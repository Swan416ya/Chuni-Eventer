"""Fluent QTableWidget：在 TABLE_VIEW 基础上修正选中行前景/背景对比度。"""

from __future__ import annotations

from PyQt6.QtWidgets import QTableWidget

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
