from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, CardWidget, ComboBox as FluentComboBox, LineEdit, PrimaryPushButton, PushButton

from ..game_data_assets import resolve_catalog_xml_path, set_default_have_in_xml
from ..game_data_index import (
    GameDataIndex,
    catalog_release_tag_id,
    format_release_tag_version,
    iter_release_tag_filter_options,
    patch_catalog_default_have,
    scan_game_chara_catalog,
    scan_game_music_catalog,
    scan_game_nameplate_catalog,
    scan_game_trophy_catalog,
)
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_warning
from .fluent_table import apply_fluent_sheet_table, set_default_have_cell
from .game_data_detail_dialog import (
    GameMusicDetailDialog,
    open_chara_image_dialog,
    open_row_image_dialog,
)

GameDataKind = Literal["music", "chara", "nameplate", "trophy"]

_DEFAULT_HAVE_KINDS = frozenset({"music", "nameplate", "trophy"})

_KIND_META: dict[GameDataKind, dict[str, Any]] = {
    "music": {
        "title": "游戏乐曲",
        "hint": "双击行查看曲绘与导出音频。可按版本 ID、流派筛选。勾选「强制解锁」会写回 Music.xml 的 defaultHave。",
        "columns": ["ID", "曲名", "艺术家", "流派", "发布日", "版本", "数据包"],
        "catalog_attr": "music_catalog",
        "scan": scan_game_music_catalog,
        "filters": ("tag", "genre"),
    },
    "chara": {
        "title": "游戏角色",
        "hint": "双击行预览默认立绘 DDS（多变体可切换），并可导出 PNG。可按版本 ID、作品筛选。",
        "columns": ["ID", "名称", "作品", "版本", "默认立绘键", "数据包"],
        "catalog_attr": "chara_catalog",
        "scan": scan_game_chara_catalog,
        "filters": ("tag", "works", "source"),
    },
    "nameplate": {
        "title": "游戏名牌",
        "hint": "双击行预览名牌贴图 DDS，并可导出 PNG。可按版本 ID 筛选。勾选「强制解锁」会写回 NamePlate.xml 的 defaultHave。",
        "columns": ["ID", "名称", "版本", "数据包"],
        "catalog_attr": "nameplate_catalog",
        "scan": scan_game_nameplate_catalog,
        "filters": ("tag", "source"),
    },
    "trophy": {
        "title": "游戏称号",
        "hint": "双击行预览称号贴图 DDS，并可导出 PNG。可按稀有度筛选。勾选「强制解锁」会写回 Trophy.xml 的 defaultHave。",
        "columns": ["ID", "名称", "稀有度", "说明", "数据包"],
        "catalog_attr": "trophy_catalog",
        "scan": scan_game_trophy_catalog,
        "filters": ("rare", "source"),
    },
}


class GameDataBrowseDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        kind: GameDataKind,
        game_root: Path,
        acus_root: Path,
        get_index: Callable[[], GameDataIndex | None],
        get_tool_path: Callable[[], Path | None],
        parent=None,
    ) -> None:
        meta = _KIND_META[kind]
        super().__init__(parent=parent)
        self._kind = kind
        self._meta = meta
        self._game_root = game_root.expanduser().resolve()
        self._acus_root = acus_root
        self._get_index = get_index
        self._get_tool_path = get_tool_path
        self._rows: list[dict[str, Any]] = []
        self._populating_table = False
        self._has_default_have_col = kind in _DEFAULT_HAVE_KINDS

        self.setWindowTitle(str(meta["title"]))
        self.setModal(True)
        self.resize(1000, 580)

        hint = BodyLabel(str(meta["hint"]), self)
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6B7280;")

        self._filter_tag = FluentComboBox(self)
        self._filter_tag.addItem("全部版本", None, "")
        self._filter_genre = FluentComboBox(self)
        self._filter_genre.addItem("全部流派", None, "")
        self._filter_works = FluentComboBox(self)
        self._filter_works.addItem("全部作品", None, "")
        self._filter_rare = FluentComboBox(self)
        self._filter_rare.addItem("全部稀有度", None, "")
        self._filter_source = FluentComboBox(self)
        self._filter_source.addItem("全部数据包", None, "")

        self._search = LineEdit(self)
        self._search.setPlaceholderText("搜索 ID / 名称 / 说明…")
        self._search.textChanged.connect(self._apply_filter)

        fl = QHBoxLayout()
        fl.setSpacing(8)
        self._lbl_tag = QLabel("版本")
        self._lbl_genre = QLabel("流派")
        self._lbl_works = QLabel("作品")
        self._lbl_rare = QLabel("稀有度")
        self._lbl_source = QLabel("数据包")
        fl.addWidget(self._lbl_tag)
        fl.addWidget(self._filter_tag, stretch=1)
        fl.addWidget(self._lbl_genre)
        fl.addWidget(self._filter_genre, stretch=1)
        fl.addWidget(self._lbl_works)
        fl.addWidget(self._filter_works, stretch=1)
        fl.addWidget(self._lbl_rare)
        fl.addWidget(self._filter_rare, stretch=1)
        fl.addWidget(self._lbl_source)
        fl.addWidget(self._filter_source, stretch=1)
        fl.addWidget(self._search, stretch=2)

        filters = meta.get("filters") or ()
        show_tag = "tag" in filters
        show_genre = "genre" in filters
        show_works = "works" in filters
        show_rare = "rare" in filters
        show_source = "source" in filters
        self._lbl_tag.setVisible(show_tag)
        self._filter_tag.setVisible(show_tag)
        self._lbl_genre.setVisible(show_genre)
        self._filter_genre.setVisible(show_genre)
        self._lbl_works.setVisible(show_works)
        self._filter_works.setVisible(show_works)
        self._lbl_rare.setVisible(show_rare)
        self._filter_rare.setVisible(show_rare)
        self._lbl_source.setVisible(show_source)
        self._filter_source.setVisible(show_source)

        cols = self._table_header_labels()
        self._table = QTableWidget(0, len(cols), self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(cols)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        if self._has_default_have_col:
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
            self._table.verticalHeader().setDefaultSectionSize(40)
        else:
            hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.doubleClicked.connect(self._on_double_click)

        refresh = PushButton("从磁盘重新扫描", self)
        refresh.clicked.connect(self._reload_from_disk)
        close = PrimaryPushButton("关闭", self)
        close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addWidget(refresh)
        btns.addStretch(1)
        btns.addWidget(close)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        cly.addWidget(hint)
        cly.addLayout(fl)
        cly.addWidget(self._table, stretch=1)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

        self._filter_tag.currentIndexChanged.connect(self._apply_filter)
        self._filter_genre.currentIndexChanged.connect(self._apply_filter)
        self._filter_works.currentIndexChanged.connect(self._apply_filter)
        self._filter_rare.currentIndexChanged.connect(self._apply_filter)
        self._filter_source.currentIndexChanged.connect(self._apply_filter)

        self._load_rows()
        self._fill_filters()
        self._apply_filter()

    def _table_header_labels(self) -> list[str]:
        cols = list(self._meta["columns"])
        if self._has_default_have_col:
            return ["强制解锁", *cols]
        return cols

    def _catalog_from_index(self) -> list[dict[str, Any]]:
        idx = self._get_index()
        if idx is None:
            return []
        raw = getattr(idx, str(self._meta["catalog_attr"]), None)
        if not isinstance(raw, list):
            return []
        return [dict(r) for r in raw if isinstance(r, dict)]

    def _load_rows(self) -> None:
        rows = self._catalog_from_index()
        if rows:
            self._rows = rows
            return
        try:
            scan_fn = self._meta["scan"]
            self._rows = scan_fn(self._game_root)
        except Exception as e:
            fly_warning(self, "读取失败", str(e))
            self._rows = []

    def _reload_from_disk(self) -> None:
        try:
            scan_fn = self._meta["scan"]
            self._rows = scan_fn(self._game_root)
        except Exception as e:
            fly_critical(self, "扫描失败", str(e))
            return
        self._fill_filters()
        self._apply_filter()

    def _all_genres(self) -> list[str]:
        s: set[str] = set()
        for r in self._rows:
            for g in r.get("genres") or []:
                gg = str(g).strip()
                if gg:
                    s.add(gg)
        return sorted(s)

    def _all_works(self) -> list[str]:
        s: set[str] = set()
        for r in self._rows:
            w = str(r.get("works_str") or "").strip()
            if w:
                s.add(w)
        return sorted(s)

    def _all_rare_types(self) -> list[str]:
        s: set[str] = set()
        for r in self._rows:
            v = r.get("rare_type")
            if v is None:
                continue
            s.add(str(int(v)))
        return sorted(s, key=lambda x: int(x))

    def _all_sources(self) -> list[str]:
        s: set[str] = set()
        for r in self._rows:
            src = str(r.get("source") or "").strip()
            if not src:
                continue
            for part in src.split(";"):
                p = part.strip()
                if p:
                    s.add(p)
        return sorted(s)

    def _fill_filters(self) -> None:
        cur_t = self._filter_tag.currentData()
        cur_g = self._filter_genre.currentData()
        cur_w = self._filter_works.currentData()
        cur_r = self._filter_rare.currentData()
        cur_s = self._filter_source.currentData()
        self._filter_tag.blockSignals(True)
        self._filter_genre.blockSignals(True)
        self._filter_works.blockSignals(True)
        self._filter_rare.blockSignals(True)
        self._filter_source.blockSignals(True)
        self._filter_tag.clear()
        self._filter_genre.clear()
        self._filter_works.clear()
        self._filter_rare.clear()
        self._filter_source.clear()
        self._filter_tag.addItem("全部版本", None, None)
        for rid, label in iter_release_tag_filter_options(self._rows):
            self._filter_tag.addItem(label, None, rid)
        self._filter_genre.addItem("全部流派", None, "")
        for g in self._all_genres():
            self._filter_genre.addItem(g, None, g)
        self._filter_works.addItem("全部作品", None, "")
        for w in self._all_works():
            self._filter_works.addItem(w, None, w)
        self._filter_rare.addItem("全部稀有度", None, "")
        for rv in self._all_rare_types():
            self._filter_rare.addItem(rv, None, rv)
        self._filter_source.addItem("全部数据包", None, "")
        for s in self._all_sources():
            self._filter_source.addItem(s, None, s)
        self._restore_combo(self._filter_tag, cur_t)
        self._restore_combo(self._filter_genre, cur_g)
        self._restore_combo(self._filter_works, cur_w)
        self._restore_combo(self._filter_rare, cur_r)
        self._restore_combo(self._filter_source, cur_s)
        self._filter_tag.blockSignals(False)
        self._filter_genre.blockSignals(False)
        self._filter_works.blockSignals(False)
        self._filter_rare.blockSignals(False)
        self._filter_source.blockSignals(False)

    @staticmethod
    def _restore_combo(cb: FluentComboBox, data) -> None:
        if data is None:
            cb.setCurrentIndex(0)
            return
        for i in range(cb.count()):
            if cb.itemData(i) == data:
                cb.setCurrentIndex(i)
                return
        cb.setCurrentIndex(0)

    @staticmethod
    def _row_default_have(r: dict[str, Any]) -> bool:
        v = r.get("default_have")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() == "true"
        return False

    def _commit_default_have(self, row_data: dict[str, Any], want: bool) -> bool:
        if self._row_default_have(row_data) == want:
            return True
        xml_path = resolve_catalog_xml_path(game_root=self._game_root, row=row_data)
        if xml_path is None:
            fly_warning(self, "无法写回", "未找到该条目对应的 XML 文件。")
            return False
        try:
            set_default_have_in_xml(xml_path, default_have=want)
        except OSError as e:
            fly_critical(self, "写入失败", str(e))
            return False
        row_data["default_have"] = want
        try:
            patch_catalog_default_have(
                self._get_index(),
                catalog_attr=str(self._meta["catalog_attr"]),
                row_id=int(row_data["id"]),
                default_have=want,
            )
        except (TypeError, ValueError, KeyError):
            pass
        return True

    def _row_values(self, r: dict[str, Any]) -> list[str]:
        if self._kind == "music":
            genres = "、".join(str(x) for x in (r.get("genres") or []))
            return [
                str(r.get("id", "")),
                str(r.get("title", "")),
                str(r.get("artist", "")),
                genres,
                str(r.get("release_date", "")),
                format_release_tag_version(r),
                str(r.get("source", "")),
            ]
        if self._kind == "chara":
            return [
                str(r.get("id", "")),
                str(r.get("name", "")),
                str(r.get("works_str", "")),
                format_release_tag_version(r),
                str(r.get("default_image_key", "")),
                str(r.get("source", "")),
            ]
        if self._kind == "nameplate":
            return [
                str(r.get("id", "")),
                str(r.get("name", "")),
                format_release_tag_version(r),
                str(r.get("source", "")),
            ]
        return [
            str(r.get("id", "")),
            str(r.get("name", "")),
            "" if r.get("rare_type") is None else str(r.get("rare_type")),
            str(r.get("explain", "")),
            str(r.get("source", "")),
        ]

    def _apply_filter(self) -> None:
        tag_id_f = self._filter_tag.currentData()
        gen_f = str(self._filter_genre.currentData() or "").strip()
        works_f = str(self._filter_works.currentData() or "").strip()
        rare_f = str(self._filter_rare.currentData() or "").strip()
        src_f = str(self._filter_source.currentData() or "").strip()
        needle = self._search.text().strip().lower()

        def ok(r: dict[str, Any]) -> bool:
            if tag_id_f is not None:
                rid = catalog_release_tag_id(r)
                if rid is None or rid != int(tag_id_f):
                    return False
            if gen_f:
                genres = [str(x).strip() for x in (r.get("genres") or [])]
                if gen_f not in genres:
                    return False
            if works_f and str(r.get("works_str") or "").strip() != works_f:
                return False
            if rare_f:
                rv = r.get("rare_type")
                if rv is None or str(int(rv)) != rare_f:
                    return False
            if src_f:
                blob = str(r.get("source") or "")
                if src_f not in blob:
                    return False
            if not needle:
                return True
            parts = [str(v) for v in r.values()]
            return needle in " ".join(parts).lower()

        filtered = [r for r in self._rows if ok(r)]
        self._populating_table = True
        self._table.setRowCount(len(filtered))
        for row_i, r in enumerate(filtered):
            col_offset = 0
            if self._has_default_have_col:
                set_default_have_cell(
                    self._table,
                    row_i,
                    row_data=r,
                    checked=self._row_default_have(r),
                    on_commit=self._commit_default_have,
                )
                col_offset = 1
            vals = self._row_values(r)
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col == 0:
                    it.setData(Qt.ItemDataRole.UserRole, r)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row_i, col + col_offset, it)
        self._populating_table = False
        self._table.resizeColumnsToContents()

    def _selected_row(self) -> dict[str, Any] | None:
        r = self._table.currentRow()
        if r < 0:
            return None
        data_col = 1 if self._has_default_have_col else 0
        it = self._table.item(r, data_col)
        if it is None:
            return None
        data = it.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _on_double_click(self, _index) -> None:
        row = self._selected_row()
        if row is None:
            return
        if self._kind == "music":
            GameMusicDetailDialog(
                row=row,
                game_root=self._game_root,
                acus_root=self._acus_root,
                get_tool_path=self._get_tool_path,
                parent=self,
            ).exec()
            return
        if self._kind == "chara":
            open_chara_image_dialog(
                row=row,
                game_root=self._game_root,
                acus_root=self._acus_root,
                get_tool_path=self._get_tool_path,
                parent=self,
            )
            return
        if self._kind == "nameplate":
            open_row_image_dialog(
                row=row,
                game_root=self._game_root,
                acus_root=self._acus_root,
                get_tool_path=self._get_tool_path,
                kind_label="名牌",
                parent=self,
            )
            return
        open_row_image_dialog(
            row=row,
            game_root=self._game_root,
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path,
            kind_label="称号",
            parent=self,
        )
