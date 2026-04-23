from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget

from .frozen_runtime import ensure_pyinstaller_dll_search_path

from qfluentwidgets import Theme, setTheme

from .acus_workspace import app_cache_dir
from .ui.main_window import MainWindow


def _app_icon_path() -> Path:
    """
    窗口 / QApplication 用图标。优先 .ico（与 PyInstaller / Windows HWND 一致），否则用 PNG。
    开发时可用仓库根 assets/icon.ico；打包后由 spec 复制到 static/logo/icon.ico。
    """
    logo = Path(__file__).resolve().parent / "static" / "logo"
    ico_packaged = logo / "icon.ico"
    if ico_packaged.is_file():
        return ico_packaged
    repo_ico = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
    if repo_ico.is_file():
        return repo_ico
    return logo / "ChuniEventer.png"


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


def _set_windows_hwnd_icons_from_ico(window: QWidget, ico_path: Path) -> None:
    """
    用真实 ICO 设置 HWND 的大/小图标。任务栏、Alt+Tab 常依赖 ICON_SMALL；
    若只对 BIG 用 PNG 去 LoadImage(IMAGE_ICON) 会失败，再把 SMALL 清成 0 就会变通用 exe 图标。
    """
    if sys.platform != "win32" or not ico_path.is_file() or ico_path.suffix.lower() != ".ico":
        return
    try:
        hwnd = int(window.winId())
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        u = ctypes.windll.user32
        hbig = u.LoadImageW(None, str(ico_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        hsm = u.LoadImageW(None, str(ico_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        if hbig:
            u.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hbig)
        if hsm:
            u.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hsm)
    except Exception:
        pass


def _setup_dialog_debug_logging() -> None:
    if os.getenv("CHUNI_DIALOG_DEBUG", "").strip() not in {"1", "true", "TRUE", "yes", "YES"}:
        return
    try:
        log_dir = app_cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "dialog_debug.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        logging.getLogger(__name__).warning(
            "dialog debug logging enabled, output=%s (parent_chain / qt.window vs normalized / modals)",
            log_file,
        )
    except Exception:
        # Non-fatal: if debug logging setup fails, continue app startup.
        pass


def main() -> int:
    ensure_pyinstaller_dll_search_path()
    _set_windows_appusermodel_id()
    _setup_dialog_debug_logging()
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
    if icon_path.suffix.lower() == ".ico":
        _set_windows_hwnd_icons_from_ico(w, icon_path)
    return app.exec()
