"""无边框弹窗：Fluent 标题栏（左标题、右最小化 / 关闭），与主窗口风格一致。"""

from __future__ import annotations

from PyQt6.QtCore import Qt

from qframelesswindow import FramelessDialog
from qfluentwidgets.window import FluentTitleBar

# 与 qfluentwidgets.window.fluent_window.FluentTitleBar.setFixedHeight(48) 一致
FLUENT_CAPTION_BAR_HEIGHT = 48


def fluent_caption_content_margins(
    *,
    left: int = 12,
    below_caption: int = 12,
    right: int = 12,
    bottom: int = 12,
) -> tuple[int, int, int, int]:
    """主布局 contentsMargins：为顶部标题栏留出空间。"""
    return (left, FLUENT_CAPTION_BAR_HEIGHT + below_caption, right, bottom)


class FluentCaptionDialog(FramelessDialog):
    """
    无系统标题栏；使用 FluentTitleBar（可拖动），隐藏最大化按钮。
    内容区请在布局上调用 setContentsMargins(*fluent_caption_content_margins(...))。
    """

    def __init__(self, *, parent=None) -> None:
        super().__init__(parent=parent)
        # After exec() returns, Qt hides the dialog but may keep a hidden modal window
        # around; that breaks later in-window MessageBox input on Windows. Destroy on close.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setTitleBar(FluentTitleBar(self))
        self.titleBar.maxBtn.hide()
        self.titleBar.minBtn.show()
        self.titleBar.setDoubleClickEnabled(False)
