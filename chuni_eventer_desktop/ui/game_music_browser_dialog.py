from __future__ import annotations

from pathlib import Path

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
    scan_game_music_catalog,
)
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_table import apply_fluent_sheet_table, set_default_have_cell
from .fluent_dialogs import fly_critical, fly_warning


class GameMusicBrowserDialog(FluentCaptionDialog):
    """浏览游戏数据包内扫描到的全部乐曲（含版本标签、流派）。"""

    def __init__(
        self,
        *,
        game_root: Path,
        get_index,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("游戏乐曲资源")
        self.setModal(True)
        self.resize(1000, 580)
        self._game_root = game_root.expanduser().resolve()
        self._get_index = get_index
        self._rows: list[dict] = []
        self._populating_table = False

        hint = BodyLabel(
            "数据来自游戏目录下所有已扫描数据包（如 data/a000/opt/*、bin/option/A*）。"
            "若列表为空或不全，请在【设置】中配置游戏根目录并点击「重新扫描游戏索引」。"
            "勾选「强制解锁」会写回 Music.xml 的 defaultHave。",
            self,
        )
        hint.setWordWrap(True)

        self._filter_tag = FluentComboBox(self)
        self._filter_tag.addItem("全部版本", None, None)
        self._filter_genre = FluentComboBox(self)
        self._filter_genre.addItem("全部流派", None, "")
        self._search = LineEdit(self)
        self._search.setPlaceholderText("筛选：ID / 曲名 / 艺术家 / 来源路径…")
        self._search.textChanged.connect(self._apply_filter)

        fl = QHBoxLayout()
        fl.setSpacing(8)
        fl.addWidget(QLabel("版本 ID"))
        fl.addWidget(self._filter_tag, stretch=1)
        fl.addWidget(QLabel("流派"))
        fl.addWidget(self._filter_genre, stretch=1)
        fl.addWidget(self._search, stretch=2)

        self._table = QTableWidget(0, 8, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(
            [
                "强制解锁",
                "ID",
                "曲名",
                "艺术家",
                "流派",
                "发布日",
                "版本",
                "数据包",
            ]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.verticalHeader().setDefaultSectionSize(40)

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

        self._load_rows()
        self._fill_filters()
        self._apply_filter()

    def _load_rows(self) -> None:
        idx: GameDataIndex | None = self._get_index()
        if idx is not None and idx.music_catalog:
            self._rows = [dict(r) for r in idx.music_catalog]
            return
        try:
            self._rows = scan_game_music_catalog(self._game_root)
        except Exception as e:
            fly_warning(self, "读取失败", str(e))
            self._rows = []

    def _reload_from_disk(self) -> None:
        try:
            self._rows = scan_game_music_catalog(self._game_root)
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

    def _fill_filters(self) -> None:
        cur_t = self._filter_tag.currentData()
        cur_g = self._filter_genre.currentData()
        self._filter_tag.blockSignals(True)
        self._filter_genre.blockSignals(True)
        self._filter_tag.clear()
        self._filter_genre.clear()
        self._filter_tag.addItem("全部版本", None, None)
        for rid, label in iter_release_tag_filter_options(self._rows):
            self._filter_tag.addItem(label, None, rid)
        self._filter_genre.addItem("全部流派", None, "")
        for g in self._all_genres():
            self._filter_genre.addItem(g, None, g)
        self._restore_combo(self._filter_tag, cur_t)
        self._restore_combo(self._filter_genre, cur_g)
        self._filter_tag.blockSignals(False)
        self._filter_genre.blockSignals(False)

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
    def _row_default_have(r: dict) -> bool:
        v = r.get("default_have")
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() == "true"
        return False

    def _commit_default_have(self, row_data: dict, want: bool) -> bool:
        if self._row_default_have(row_data) == want:
            return True
        xml_path = resolve_catalog_xml_path(game_root=self._game_root, row=row_data)
        if xml_path is None:
            fly_warning(self, "无法写回", "未找到该条目对应的 Music.xml。")
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
                catalog_attr="music_catalog",
                row_id=int(row_data["id"]),
                default_have=want,
            )
        except (TypeError, ValueError, KeyError):
            pass
        return True

    def _apply_filter(self) -> None:
        tag_id_f = self._filter_tag.currentData()
        gen_f = (self._filter_genre.currentData() or "").strip()
        needle = self._search.text().strip().lower()

        def ok(r: dict) -> bool:
            if tag_id_f is not None:
                rid = catalog_release_tag_id(r)
                if rid is None or rid != int(tag_id_f):
                    return False
            if gen_f:
                genres = [str(x).strip() for x in (r.get("genres") or [])]
                if gen_f not in genres:
                    return False
            if not needle:
                return True
            parts = [
                str(r.get("id", "")),
                str(r.get("title", "")),
                str(r.get("artist", "")),
                str(r.get("release_date", "")),
                str(r.get("release_tag_str", "")),
                str(r.get("source", "")),
                " ".join(str(x) for x in (r.get("genres") or [])),
            ]
            return needle in " ".join(parts).lower()

        filtered = [r for r in self._rows if ok(r)]
        self._populating_table = True
        self._table.setRowCount(len(filtered))
        for row, r in enumerate(filtered):
            set_default_have_cell(
                self._table,
                row,
                row_data=r,
                checked=self._row_default_have(r),
                on_commit=self._commit_default_have,
            )
            genres = "、".join(str(x) for x in (r.get("genres") or []))
            vals = [
                str(r.get("id", "")),
                str(r.get("title", "")),
                str(r.get("artist", "")),
                genres,
                str(r.get("release_date", "")),
                format_release_tag_version(r),
                str(r.get("source", "")),
            ]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col == 0:
                    it.setData(Qt.ItemDataRole.UserRole, r)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col + 1, it)
        self._populating_table = False
        self._table.resizeColumnsToContents()
