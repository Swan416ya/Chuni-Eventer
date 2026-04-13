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

from ..game_data_index import GameDataIndex, scan_game_music_catalog
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_table import apply_fluent_sheet_table
from .fluent_dialogs import fly_critical, fly_warning


class GameMusicBrowserDialog(FluentCaptionDialog):
    """只读：浏览游戏数据包内扫描到的全部乐曲（含版本标签、流派）。"""

    def __init__(
        self,
        *,
        game_root: Path,
        get_index,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("游戏乐曲资源（只读）")
        self.setModal(True)
        self.resize(1000, 580)
        self._game_root = game_root.expanduser().resolve()
        self._get_index = get_index
        self._rows: list[dict] = []

        hint = BodyLabel(
            "数据来自游戏目录下所有已扫描数据包（如 data/a000/opt/*、bin/option/A*）。"
            "若列表为空或不全，请在【设置】中配置游戏根目录并点击「重新扫描游戏索引」。",
            self,
        )
        hint.setWordWrap(True)

        self._filter_tag = FluentComboBox(self)
        self._filter_tag.addItem("全部版本", None, "")
        self._filter_genre = FluentComboBox(self)
        self._filter_genre.addItem("全部流派", None, "")
        self._search = LineEdit(self)
        self._search.setPlaceholderText("筛选：ID / 曲名 / 艺术家 / 来源路径…")
        self._search.textChanged.connect(self._apply_filter)

        fl = QHBoxLayout()
        fl.setSpacing(8)
        fl.addWidget(QLabel("版本(releaseTag)"))
        fl.addWidget(self._filter_tag, stretch=1)
        fl.addWidget(QLabel("流派"))
        fl.addWidget(self._filter_genre, stretch=1)
        fl.addWidget(self._search, stretch=2)

        self._table = QTableWidget(0, 8, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(
            [
                "ID",
                "曲名",
                "艺术家",
                "流派",
                "发布日",
                "版本标签",
                "数据包",
                "releaseTag.id",
            ]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setColumnHidden(7, True)

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

    def _all_tags(self) -> list[str]:
        s: set[str] = set()
        for r in self._rows:
            t = (r.get("release_tag_str") or "").strip()
            if t:
                s.add(t)
        return sorted(s)

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
        self._filter_tag.addItem("全部版本", None, "")
        for t in self._all_tags():
            self._filter_tag.addItem(t, None, t)
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

    def _apply_filter(self) -> None:
        tag_f = (self._filter_tag.currentData() or "").strip()
        gen_f = (self._filter_genre.currentData() or "").strip()
        needle = self._search.text().strip().lower()

        def ok(r: dict) -> bool:
            if tag_f:
                if (r.get("release_tag_str") or "").strip() != tag_f:
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
        self._table.setRowCount(len(filtered))
        for row, r in enumerate(filtered):
            genres = "、".join(str(x) for x in (r.get("genres") or []))
            rt_id = r.get("release_tag_id")
            rt_id_s = "" if rt_id is None else str(rt_id)
            vals = [
                str(r.get("id", "")),
                str(r.get("title", "")),
                str(r.get("artist", "")),
                genres,
                str(r.get("release_date", "")),
                str(r.get("release_tag_str", "")),
                str(r.get("source", "")),
                rt_id_s,
            ]
            for col, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(row, col, it)
        self._table.resizeColumnsToContents()
