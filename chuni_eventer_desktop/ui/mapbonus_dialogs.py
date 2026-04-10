from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
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
from .name_glyph_preview import wrap_name_input_with_preview


KIND_LABELS: dict[str, str] = {
    "music": "指定乐曲",
    "musicGenre": "指定流派乐曲",
    "releaseTag": "指定版本乐曲（releaseTag）",
    "chara": "指定角色",
    "charaRankGE": "角色等级>=N",
}


class MapBonusEditDialog(QDialog):
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

        self.name_id = QLineEdit()
        self.name_str = QLineEdit()
        if data is not None:
            self.name_id.setText(str(data.name_id))
            self.name_str.setText(data.name_str)
        else:
            sid = preset_id if preset_id is not None else suggest_next_mapbonus_id(acus_root)
            sstr = (preset_str or "").strip() or f"CustomMapBonus{sid}"
            self.name_id.setText(str(sid))
            self.name_str.setText(sstr)

        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["条件类型", "加成格数", "目标", "说明"])
        self.table.setColumnWidth(0, 220)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 520)
        self.table.setColumnWidth(3, 220)

        btn_add = QPushButton("新增条件")
        btn_del = QPushButton("删除条件")
        btn_add.clicked.connect(self._add_row_default)
        btn_del.clicked.connect(self._del_selected_row)
        hb = QHBoxLayout()
        hb.addWidget(btn_add)
        hb.addWidget(btn_del)
        hb.addStretch(1)

        form = QFormLayout()
        form.addRow("mapBonusName.id", self.name_id)
        form.addRow("mapBonusName.str", wrap_name_input_with_preview(self.name_str, parent=self))

        ok = QPushButton("保存")
        cancel = QPushButton("取消")
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(cancel)
        foot.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(QLabel(f"substances（命中条件，最多 {MAX_RULES} 条；底层 id/str 自动填入）"))
        lay.addWidget(self.table, stretch=1)
        lay.addLayout(hb)
        lay.addLayout(foot)

        rules = list(data.rules) if data is not None else []
        if not rules:
            rules = [MapBonusRule(kind="releaseTag", point=1, target_id=-1, target_str="Invalid", chara_rank=1, explain_text="")]
        for r in rules:
            self._append_rule_row(r)
        self.resize(980, 520)

    def _set_kind_cell(self, row: int, value: str) -> None:
        cb = QComboBox(self.table)
        for x in ALLOWED_KINDS:
            cb.addItem(KIND_LABELS.get(x, x), x)
        idx = cb.findData(value)
        cb.setCurrentIndex(idx if idx >= 0 else cb.findData("releaseTag"))
        self.table.setCellWidget(row, 0, cb)
        cb.currentIndexChanged.connect(lambda _=0, rr=row: self._sync_row_widgets(rr, keep_target=False))

    def _set_target_cell(self, row: int, *, kind: str, selected_id: int | None, selected_str: str | None) -> None:
        if kind == "charaRankGE":
            le = QLineEdit(self.table)
            if selected_id is not None and selected_id > 0:
                le.setText(str(selected_id))
            else:
                le.setText("26")
            le.setPlaceholderText("角色等级阈值（例如 26）")
            self.table.setCellWidget(row, 2, le)
            return

        cb = QComboBox(self.table)
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

        cb.addItem("(请选择)", None)
        for i, s in pairs:
            cb.addItem(f"{i} | {s}", (i, s))
        cb.setMinimumWidth(460)
        try:
            cb.view().setMinimumWidth(640)
        except Exception:
            pass
        pick = -1
        if selected_id is not None:
            for i in range(1, cb.count()):
                d = cb.itemData(i)
                if isinstance(d, tuple) and len(d) == 2 and d[0] == selected_id:
                    pick = i
                    break
        if pick < 0 and selected_str:
            for i in range(1, cb.count()):
                d = cb.itemData(i)
                if isinstance(d, tuple) and len(d) == 2 and str(d[1]) == str(selected_str):
                    pick = i
                    break
        if pick >= 0:
            cb.setCurrentIndex(pick)
        self.table.setCellWidget(row, 2, cb)

    def _append_rule_row(self, r: MapBonusRule) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_kind_cell(row, r.kind)
        self.table.setItem(row, 1, QTableWidgetItem(str(r.point)))
        target_seed_id = r.chara_rank if r.kind == "charaRankGE" else r.target_id
        self.table.setItem(row, 3, QTableWidgetItem(r.explain_text))
        self._sync_row_widgets(row, keep_target=False, selected_id=target_seed_id, selected_str=r.target_str)

    def _add_row_default(self) -> None:
        if self.table.rowCount() >= MAX_RULES:
            QMessageBox.information(self, "已达上限", f"每个 MapBonus 最多添加 {MAX_RULES} 条条件。")
            return
        self._append_rule_row(
            MapBonusRule(kind="releaseTag", point=1, target_id=-1, target_str="Invalid", chara_rank=1, explain_text="")
        )

    def _del_selected_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
        if self.table.rowCount() <= 0:
            self._add_row_default()

    def _kind_at(self, row: int) -> str:
        w = self.table.cellWidget(row, 0)
        if isinstance(w, QComboBox):
            k = str(w.currentData() or "")
            return k if k in ALLOWED_KINDS else "releaseTag"
        return "releaseTag"

    def _sync_row_widgets(
        self,
        row: int,
        *,
        keep_target: bool = True,
        selected_id: int | None = None,
        selected_str: str | None = None,
    ) -> None:
        if row < 0 or row >= self.table.rowCount():
            return
        kind = self._kind_at(row)

        keep_id = None
        keep_str = None
        if keep_target:
            w = self.table.cellWidget(row, 2)
            if isinstance(w, QComboBox):
                d = w.currentData()
                if isinstance(d, tuple) and len(d) == 2:
                    keep_id, keep_str = int(d[0]), str(d[1])
        sid = keep_id if keep_target else selected_id
        sstr = keep_str if keep_target else selected_str
        self._set_target_cell(row, kind=kind, selected_id=sid, selected_str=sstr)

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

    def _row_int(self, row: int, col: int, field: str, default: int | None = None) -> int:
        it = self.table.item(row, col)
        raw = (it.text() if it else "").strip()
        if raw == "" and default is not None:
            return default
        try:
            return int(raw)
        except Exception:
            raise ValueError(f"第 {row + 1} 行 {field} 不是整数")

    def _on_ok(self) -> None:
        try:
            mid = int((self.name_id.text() or "").strip())
        except Exception:
            QMessageBox.critical(self, "错误", "mapBonusName.id 必须是整数")
            return
        mstr = (self.name_str.text() or "").strip() or f"MapBonus{mid}"

        rules: list[MapBonusRule] = []
        if self.table.rowCount() > MAX_RULES:
            QMessageBox.critical(self, "错误", f"条件条目超过上限：最多 {MAX_RULES} 条。")
            return
        for r in range(self.table.rowCount()):
            kind = self._kind_at(r)
            pt = self._row_int(r, 1, "point", default=1)
            tbox = self.table.cellWidget(r, 2)
            tid = -1
            tstr = "Invalid"
            cr = 1
            if kind == "charaRankGE":
                if not isinstance(tbox, QLineEdit):
                    QMessageBox.critical(self, "错误", f"第 {r + 1} 行角色等级阈值输入框异常")
                    return
                raw_rank = (tbox.text() or "").strip()
                try:
                    cr = int(raw_rank)
                except Exception:
                    QMessageBox.critical(self, "错误", f"第 {r + 1} 行角色等级阈值必须是整数")
                    return
                if cr < 1:
                    QMessageBox.critical(self, "错误", f"第 {r + 1} 行角色等级阈值必须 >= 1")
                    return
                tid = -1
                tstr = "Invalid"
            else:
                if not isinstance(tbox, QComboBox):
                    QMessageBox.critical(self, "错误", f"第 {r + 1} 行目标下拉异常")
                    return
                d = tbox.currentData()
                if not (isinstance(d, tuple) and len(d) == 2):
                    QMessageBox.critical(self, "错误", f"第 {r + 1} 行请从下拉框选择目标")
                    return
                tid, tstr = int(d[0]), str(d[1])
            ex = ((self.table.item(r, 3).text() if self.table.item(r, 3) else "") or "").strip()
            rules.append(
                MapBonusRule(
                    kind=kind,
                    point=pt if pt > 0 else 1,
                    target_id=tid,
                    target_str=tstr,
                    chara_rank=cr,
                    explain_text=ex,
                )
            )
        try:
            out = save_mapbonus_xml(self._acus_root, MapBonusData(name_id=mid, name_str=mstr, rules=tuple(rules)))
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return
        self.result_name = (mid, mstr)
        self.result_xml = out
        self.accept()

