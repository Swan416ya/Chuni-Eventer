"""Fluent QTableWidget：统一为主页管理资源表格风格。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import CheckBox, FluentStyleSheet, setCustomStyleSheet

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


class DefaultHaveTableCell(QWidget):
    """表格「强制解锁」列：居中 qfluentwidgets CheckBox（Fluent 表样式下 QTableWidgetItem 勾选框不可见）。"""

    def __init__(
        self,
        *,
        row_data: dict[str, Any],
        checked: bool,
        on_commit: Callable[[dict[str, Any], bool], bool],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.row_data = row_data
        self._on_commit = on_commit
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cb = CheckBox(self)
        self._cb.blockSignals(True)
        self._cb.setChecked(checked)
        self._cb.blockSignals(False)
        self._cb.stateChanged.connect(self._on_state_changed)
        lay.addWidget(self._cb)

    def set_checked(self, checked: bool) -> None:
        self._cb.blockSignals(True)
        self._cb.setChecked(checked)
        self._cb.blockSignals(False)

    def _on_state_changed(self, _state: int) -> None:
        want = self._cb.isChecked()
        if not self._on_commit(self.row_data, want):
            self.set_checked(not want)


def set_default_have_cell(
    table: QTableWidget,
    row: int,
    *,
    row_data: dict[str, Any],
    checked: bool,
    on_commit: Callable[[dict[str, Any], bool], bool],
) -> DefaultHaveTableCell:
    cell = DefaultHaveTableCell(row_data=row_data, checked=checked, on_commit=on_commit, parent=table)
    table.setCellWidget(row, 0, cell)
    return cell


def apply_fluent_tableview_header_style(table: QWidget, *, object_name: str) -> None:
    """
    qfluentwidgets TableView 默认表头为整条直角灰底；与数据区圆角块协调：
    透明表头容器、分段圆角 section、文字水平垂直居中。
    """
    name = (object_name or "FluentTableHdr").strip() or "FluentTableHdr"
    table.setObjectName(name)
    hh_fn = getattr(table, "horizontalHeader", None)
    if not callable(hh_fn):
        return
    hh = hh_fn()
    hh.setDefaultAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
    _light = f"""
#{name} QHeaderView {{
    background-color: transparent;
}}
#{name} QHeaderView::section {{
    background-color: rgba(0, 0, 0, 0.06);
    color: #374151;
    font-weight: 500;
    padding: 8px 8px;
    border: none;
    border-radius: 6px;
    margin: 4px 3px;
}}
"""
    _dark = f"""
#{name} QHeaderView {{
    background-color: transparent;
}}
#{name} QHeaderView::section {{
    background-color: rgba(255, 255, 255, 0.08);
    color: #e5e7eb;
    font-weight: 500;
    padding: 8px 8px;
    border: none;
    border-radius: 6px;
    margin: 4px 3px;
}}
"""
    setCustomStyleSheet(table, _light, _dark)
