"""应用级调色板：让原生 Qt 控件跟随 qfluentwidgets 的明暗主题。

qfluentwidgets 的 ``setTheme()`` 只会重新应用它自己注册的 QSS（各 Fluent 控件
皮肤），不会修改 ``QApplication`` 的 palette。于是原生 Qt 部件——QDialog、
QLabel、QPlainTextEdit、QTableWidget 表头等——始终使用系统浅色调色板。
在深色主题下这些弹窗表现为「浅灰底 + 浅色文字」，看起来就是没适配黑暗模式。

本模块在启动时按当前主题安装整套 palette，并挂到
``qconfig.themeChangedFinished`` 上，主题一换就同步调色板。
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from qfluentwidgets import isDarkTheme
from qfluentwidgets.common.config import qconfig

# 深色调色板：与 qfluentwidgets 深色 QSS 的窗口/卡片底色保持一致
_DARK_WINDOW = QColor(32, 32, 32)  # #202020
_DARK_BASE = QColor(39, 39, 42)  # #27272A
_DARK_ALTERNATE_BASE = QColor(45, 45, 48)  # #2D2D30
_DARK_BUTTON = QColor(45, 45, 48)
_DARK_TEXT = QColor(228, 228, 231)  # #E4E4E7
_DARK_DISABLED_TEXT = QColor(120, 120, 124)
_DARK_ACCENT = QColor(0, 159, 170)  # 与 Fluent 主题色一致
_DARK_LINK = QColor(100, 181, 246)

_installed = False


def _dark_palette() -> QPalette:
    p = QPalette()
    role = QPalette.ColorRole
    group = QPalette.ColorGroup

    p.setColor(role.Window, _DARK_WINDOW)
    p.setColor(role.WindowText, _DARK_TEXT)
    p.setColor(role.Base, _DARK_BASE)
    p.setColor(role.AlternateBase, _DARK_ALTERNATE_BASE)
    p.setColor(role.ToolTipBase, _DARK_BASE)
    p.setColor(role.ToolTipText, _DARK_TEXT)
    p.setColor(role.Text, _DARK_TEXT)
    p.setColor(role.PlaceholderText, QColor(160, 160, 165))
    p.setColor(role.Button, _DARK_BUTTON)
    p.setColor(role.ButtonText, _DARK_TEXT)
    p.setColor(role.BrightText, QColor(255, 80, 80))
    p.setColor(role.Light, QColor(60, 60, 64))
    p.setColor(role.Midlight, QColor(52, 52, 56))
    p.setColor(role.Mid, QColor(70, 70, 74))
    p.setColor(role.Dark, QColor(20, 20, 20))
    p.setColor(role.Shadow, QColor(0, 0, 0))
    p.setColor(role.Link, _DARK_LINK)
    p.setColor(role.Highlight, _DARK_ACCENT)
    p.setColor(role.HighlightedText, QColor(255, 255, 255))

    for text_role in (role.WindowText, role.Text, role.ButtonText):
        p.setColor(group.Disabled, text_role, _DARK_DISABLED_TEXT)
    p.setColor(group.Disabled, role.Base, QColor(38, 38, 38))
    p.setColor(group.Disabled, role.Button, QColor(38, 38, 38))
    p.setColor(group.Disabled, role.Highlight, QColor(60, 60, 62))
    return p


def _light_palette(app: QApplication) -> QPalette:
    """浅色主题直接用系统风格的标准调色板，保持与未改版前完全一致的外观。"""
    palette = app.style().standardPalette()
    if palette.color(QPalette.ColorRole.PlaceholderText).alpha() == 0:
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(117, 117, 117))
    return palette


def apply_app_palette(app: QApplication | None = None) -> None:
    """按当前 qfluentwidgets 主题给 QApplication 装上对应的 palette。"""
    app = app or QApplication.instance()
    if app is None:
        return
    if isDarkTheme():
        app.setPalette(_dark_palette())
    else:
        app.setPalette(_light_palette(app))


def install_theme_palette(app: QApplication | None = None) -> None:
    """安装调色板并跟随后续主题切换（重复调用只生效一次）。"""
    global _installed
    app = app or QApplication.instance()
    if app is None:
        return
    apply_app_palette(app)
    if _installed:
        return
    _installed = True
    # 老版本 qfluentwidgets 没有 themeChangedFinished，退回 themeChanged。
    finished = getattr(qconfig, "themeChangedFinished", None)
    if finished is not None:
        finished.connect(lambda: apply_app_palette(app))
    else:
        qconfig.themeChanged.connect(lambda _theme: apply_app_palette(app))
