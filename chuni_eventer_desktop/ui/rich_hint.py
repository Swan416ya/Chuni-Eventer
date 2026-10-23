"""说明文字的统一出口。

约定（见 ``docs/界面与工作区/ui_style_inventory_zh.md``）：
- 正文只留「这页干什么 + 一条关键约束」，一行说清；
- 像素坐标、XML 字段名、内部处理步骤这类细则一律收进 ⓘ 弹窗，不占正文。
"""

from __future__ import annotations

import html
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    FluentIcon,
    PrimaryPushButton,
    TransparentToolButton,
    isDarkTheme,
)

from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins

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


class DetailDialog(FluentCaptionDialog):
    """细则弹窗：正文按窗口宽度换行、超长可滚动。

    不用 ``fly_message`` 承载长细则：原生 QMessageBox 的正文标签不换行，
    上百字的说明会被裁成一行（实测 width≈300、sizeHint≈2360，右侧看不见）。
    """

    def __init__(self, *, text: str, title: str = "说明", parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(560, 420)

        body = QWidget(self)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(16, 8, 16, 8)
        body_lay.setSpacing(8)
        body_lay.addWidget(rich_hint_label(text, body, font_size_pt=13))
        body_lay.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(body)

        ok = PrimaryPushButton("知道了", self)
        ok.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        foot.addWidget(ok)

        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(10)
        root.addWidget(scroll, stretch=1)
        root.addLayout(foot)


def show_detail_dialog(parent: QWidget | None, text: str, title: str = "说明") -> None:
    dlg = DetailDialog(text=text, title=title, parent=parent)
    dlg.setWindowModality(Qt.WindowModality.WindowModal)
    # open() 而不是 exec()：细则弹窗常在已有模态弹窗里打开，避免嵌套事件循环
    dlg.open()


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
    btn.clicked.connect(lambda: show_detail_dialog(btn.window(), details, details_title))
    lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignTop)
    return row
