from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ComboBox as FluentComboBox, LineEdit, PrimaryPushButton, PushButton

from ..course_rule import CourseRuleParams, build_course_rule_explain
from ..course_rank import (
    RANK_COURSE_SLOT_COUNT,
    RANK_DIFFICULTIES,
    RankCourseDraft,
    RankCourseItem,
    apply_music_meta_to_draft,
    default_rank_course_draft,
    load_rank_course_draft,
    music_diff_choices,
    write_rank_course_xml,
)
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

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
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
        self._music_id = 0
        self._music_title = ""

        self._label = BodyLabel(f"曲目 {index + 1}", self)
        self._music_display = LineEdit(self)
        self._music_display.setReadOnly(True)
        self._music_display.setPlaceholderText("点击右侧按钮选择乐曲…")
        self._pick_btn = PushButton("选择…", self)
        self._pick_btn.clicked.connect(self._open_picker)
        self.diff_combo = FluentComboBox(self)
        for did, dstr, _ddata in music_diff_choices():
            self.diff_combo.addItem(dstr, None, did)
        self.diff_combo.setCurrentIndex(3)

        music_row = QHBoxLayout()
        music_row.setContentsMargins(0, 0, 0, 0)
        music_row.setSpacing(8)
        music_row.addWidget(self._music_display, stretch=1)
        music_row.addWidget(self._pick_btn)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self._label)
        lay.addLayout(music_row, stretch=1)
        lay.addWidget(self.diff_combo)

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
        self.resize(760, 620)

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
        cly.addWidget(
            BodyLabel(
                "保存时会写入 ACUS/course/…/Course.xml，并自动生成/更新 ACUS/courseRule/…/CourseRule.xml "
                "（规则 ID 从 7001 起分配）。通关奖励使用默认值。"
                "CourseSort 会先从【设置】中的游戏数据目录复制官方列表，再把自制课题追加到末尾。"
            )
        )

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
                if slot.music_id > 0:
                    row.set_music(slot.music_id, slot.music_str)
                row.set_diff_id(slot.diff_id)
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

        from ..course_rank import CourseMusicSlot

        slots: list[CourseMusicSlot] = []
        for row in self._slot_rows:
            mid = row.music_id()
            if mid <= 0:
                fly_critical(self, "错误", "请为 3 首曲目都选择有效乐曲。")
                return None
            diff_id_m = row.diff_id()
            title = row.music_title()
            dstr = next((s for i, s, _ in music_diff_choices() if i == diff_id_m), "Master")
            ddata = next((d for i, _, d in music_diff_choices() if i == diff_id_m), "MASTER")
            slots.append(CourseMusicSlot(mid, title, diff_id_m, dstr, ddata))

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
        apply_music_meta_to_draft(self._acus_root, draft, slots[0].music_id)
        return draft

    def _save(self) -> None:
        draft = self._collect_draft()
        if draft is None:
            return
        try:
            write_rank_course_xml(acus_root=self._acus_root, draft=draft, is_edit=self._is_edit, game_root=self._game_root)
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
