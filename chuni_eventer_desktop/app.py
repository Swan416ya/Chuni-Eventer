from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget

from .frozen_runtime import ensure_pyinstaller_dll_search_path

from qfluentwidgets import Theme, setTheme

from .ui.main_window import MainWindow


def _app_icon_path() -> Path:
    return Path(__file__).resolve().parent / "static" / "logo" / "ChuniEventer.png"


def _set_windows_appusermodel_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "chuni.eventer.desktop"
        )
    except Exception:
        # 非致命：设置失败不影响程序运行，只可能影响任务栏图标归属。
        pass


def _clear_windows_titlebar_small_icon(window: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_SMALL2 = 2
        ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, 0)
        ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL2, 0)
    except Exception:
        # 非致命：失败时最多保留原有标题栏小图标。
        pass


def _set_windows_alt_tab_icon(window: QWidget, icon_path: Path) -> None:
    if sys.platform != "win32" or not icon_path.is_file():
        return
    try:
        hwnd = int(window.winId())
        WM_SETICON = 0x0080
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        hicon = ctypes.windll.user32.LoadImageW(
            None,
            str(icon_path),
            IMAGE_ICON,
            0,
            0,
            LR_LOADFROMFILE,
        )
        if hicon:
            ctypes.windll.user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
    except Exception:
        # 非致命：失败时退回 Qt 默认窗口图标行为。
        pass


def main() -> int:
    ensure_pyinstaller_dll_search_path()
    _set_windows_appusermodel_id()
    app = QApplication(sys.argv)
    app.setApplicationName("chuni eventer desktop")
    icon_path = _app_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    setTheme(Theme.AUTO)

    w = MainWindow()
    if icon_path.is_file():
        w.setWindowIcon(QIcon(str(icon_path)))
    w.show()
    _set_windows_alt_tab_icon(w, icon_path)
    _clear_windows_titlebar_small_icon(w)
    return app.exec()
