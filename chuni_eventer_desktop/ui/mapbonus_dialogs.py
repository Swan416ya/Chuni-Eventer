from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLineEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox as FluentComboBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    isDarkTheme,
)

from ..mapbonus_xml import (
    ALLOWED_KINDS,
    MAX_RULES,
    MapBonusData,
    MapBonusRule,
    load_mapbonus_xml,
    save_mapbonus_xml,
    suggest_next_mapbonus_id,
)
from ..game_data_index import GameDataIndex, merged_chara_pairs, merged_music_pairs
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .name_glyph_preview import wrap_name_input_with_preview


KIND_LABELS: dict[str, str] = {
    "music": "指定乐曲",
    "musicGenre": "指定流派乐曲",
    "releaseTag": "指定版本乐曲（releaseTag）",
    "chara": "指定角色",
    "charaRankGE": "角色等级>=N",
}


class _MapBonusRuleEditDialog(FluentCaptionDialog):
    """单条 MapBonus 条件的编辑子窗。"""

    def __init__(
        self,
        *,
        parent: QWidget,
        initial: MapBonusRule | None,
        music_pairs: list[tuple[int, str]],
        chara_pairs: list[tuple[int, str]],
        genre_pairs: list[tuple[int, str]],
        release_tag_pairs: list[tuple[int, str]],
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("编辑条件")
        self.setModal(True)
        self.resize(560, 420)
        self.saved_rule: MapBonusRule | None = None
        self.removed = False

        self._music_pairs = music_pairs
        self._chara_pairs = chara_pairs
        self._genre_pairs = genre_pairs
        self._release_tag_pairs = release_tag_pairs

        if initial is None:
            seed = MapBonusRule(
                kind="releaseTag",
                point=1,
                target_id=-1,
                target_str="Invalid",
                chara_rank=1,
                explain_text="",
            )
        else:
            seed = initial

        self._kind = FluentComboBox(self)
        for x in ALLOWED_KINDS:
            self._kind.addItem(KIND_LABELS.get(x, x), None, x)
        self._kind.blockSignals(True)
        idx = self._kind.findData(seed.kind)
        fb = self._kind.findData("releaseTag")
        self._kind.setCurrentIndex(idx if idx >= 0 else (fb if fb >= 0 else 0))
        self._kind.blockSignals(False)

        self._point = LineEdit(self)
        self._point.setText(str(seed.point))

        self._explain = LineEdit(self)
        self._explain.setText(seed.explain_text)
        self._explain.setPlaceholderText("说明（explainText，可空）")

        self._target_host = QWidget(self)
        self._target_lay = QVBoxLayout(self._target_host)
        self._target_lay.setContentsMargins(0, 0, 0, 0)
        self._target_widget: QWidget | None = None

        seed_tid = seed.chara_rank if seed.kind == "charaRankGE" else seed.target_id
        self._kind.currentIndexChanged.connect(lambda _i: self._rebuild_target(keep=True))
        self._rebuild_target(
            keep=False,
            selected_id=seed_tid,
            selected_str=seed.target_str,
        )

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("条件类型", self._kind)
        form.addRow("加成格数", self._point)
        form.addRow("目标", self._target_host)
        form.addRow("说明", self._explain)

        remove_btn = PushButton("移除此条件", self)
        remove_btn.clicked.connect(self._on_remove)
        ok_btn = PrimaryPushButton("保存", self)
        ok_btn.clicked.connect(self._on_save)
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addWidget(remove_btn)
        foot.addStretch(1)
        foot.addWidget(cancel_btn)
        foot.addWidget(ok_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addLayout(form)
        lay.addStretch(1)
        lay.addLayout(foot)

    def _kind_val(self) -> str:
        k = self._kind.currentData()
        s = str(k or "")
        return s if s in ALLOWED_KINDS else "releaseTag"

    def _rebuild_target(
        self,
        *,
        keep: bool,
        selected_id: int | None = None,
        selected_str: str | None = None,
    ) -> None:
        keep_id = None
        keep_str = None
        if keep:
            w = self._target_widget
            if isinstance(w, FluentComboBox):
                d = w.currentData()
                if isinstance(d, tuple) and len(d) == 2:
                    keep_id, keep_str = int(d[0]), str(d[1])
            elif isinstance(w, LineEdit):
                try:
                    keep_id = int((w.text() or "").strip())
                except ValueError:
                    keep_id = None
                keep_str = None
        sid = keep_id if keep else selected_id
        sstr = keep_str if keep else selected_str

        while self._target_lay.count():
            it = self._target_lay.takeAt(0)
            if it.widget() is not None:
                it.widget().deleteLater()
        self._target_widget = None
        kind = self._kind_val()

        if kind == "charaRankGE":
            le = LineEdit(self._target_host)
            if sid is not None and sid > 0:
                le.setText(str(sid))
            else:
                le.setText("26")
            le.setPlaceholderText("角色等级阈值（例如 26）")
            self._target_lay.addWidget(le)
            self._target_widget = le
            return

        cb = FluentComboBox(self._target_host)
        pairs: list[tuple[int, str]]
        if kind == "music":
            pairs = self._music_pairs
        elif kind == "musicGenre":
            pairs = self._genre_pairs
        elif kind == "releaseTag":
            pairs = self._release_tag_pairs
        elif kind == "chara":
            pairs = self._chara_pairs
        else:
            pairs = [(-1, "Invalid")]

        cb.addItem("(请选择)", None, None)
        for i, s in pairs:
            cb.addItem(f"{i} | {s}", None, (i, s))
        cb.setMinimumWidth(400)
        try:
            cb.view().setMinimumWidth(560)
        except Exception:
            pass
        pick = -1
        if sid is not None:
            for i in range(1, cb.count()):
                d = cb.itemData(i)
                if isinstance(d, tuple) and len(d) == 2 and d[0] == sid:
                    pick = i
                    break
        if pick < 0 and sstr:
            for i in range(1, cb.count()):
                d = cb.itemData(i)
                if isinstance(d, tuple) and len(d) == 2 and str(d[1]) == str(sstr):
                    pick = i
                    break
        if pick >= 0:
            cb.setCurrentIndex(pick)
        self._target_lay.addWidget(cb)
        self._target_widget = cb

    def _on_remove(self) -> None:
        self.removed = True
        self.saved_rule = None
        self.accept()

    def _on_save(self) -> None:
        kind = self._kind_val()
        raw_pt = (self._point.text() or "").strip()
        try:
            pt = int(raw_pt) if raw_pt else 1
        except ValueError:
            fly_critical(self, "错误", "加成格数必须是整数")
            return
        if pt < 1:
            pt = 1
        tid = -1
        tstr = "Invalid"
        cr = 1
        tw = self._target_widget
        if kind == "charaRankGE":
            if not isinstance(tw, LineEdit):
                fly_critical(self, "错误", "目标输入异常")
                return
            raw_rank = (tw.text() or "").strip()
            try:
                cr = int(raw_rank)
            except ValueError:
                fly_critical(self, "错误", "角色等级阈值必须是整数")
                return
            if cr < 1:
                fly_critical(self, "错误", "角色等级阈值必须 >= 1")
                return
            tid = -1
            tstr = "Invalid"
        else:
            if not isinstance(tw, FluentComboBox):
                fly_critical(self, "错误", "目标下拉异常")
                return
            d = tw.currentData()
            if not (isinstance(d, tuple) and len(d) == 2):
                fly_critical(self, "错误", "请从下拉框选择目标")
                return
            tid, tstr = int(d[0]), str(d[1])
        ex = (self._explain.text() or "").strip()
        self.saved_rule = MapBonusRule(
            kind=kind,
            point=pt,
            target_id=tid,
            target_str=tstr,
            chara_rank=cr,
            explain_text=ex,
        )
        self.removed = False
        self.accept()


def _slot_button_style() -> str:
    dark = isDarkTheme()
    bg = "#27272A" if dark else "#FAFAFA"
    bd = "#52525B" if dark else "#D4D4D8"
    bg_h = "#3F3F46" if dark else "#F4F4F5"
    bd_h = "#71717A" if dark else "#A1A1AA"
    fg = "#E4E4E7" if dark else "#3F3F46"
    return (
        f"QPushButton{{background:{bg};border:2px dashed {bd};border-radius:10px;color:{fg};"
        "padding:12px;text-align:left;}}"
        f"QPushButton:hover{{background:{bg_h};border:2px solid {bd_h};}}"
    )


def _format_slot_text(index: int, rule: MapBonusRule | None) -> str:
    n = index + 1
    if rule is None:
        return f"条件 {n}\n（空白 · 点击添加）"
    kind_cn = KIND_LABELS.get(rule.kind, rule.kind)
    if rule.kind == "charaRankGE":
        tgt = f"等级 ≥ {rule.chara_rank}"
    else:
        ts = (rule.target_str or "").strip() or "—"
        if len(ts) > 28:
            ts = ts[:26] + "…"
        tgt = f"{rule.target_id} · {ts}"
    return f"条件 {n}\n{kind_cn}\n加成格数 {rule.point}\n{tgt}"


class MapBonusEditDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        acus_root: Path,
        game_index: GameDataIndex | None = None,
        xml_path: Path | None = None,
        preset_id: int | None = None,
        preset_str: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setModal(True)
        self._acus_root = acus_root
        self._game_index = game_index
        self.result_name: tuple[int, str] | None = None
        self.result_xml: Path | None = None
        self._music_pairs = merged_music_pairs(self._acus_root, self._game_index)
        self._chara_pairs = merged_chara_pairs(self._acus_root, self._game_index)
        self._genre_pairs, self._release_tag_pairs = self._collect_genre_and_release_tags()

        data = None
        if xml_path is not None and xml_path.is_file():
            data = load_mapbonus_xml(xml_path)
            self.setWindowTitle("编辑 MapBonus")
        else:
            self.setWindowTitle("新建 MapBonus")

        self.name_id = LineEdit(self)
        self.name_str = LineEdit(self)
        if data is not None:
            self.name_id.setText(str(data.name_id))
            self.name_str.setText(data.name_str)
        else:
            sid = preset_id if preset_id is not None else suggest_next_mapbonus_id(acus_root)
            sstr = (preset_str or "").strip() or f"CustomMapBonus{sid}"
            self.name_id.setText(str(sid))
            self.name_str.setText(sstr)

        self._slots: list[MapBonusRule | None] = [None] * MAX_RULES
        if data is not None:
            for i, r in enumerate(list(data.rules)[:MAX_RULES]):
                self._slots[i] = r

        self._slot_btns: list[PushButton] = []
        grid = QGridLayout()
        grid.setSpacing(12)
        for i in range(MAX_RULES):
            row, col = divmod(i, 2)
            btn = PushButton(self)
            btn.setMinimumHeight(120)
            btn.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Expanding,
            )
            btn.setStyleSheet(_slot_button_style())
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, idx=i: self._edit_slot(idx))
            self._slot_btns.append(btn)
            grid.addWidget(btn, row, col)
        for r in range(2):
            grid.setRowStretch(r, 1)
        for c in range(2):
            grid.setColumnStretch(c, 1)

        name_card = CardWidget(self)
        name_lay = QVBoxLayout(name_card)
        name_lay.setContentsMargins(16, 14, 16, 14)
        name_lay.setSpacing(10)
        name_lay.addWidget(BodyLabel("MapBonus 标识", self))
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("mapBonusName.id", self.name_id)
        form.addRow("mapBonusName.str", wrap_name_input_with_preview(self.name_str, parent=self))
        name_lay.addLayout(form)

        rules_card = CardWidget(self)
        rules_lay = QVBoxLayout(rules_card)
        rules_lay.setContentsMargins(16, 14, 16, 14)
        rules_lay.setSpacing(10)
        rules_lay.addWidget(BodyLabel("命中条件（最多 4 条）", self))
        hint = BodyLabel(self)
        hint.setWordWrap(True)
        hint.setText(
            "点击下方格子编辑对应序号条件；空白格表示未使用。保存时按条件 1→4 的顺序写入 XML，"
            "自动跳过空白格。若全部空白，将写入一条默认占位条件。"
        )
        hint.setTextColor("#6B7280", "#9CA3AF")
        rules_lay.addWidget(hint)
        rules_lay.addLayout(grid, stretch=1)

        ok = PrimaryPushButton("保存", self)
        ok.clicked.connect(self._on_ok)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(cancel)
        foot.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(name_card)
        lay.addWidget(rules_card, stretch=1)
        lay.addLayout(foot)

        for i in range(MAX_RULES):
            self._refresh_slot_button(i)
        self.resize(720, 560)

    def _refresh_slot_button(self, index: int) -> None:
        self._slot_btns[index].setText(_format_slot_text(index, self._slots[index]))

    def _edit_slot(self, index: int) -> None:
        dlg = _MapBonusRuleEditDialog(
            parent=self,
            initial=self._slots[index],
            music_pairs=self._music_pairs,
            chara_pairs=self._chara_pairs,
            genre_pairs=self._genre_pairs,
            release_tag_pairs=self._release_tag_pairs,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if dlg.removed:
                self._slots[index] = None
            else:
                self._slots[index] = dlg.saved_rule
            self._refresh_slot_button(index)

    def _collect_genre_and_release_tags(self) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
        genre_map: dict[int, str] = {}
        rt_map: dict[int, str] = {}

        roots: list[Path] = []
        if self._game_index is not None:
            try:
                gr = Path(self._game_index.game_root).resolve()
                for rel in self._game_index.roots_scanned:
                    rp = (gr / rel).resolve()
                    if rp.is_dir():
                        roots.append(rp)
            except Exception:
                pass
            for row in self._game_index.music_catalog:
                try:
                    rid = int(row.get("release_tag_id")) if row.get("release_tag_id") is not None else None
                except Exception:
                    rid = None
                rs = str(row.get("release_tag_str") or "").strip()
                if rid is not None and rid >= 0 and rs:
                    rt_map.setdefault(rid, rs)

        a001 = self._acus_root.parent / "A001"
        if a001.is_dir():
            roots.append(a001.resolve())
        roots.append(self._acus_root.resolve())

        seen = set()
        uniq_roots: list[Path] = []
        for r in roots:
            if r in seen:
                continue
            seen.add(r)
            uniq_roots.append(r)

        for root in uniq_roots:
            for p in root.glob("music/**/Music.xml"):
                try:
                    x = ET.parse(p).getroot()
                except Exception:
                    continue
                for g in x.findall("genreNames/list/StringID"):
                    try:
                        gid = int((g.findtext("id") or "").strip())
                    except Exception:
                        continue
                    gs = (g.findtext("str") or "").strip()
                    if gs:
                        genre_map.setdefault(gid, gs)
                try:
                    rid = int((x.findtext("releaseTagName/id") or "").strip())
                except Exception:
                    rid = None
                rs = (x.findtext("releaseTagName/str") or "").strip()
                if rid is not None and rid >= 0 and rs:
                    rt_map.setdefault(rid, rs)

        genres = sorted(genre_map.items(), key=lambda x: x[0])
        rt_map.setdefault(-1, "Invalid")
        rt_map.setdefault(-2, "PJSK")
        release_tags = sorted(rt_map.items(), key=lambda x: x[0])
        return genres, release_tags

    def _on_ok(self) -> None:
        try:
            mid = int((self.name_id.text() or "").strip())
        except Exception:
            fly_critical(self, "错误", "mapBonusName.id 必须是整数")
            return
        mstr = (self.name_str.text() or "").strip() or f"MapBonus{mid}"

        rules: list[MapBonusRule] = [r for r in self._slots if r is not None]
        if len(rules) > MAX_RULES:
            fly_critical(self, "错误", f"条件条目超过上限：最多 {MAX_RULES} 条。")
            return
        try:
            out = save_mapbonus_xml(
                self._acus_root,
                MapBonusData(name_id=mid, name_str=mstr, rules=tuple(rules)),
            )
        except Exception as e:
            fly_critical(self, "保存失败", str(e))
            return
        self.result_name = (mid, mstr)
        self.result_xml = out
        self.accept()
