from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, ComboBox as FluentComboBox, LineEdit, PrimaryPushButton, PushButton, SegmentedWidget

from ..course_rank import (
    RANK_COURSE_SLOT_COUNT,
    RANK_DIFFICULTIES,
    CourseMusicCandidate,
    CourseMusicSlot,
    RANDOM_LEVEL_CHOICES,
    RankCourseDraft,
    RankCourseItem,
    _level_id_to_label,
    apply_music_meta_to_draft,
    default_rank_course_draft,
    load_rank_course_draft,
    music_diff_choices,
    write_rank_course_xml,
)
from ..course_rule import CourseRuleParams, build_course_rule_explain
from ..game_data_index import GameDataIndex
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .music_picker_dialog import pick_music
from .name_glyph_preview import wrap_name_input_with_preview


class _RuleParamsRow(QWidget):
    """CourseRule 回血 / 各判定扣血 — 单行输入。"""

    def __init__(self, *, initial: CourseRuleParams, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.recovery_edit = LineEdit(self)
        self.recovery_edit.setText(str(initial.recovery_life))
        self.life_edit = LineEdit(self)
        self.life_edit.setText(str(initial.life))
        self.miss_edit = LineEdit(self)
        self.miss_edit.setText(str(initial.damage_miss))
        self.attack_edit = LineEdit(self)
        self.attack_edit.setText(str(initial.damage_attack))
        self.justice_edit = LineEdit(self)
        self.justice_edit.setText(str(initial.damage_justice))
        self.jc_edit = LineEdit(self)
        self.jc_edit.setText(str(initial.damage_justice_c))

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        specs = (
            ("总血量", self.life_edit),
            ("每曲回血", self.recovery_edit),
            ("Miss扣血", self.miss_edit),
            ("Attack扣血", self.attack_edit),
            ("Justice扣血", self.justice_edit),
            ("J-C扣血", self.jc_edit),
        )
        for col, (label, edit) in enumerate(specs):
            grid.addWidget(BodyLabel(label, self), 0, col)
            edit.setMaximumWidth(72)
            grid.addWidget(edit, 1, col)
            grid.setColumnStretch(col, 0)
        grid.setAlignment(Qt.AlignmentFlag.AlignLeft)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)
        outer.addLayout(grid)
        self._explain_preview = BodyLabel("", self)
        self._explain_preview.setWordWrap(True)
        self._explain_preview.setStyleSheet("color:#6b7280;")
        outer.addWidget(self._explain_preview)
        for edit in (
            self.life_edit,
            self.recovery_edit,
            self.miss_edit,
            self.attack_edit,
            self.justice_edit,
            self.jc_edit,
        ):
            edit.textChanged.connect(self._refresh_explain_preview)
        self._refresh_explain_preview()

    def _refresh_explain_preview(self) -> None:
        params = self.params_or_none(silent=True)
        if params is None:
            self._explain_preview.setText("规则说明预览：（请填写有效整数）")
            return
        self._explain_preview.setText(f"规则说明预览：{build_course_rule_explain(params)}")

    def params_or_none(self, *, silent: bool = False) -> CourseRuleParams | None:
        def _read(edit: LineEdit, label: str) -> int | None:
            try:
                return int(edit.text().strip())
            except ValueError:
                if not silent:
                    fly_critical(self.window(), "错误", f"{label}须为整数。")
                return None

        rec = _read(self.recovery_edit, "每曲回血")
        life = _read(self.life_edit, "总血量")
        miss = _read(self.miss_edit, "Miss扣血")
        atk = _read(self.attack_edit, "Attack扣血")
        j = _read(self.justice_edit, "Justice扣血")
        jc = _read(self.jc_edit, "J-C扣血")
        if None in (rec, life, miss, atk, j, jc):
            return None
        assert (
            rec is not None
            and life is not None
            and miss is not None
            and atk is not None
            and j is not None
            and jc is not None
        )
        return CourseRuleParams(
            recovery_life=rec,
            damage_miss=miss,
            damage_attack=atk,
            damage_justice=j,
            damage_justice_c=jc,
            life=life,
        )


