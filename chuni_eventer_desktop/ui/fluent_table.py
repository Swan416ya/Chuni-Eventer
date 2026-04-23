"""Fluent QTableWidget：统一为主页管理资源表格风格。"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QTableWidget, QTableWidgetItem, QVBoxLayout

from qfluentwidgets import FluentStyleSheet, setCustomStyleSheet

# 显式覆盖选中态，避免默认 QSS 在浅色卡片上出现「白字 + 浅底」导致看不见
_LIGHT_SELECTION_QSS = """
QTableWidget#FluentSheetTable::item:selected,
QTableWidget#FluentSheetTable::item:selected:active,
QTableWidget#FluentSheetTable::item:selected:!active {
    background-color: #B8D9F0;
    color: #1A1A1A;
}
"""

_DARK_SELECTION_QSS = """
QTableWidget#FluentSheetTable::item:selected,
QTableWidget#FluentSheetTable::item:selected:active,
QTableWidget#FluentSheetTable::item:selected:!active {
    background-color: #505050;
    color: #FFFFFF;
}
"""


def apply_fluent_sheet_table(table: QTableWidget) -> None:
    table.setObjectName("FluentSheetTable")
    FluentStyleSheet.TABLE_VIEW.apply(table)
    setCustomStyleSheet(table, _LIGHT_SELECTION_QSS, _DARK_SELECTION_QSS)
    # Align with manager_widget TableView visual style.
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)


def sheet_list_card_layout_margins(layout: QVBoxLayout) -> None:
    """与 `MusicReleaseTagDialog` 列表卡一致：内边距与间距。"""
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)


def sheet_list_hint_muted_colors(widget: object) -> None:
    """与 `MusicReleaseTagDialog` 顶部说明一致（BodyLabel 等支持 setTextColor 的控件）。"""
    fn = getattr(widget, "setTextColor", None)
    if callable(fn):
        fn("#6B7280", "#9CA3AF")


def mark_sheet_item_readonly(item: QTableWidgetItem) -> None:
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
