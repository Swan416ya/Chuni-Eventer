"""说明文字的统一出口。

约定（见 ``docs/界面与工作区/ui_style_inventory_zh.md``）：
- 正文只留「这页干什么 + 一条关键约束」，一行说清；
- 像素坐标、XML 字段名、内部处理步骤这类细则一律收进 ⓘ 弹窗，不占正文。
"""

from __future__ import annotations

import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

from qfluentwidgets import FluentIcon, TransparentToolButton, isDarkTheme

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")


def _code_span_style() -> str:
    if isDarkTheme():
        return (
            "font-family:Consolas,'Courier New',monospace;"
            "background:#374151;color:#E5E7EB;padding:0 4px;border-radius:3px;"
        )
    return (
        "font-family:Consolas,'Courier New',monospace;"
        "background:#E5E7EB;color:#1F2937;padding:0 4px;border-radius:3px;"
    )


def markdown_to_rich_html(text: str) -> str:
    """支持 ``**bold**`` 与 `` `code` ``；换行转为 ``<br/>``。"""
    s = html.escape(text, quote=False)
    s = _BOLD_RE.sub(r"<b>\1</b>", s)
    style = _code_span_style()
    s = _CODE_RE.sub(rf'<span style="{style}">\1</span>', s)
    return s.replace("\n", "<br/>")


def rich_hint_label(
    text: str,
    parent: QWidget | None = None,
    *,
    color: str | None = None,
    font_size_pt: int = 13,
) -> QLabel:
    lbl = QLabel(parent)
    lbl.setWordWrap(True)
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setText(markdown_to_rich_html(text))
    if color is None:
        color = "#9CA3AF" if isDarkTheme() else "#4B5563"
    lbl.setStyleSheet(f"color:{color};font-size:{font_size_pt}px;")
    lbl.setOpenExternalLinks(False)
    return lbl


def hint_row(
    text: str,
    details: str | None = None,
    parent: QWidget | None = None,
    *,
    color: str | None = None,
    font_size_pt: int = 12,
    details_title: str = "说明",
) -> QWidget:
    """一行说明（可选尾部 ⓘ）：细则点开弹窗看，不铺在正文里。"""
    row = QWidget(parent)
    # 只占一行高度：外层 VBox 有富余空间时不要把它拉高（否则 ⓘ 会飘到行外）
    row.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)

    lbl = rich_hint_label(text, row, color=color, font_size_pt=font_size_pt)
    # wordWrap 下 QLabel 的 sizeHint 会按窄宽度估成多行，外层 VBox 因此留出空白；
    # 说明行按「最多两行」定高，正文规范也要求控制在一行内。
    lbl.setMaximumHeight(40)
    lay.addWidget(lbl, stretch=1, alignment=Qt.AlignmentFlag.AlignTop)
    if not details:
        return row

    btn = TransparentToolButton(FluentIcon.INFO, row)
    btn.setFixedSize(22, 22)
    btn.setToolTip(f"查看{details_title}")

    def _show_details() -> None:
        # 局部 import：fluent_dialogs 依赖较多，避免模块级循环引用
        from .fluent_dialogs import fly_message

        fly_message(btn.window(), details_title, details)

    btn.clicked.connect(_show_details)
    lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignTop)
    return row
