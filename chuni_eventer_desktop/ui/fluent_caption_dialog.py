"""无边框弹窗：Fluent 标题栏（左标题、右最小化 / 关闭），与主窗口风格一致。"""

from __future__ import annotations

import ctypes

from PyQt6.QtCore import Qt

from qframelesswindow import FramelessDialog
from qfluentwidgets.window import FluentTitleBar

# 与 qfluentwidgets.window.fluent_window.FluentTitleBar.setFixedHeight(48) 一致
FLUENT_CAPTION_BAR_HEIGHT = 48


def _force_remove_win32_caption(hwnd: int) -> None:
    """Win32 workaround：强制清除 WS_CAPTION 样式，避免 DWM 残留系统标题栏。

    在某些 Windows 11 机器上（尤其广电网络环境），即使 Qt windowFlags 包含
    FramelessWindowHint，DWM 仍会叠加一层系统标题栏，造成"双层标题栏"。
    通过 SetWindowLongW 移除 WS_CAPTION 并触发 FRAMECHANGED 可彻底解决。
    """
    try:
        user32 = ctypes.windll.user32
        GWL_STYLE = -16
        WS_CAPTION = 0x00C00000
        style = user32.GetWindowLongW(hwnd, GWL_STYLE)
        style = style & ~WS_CAPTION
        user32.SetWindowLongW(hwnd, GWL_STYLE, style)
        # 强制重绘让样式变更生效
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_FRAMECHANGED = 0x0020
        SWP_NOZORDER = 0x0004
        user32.SetWindowPos(
            hwnd,
            0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_NOZORDER,
        )
    except Exception:
        # Win32 API 不可用时静默忽略（不影响跨平台）
        pass


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
        # 强制移除 Win32 系统标题栏（Windows 11 DWM 残留 workaround）
        _force_remove_win32_caption(int(self.winId()))


def fluent_caption_content_margins(
    *,
    left: int = 12,
    below_caption: int = 12,
    right: int = 12,
    bottom: int = 12,
) -> tuple[int, int, int, int]:
    """主布局 contentsMargins：为顶部标题栏留出空间。"""
    return (left, FLUENT_CAPTION_BAR_HEIGHT + below_caption, right, bottom)
