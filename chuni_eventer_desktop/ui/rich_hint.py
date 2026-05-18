"""将少量 Markdown（**粗体**、``行内代码``）转为 QLabel 可用的 RichText HTML。"""

from __future__ import annotations

import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from qfluentwidgets import isDarkTheme

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
