from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

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

from ..game_data_index import (
    GameDataIndex,
    catalog_release_tag_id,
    format_release_tag_version,
    iter_release_tag_filter_options,
    merged_music_catalog,
    scan_game_music_catalog,
)
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_warning
from .fluent_table import apply_fluent_sheet_table


def _music_row_search_blob(r: dict[str, Any]) -> str:
    parts = [
        str(r.get("id", "")),
        str(r.get("title", "")),
        str(r.get("artist", "")),
        str(r.get("release_date", "")),
        str(r.get("release_tag_str", "")),
        str(r.get("source", "")),
        " ".join(str(x) for x in (r.get("genres") or [])),
    ]
    return " ".join(parts).lower()


def _filter_music_rows(
    rows: list[dict[str, Any]],
    *,
    tag_id_f: int | None,
    genre_f: str,
    needle: str,
) -> list[dict[str, Any]]:
    gen_f = genre_f.strip()
    needle_l = needle.strip().lower()

    def ok(r: dict[str, Any]) -> bool:
        if tag_id_f is not None:
            rid = catalog_release_tag_id(r)
            if rid is None or rid != int(tag_id_f):
                return False
        if gen_f:
            genres = [str(x).strip() for x in (r.get("genres") or [])]
            if gen_f not in genres:
                return False
        if not needle_l:
            return True
        return needle_l in _music_row_search_blob(r)

    return [r for r in rows if ok(r)]


def _all_music_genres(rows: list[dict[str, Any]]) -> list[str]:
    s: set[str] = set()
    for r in rows:
        for g in r.get("genres") or []:
            gg = str(g).strip()
            if gg:
                s.add(gg)
    return sorted(s)


def _restore_combo(cb: FluentComboBox, data) -> None:
    if data is None:
        cb.setCurrentIndex(0)
        return
    for i in range(cb.count()):
        if cb.itemData(i) == data:
            cb.setCurrentIndex(i)
            return
    cb.setCurrentIndex(0)


class MusicPickerDialog(FluentCaptionDialog):
    """乐曲选择弹窗：版本/流派筛选 + 搜索，双击或「确定」回填。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        game_root: str | Path = "",
        get_index: Callable[[], GameDataIndex | None],
        preselect_id: int | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("选择乐曲")
        self.setModal(True)
        self.resize(960, 560)
        self._acus_root = acus_root
        self._game_root_raw = str(game_root or "").strip()
        self._get_index = get_index
        self._rows: list[dict[str, Any]] = []
        self._selected: tuple[int, str] | None = None
        self._preselect_id = preselect_id

        hint = BodyLabel(
            "可按版本 ID、流派筛选，并搜索 ID / 曲名 / 艺术家 / 数据包。"
            "双击一行选中并关闭；或选中后点「确定」。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6B7280;")

        self._filter_tag = FluentComboBox(self)
        self._filter_tag.addItem("全部版本", None, None)
        self._filter_genre = FluentComboBox(self)
        self._filter_genre.addItem("全部流派", None, "")
        self._search = LineEdit(self)
        self._search.setPlaceholderText("搜索 ID / 曲名 / 艺术家 / 流派 / 数据包…")
        self._search.textChanged.connect(self._apply_filter)

        fl = QHBoxLayout()
        fl.setSpacing(8)
        fl.addWidget(QLabel("版本"))
        fl.addWidget(self._filter_tag, stretch=1)
        fl.addWidget(QLabel("流派"))
        fl.addWidget(self._filter_genre, stretch=1)
        fl.addWidget(self._search, stretch=2)

        self._table = QTableWidget(0, 7, self)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(
            ["ID", "曲名", "艺术家", "流派", "发布日", "版本", "数据包"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.doubleClicked.connect(self._on_double_click)

        refresh = PushButton("从磁盘重新扫描", self)
        refresh.clicked.connect(self._reload_from_disk)
        ok = PrimaryPushButton("确定", self)
        ok.clicked.connect(self._confirm_selection)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addWidget(refresh)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

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

    @property
    def selected(self) -> tuple[int, str] | None:
        return self._selected

    def _load_rows(self) -> None:
        gr = self._game_root_raw or None
        game_path = Path(gr).expanduser() if gr else None
        self._rows = merged_music_catalog(
            self._acus_root,
            self._get_index(),
            game_root=game_path,
        )
        if not self._rows and game_path is not None:
            try:
                self._rows = scan_game_music_catalog(game_path)
            except Exception as e:
                fly_warning(self, "读取失败", str(e))
                self._rows = []

    def _reload_from_disk(self) -> None:
        gr = self._game_root_raw
        if not gr:
            fly_warning(self, "提示", "未配置游戏数据目录，仅刷新 ACUS 内乐曲。")
        self._load_rows()
        self._fill_filters()
        self._apply_filter()

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
        for g in _all_music_genres(self._rows):
            self._filter_genre.addItem(g, None, g)
        _restore_combo(self._filter_tag, cur_t)
        _restore_combo(self._filter_genre, cur_g)
        self._filter_tag.blockSignals(False)
        self._filter_genre.blockSignals(False)

    def _apply_filter(self) -> None:
        tag_id_f = self._filter_tag.currentData()
        gen_f = str(self._filter_genre.currentData() or "")
        filtered = _filter_music_rows(
            self._rows,
            tag_id_f=tag_id_f,
            genre_f=gen_f,
            needle=self._search.text(),
        )
        self._table.setRowCount(len(filtered))
        select_row = -1
        for row_i, r in enumerate(filtered):
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
                self._table.setItem(row_i, col, it)
            if self._preselect_id is not None and int(r.get("id", -1)) == int(self._preselect_id):
                select_row = row_i
        if select_row >= 0:
            self._table.selectRow(select_row)
            self._table.scrollToItem(self._table.item(select_row, 0))
        self._table.resizeColumnsToContents()

    def _row_at(self, row: int) -> dict[str, Any] | None:
        if row < 0:
            return None
        it = self._table.item(row, 0)
        if it is None:
            return None
        data = it.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _accept_row(self, row: dict[str, Any]) -> None:
        try:
            mid = int(row["id"])
        except (KeyError, TypeError, ValueError):
            return
        title = str(row.get("title") or "").strip() or f"Music{mid}"
        self._selected = (mid, title)
        self.accept()

    def _on_double_click(self, index) -> None:
        row = self._row_at(index.row())
        if row is not None:
            self._accept_row(row)

    def _confirm_selection(self) -> None:
        row = self._row_at(self._table.currentRow())
        if row is None:
            fly_warning(self, "提示", "请先选择一首乐曲。")
            return
        self._accept_row(row)


def pick_music(
    *,
    parent,
    acus_root: Path,
    game_root: str = "",
    get_index: Callable[[], GameDataIndex | None],
    preselect_id: int | None = None,
) -> tuple[int, str] | None:
    dlg = MusicPickerDialog(
        acus_root=acus_root,
        game_root=game_root,
        get_index=get_index,
        preselect_id=preselect_id,
        parent=parent,
    )
    if dlg.exec() != dlg.DialogCode.Accepted:
        return None
    return dlg.selected