class _MusicSlotRow(QWidget):
    """一个曲目槽位，支持三种选曲模式：固定/等级随机/候选池随机。"""

    MODE_FIXED = 0       # type=0 固定选曲
    MODE_LEVEL = 1       # type=1 按等级池随机
    MODE_POOL = 2        # type=2 按候选池随机

    def __init__(
        self,
        *,
        index: int,
        acus_root: Path,
        game_root: str,
        get_index: Callable[[], GameDataIndex | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._acus_root = acus_root
        self._game_root = game_root
        self._get_index = get_index
        self._index = index
        self._music_id = -1
        self._music_title = ""

        # === 模式切换 ===
        self._mode_seg = SegmentedWidget(self)
        self._mode_seg.addItem("fixed", "固定选曲")
        self._mode_seg.addItem("level", "等级随机")
        self._mode_seg.addItem("pool", "候选池随机")
        self._mode_seg.setCurrentItem("fixed")
        self._mode_seg.currentItemChanged.connect(self._on_mode_changed)

        # === 固定选曲面板 ===
        self._fixed_panel = QWidget(self)
        self._music_display = LineEdit(self._fixed_panel)
        self._music_display.setReadOnly(True)
        self._music_display.setPlaceholderText("点击右侧按钮选择乐曲…")
        self._pick_btn = PushButton("选择…", self._fixed_panel)
        self._pick_btn.clicked.connect(self._open_picker)
        self.diff_combo = FluentComboBox(self._fixed_panel)
        for did, dstr, _ddata in music_diff_choices():
            self.diff_combo.addItem(dstr, None, did)
        self.diff_combo.setCurrentIndex(3)
        fixed_row = QHBoxLayout(self._fixed_panel)
        fixed_row.setContentsMargins(0, 0, 0, 0)
        fixed_row.setSpacing(8)
        fixed_row.addWidget(self._music_display, stretch=1)
        fixed_row.addWidget(self._pick_btn)
        fixed_row.addWidget(self.diff_combo)

        # === 等级随机面板 ===
        self._level_panel = QWidget(self)
        self._level_combo = FluentComboBox(self._level_panel)
        for lid, lstr in RANDOM_LEVEL_CHOICES:
            self._level_combo.addItem(lstr, None, lid)
        self._level_combo.setCurrentIndex(0)
        level_hint = CaptionLabel("从全曲库中符合该等级的曲目随机选一首", self._level_panel)
        level_lay = QVBoxLayout(self._level_panel)
        level_lay.setContentsMargins(0, 0, 0, 0)
        level_lay.setSpacing(6)
        level_lay.addWidget(self._level_combo)
        level_lay.addWidget(level_hint)

        # === 候选池随机面板 ===
        self._pool_panel = QWidget(self)
        self._pool_candidates: list[CourseMusicCandidate] = []
        self._pool_list_label = CaptionLabel("候选池：0 首", self._pool_panel)
        self._pool_diff_combo = FluentComboBox(self._pool_panel)
        for did, dstr, _ddata in music_diff_choices():
            self._pool_diff_combo.addItem(dstr, None, did)
        self._pool_diff_combo.setCurrentIndex(3)
        self._pool_add_btn = PushButton("添加候选…", self._pool_panel)
        self._pool_add_btn.clicked.connect(self._add_pool_candidate)
        self._pool_clear_btn = PushButton("清空", self._pool_panel)
        self._pool_clear_btn.clicked.connect(self._clear_pool_candidates)
        pool_row = QHBoxLayout(self._pool_panel)
        pool_row.setContentsMargins(0, 0, 0, 0)
        pool_row.setSpacing(8)
        pool_row.addWidget(self._pool_list_label, stretch=1)
        pool_row.addWidget(self._pool_diff_combo)
        pool_row.addWidget(self._pool_add_btn)
        pool_row.addWidget(self._pool_clear_btn)

        # === StackedWidget 切换三种面板 ===
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._fixed_panel)
        self._stack.addWidget(self._level_panel)
        self._stack.addWidget(self._pool_panel)

        # === 总布局 ===
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(BodyLabel(f"曲目 {index + 1}"))
        title_row.addStretch(1)
        title_row.addWidget(self._mode_seg)
        lay.addLayout(title_row)
        lay.addWidget(self._stack)

    def _on_mode_changed(self, key: str) -> None:
        if key == "fixed":
            self._stack.setCurrentIndex(0)
        elif key == "level":
            self._stack.setCurrentIndex(1)
        else:  # pool
            self._stack.setCurrentIndex(2)

    def _open_picker(self) -> None:
        picked = pick_music(
            parent=self.window(),
            acus_root=self._acus_root,
            game_root=self._game_root,
            get_index=self._get_index,
            preselect_id=self._music_id if self._music_id > 0 else None,
        )
        if picked is None:
            return
        mid, title = picked
        self.set_music(mid, title)

    def _add_pool_candidate(self) -> None:
        picked = pick_music(
            parent=self.window(),
            acus_root=self._acus_root,
            game_root=self._game_root,
            get_index=self._get_index,
        )
        if picked is None:
            return
        mid, title = picked
        did = self._pool_diff_combo.currentData() or 3
        dstr = next((s for i, s, _ in music_diff_choices() if i == did), "Master")
        ddata = next((d for i, _, d in music_diff_choices() if i == did), dstr.upper())
        self._pool_candidates.append(CourseMusicCandidate(mid, title, did, dstr, ddata))
        self._refresh_pool_label()

    def _clear_pool_candidates(self) -> None:
        self._pool_candidates.clear()
        self._refresh_pool_label()

    def _refresh_pool_label(self) -> None:
        self._pool_list_label.setText(f"候选池：{len(self._pool_candidates)} 首")

    # === 状态读写（供 _collect_draft 调用）===

    def set_mode(self, slot_type: int) -> None:
        if slot_type == 1:
            self._mode_seg.setCurrentItem("level")
        elif slot_type == 2:
            self._mode_seg.setCurrentItem("pool")
        else:
            self._mode_seg.setCurrentItem("fixed")

    def current_mode(self) -> int:
        key = self._mode_seg.currentItem()
        if key == "level":
            return 1
        if key == "pool":
            return 2
        return 0

    # --- 固定面板状态 ---
    def set_music(self, music_id: int, title: str) -> None:
        self._music_id = int(music_id)
        self._music_title = (title or "").strip() or (f"Music{music_id}" if music_id > 0 else "")
        if self._music_id > 0:
            self._music_display.setText(f"{self._music_id} · {self._music_title}")
        else:
            self._music_display.clear()

    def set_diff_id(self, diff_id: int) -> None:
        idx = self.diff_combo.findData(int(diff_id))
        if idx >= 0:
            self.diff_combo.setCurrentIndex(idx)

    def music_id(self) -> int:
        return self._music_id

    def music_title(self) -> str:
        return self._music_title

    def diff_id(self) -> int:
        v = self.diff_combo.currentData()
        return int(v) if v is not None else 3

    # --- 等级随机面板状态 ---
    def set_level_id(self, level_id: int) -> None:
        idx = self._level_combo.findData(int(level_id))
        if idx >= 0:
            self._level_combo.setCurrentIndex(idx)

    def level_id(self) -> int:
        v = self._level_combo.currentData()
        return int(v) if v is not None else 19

    # --- 候选池随机面板状态 ---
    def set_candidates(self, candidates: list[CourseMusicCandidate]) -> None:
        self._pool_candidates = list(candidates)
        self._refresh_pool_label()

    def candidates(self) -> tuple[CourseMusicCandidate, ...]:
        return tuple(self._pool_candidates)

    # --- 通用构造 ---
    def to_slot(self) -> CourseMusicSlot:
        """从当前 UI 状态构造 CourseMusicSlot。"""
        mode = self.current_mode()
        if mode == 1:
            return CourseMusicSlot(
                slot_type=1,
                level_id=self.level_id(),
                music_str=_level_id_to_label(self.level_id()),
            )
        if mode == 2:
            cands = self.candidates()
            return CourseMusicSlot(
                slot_type=2,
                candidates=cands,
                music_str=f"{len(cands)}首候选",
            )
        # mode == 0 固定
        did = self.diff_id()
        dstr = next((s for i, s, _ in music_diff_choices() if i == did), "Master")
        ddata = next((d for i, _, d in music_diff_choices() if i == did), "MASTER")
        return CourseMusicSlot(
            self.music_id(),
            self.music_title(),
            did,
            dstr,
            ddata,
        )


class CourseRankEditDialog(FluentCaptionDialog):
    """新增/编辑段位组曲（CLASS Ⅰ～Ⅴ Course + CourseRule）。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        game_root: str = "",
        get_index: Callable[[], GameDataIndex | None] | None = None,
        game_index: GameDataIndex | None = None,
        edit_xml: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._game_root = (game_root or "").strip()
        if get_index is not None:
            self._get_index = get_index
        else:
            self._get_index = lambda: game_index
        self._edit_xml = edit_xml

        is_edit = edit_xml is not None and edit_xml.is_file()
        self.setWindowTitle("编辑段位组曲" if is_edit else "新增段位组曲")
        self.setModal(True)
        self.resize(640, 620)

        draft: RankCourseDraft | None = None
        if is_edit and edit_xml is not None:
            draft = load_rank_course_draft(acus_root, edit_xml)
        if draft is None:
            draft = default_rank_course_draft(acus_root)
        self._draft = draft
        self._is_edit = is_edit

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        form = QFormLayout()
        self.id_edit = LineEdit(self)
        self.id_edit.setText(str(draft.course_id))
        self.id_edit.setReadOnly(is_edit)
        self.name_edit = LineEdit(self)
        self.name_edit.setText(draft.course_name)
        self.diff_combo = FluentComboBox(self)
        for did, _ds, ddata in RANK_DIFFICULTIES:
            self.diff_combo.addItem(ddata, None, did)
        diff_idx = self.diff_combo.findData(draft.difficulty_id)
        if diff_idx >= 0:
            self.diff_combo.setCurrentIndex(diff_idx)
        self._rule_id_hint = BodyLabel(
            f"当前绑定 CourseRule ID：{draft.rule_id}" if is_edit and draft.rule_id > 0 else "CourseRule ID：保存时自动分配（≥7001）",
            self,
        )
        self._rule_id_hint.setStyleSheet("color:#6b7280;")

        form.addRow("课题 ID", self.id_edit)
        form.addRow("显示名", wrap_name_input_with_preview(self.name_edit))
        form.addRow("段位", self.diff_combo)
        form.addRow("课题规则", self._rule_id_hint)
        cly.addLayout(form)

        cly.addWidget(BodyLabel("CourseRule 参数（总血量 / 每曲结束回血 / 各判定扣血）"))
        self._rule_row = _RuleParamsRow(initial=draft.rule_params, parent=self)
        cly.addWidget(self._rule_row)

        cly.addWidget(BodyLabel("组曲曲目（3 首）"))
        self._slot_rows: list[_MusicSlotRow] = []
        for i in range(RANK_COURSE_SLOT_COUNT):
            row = _MusicSlotRow(
                index=i,
                acus_root=self._acus_root,
                game_root=self._game_root,
                get_index=self._get_index,
                parent=self,
            )
            if i < len(draft.music_slots):
                slot = draft.music_slots[i]
                row.set_mode(slot.slot_type)
                if slot.is_fixed:
                    row.set_music(slot.music_id, slot.music_str)
                    row.set_diff_id(slot.diff_id)
                elif slot.is_level_random:
                    row.set_level_id(slot.level_id)
                elif slot.is_pool_random:
                    row.set_candidates(list(slot.candidates))
            self._slot_rows.append(row)
            cly.addWidget(row)

        ok = PrimaryPushButton("保存到 ACUS", self)
        ok.clicked.connect(self._save)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card)
        lay.addStretch(1)
        lay.addLayout(btns)

    def _collect_draft(self) -> RankCourseDraft | None:
        try:
            cid = int(self.id_edit.text().strip())
        except ValueError:
            fly_critical(self, "错误", "课题 ID 须为整数。")
            return None
        name = self.name_edit.text().strip()
        if not name:
            fly_critical(self, "错误", "请填写显示名。")
            return None
        diff_id = int(self.diff_combo.currentData() or 14)
        rule_params = self._rule_row.params_or_none()
        if rule_params is None:
            return None

        slots: list[CourseMusicSlot] = []
        for i, row in enumerate(self._slot_rows):
            mode = row.current_mode()
            if mode == 0:
                # 固定选曲：校验 mid > 0
                mid = row.music_id()
                if mid <= 0:
                    fly_critical(
                        self, "曲目未选择",
                        f"请为曲目 {i + 1} 选择有效乐曲，或切换为随机模式。",
                    )
                    return None
                slots.append(row.to_slot())
            elif mode == 1:
                # 等级随机：无需校验（level_combo 总有值）
                slots.append(row.to_slot())
            elif mode == 2:
                # 候选池随机：校验至少 1 个候选
                if not row.candidates():
                    fly_critical(
                        self, "候选池为空",
                        f"请为曲目 {i + 1} 添加至少 1 首候选乐曲。",
                    )
                    return None
                slots.append(row.to_slot())

        draft = RankCourseDraft(
            course_id=cid,
            course_name=name,
            difficulty_id=diff_id,
            rule_id=self._draft.rule_id,
            reward_id=self._draft.reward_id,
            reward_str=self._draft.reward_str,
            rule_params=rule_params,
            release_tag_id=self._draft.release_tag_id,
            release_tag_str=self._draft.release_tag_str,
            net_open_id=self._draft.net_open_id,
            net_open_str=self._draft.net_open_str,
            music_slots=slots,
        )
        # 找第一个固定 slot 读取 release_tag / net_open；如果全是随机则跳过
        first_fixed_id = -1
        for s in slots:
            if s.is_fixed and s.music_id > 0:
                first_fixed_id = s.music_id
                break
        if first_fixed_id > 0:
            apply_music_meta_to_draft(self._acus_root, draft, first_fixed_id)
        return draft

    def _save(self) -> None:
        draft = self._collect_draft()
        if draft is None:
            return
        try:
            write_rank_course_xml(
                acus_root=self._acus_root,
                draft=draft,
                is_edit=self._is_edit,
                game_root=self._game_root,
            )
        except Exception as e:
            fly_critical(self, "写入失败", str(e))
            return
        self.accept()


def open_course_rank_editor(
    *,
    acus_root: Path,
    game_root: str = "",
    get_index: Callable[[], GameDataIndex | None] | None = None,
    game_index: GameDataIndex | None = None,
    item: RankCourseItem | None = None,
    parent=None,
) -> bool:
    dlg = CourseRankEditDialog(
        acus_root=acus_root,
        game_root=game_root,
        get_index=get_index,
        game_index=game_index,
        edit_xml=item.xml_path if item else None,
        parent=parent,
    )
    return dlg.exec() == dlg.DialogCode.Accepted