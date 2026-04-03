from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .frozen_runtime import ensure_pyinstaller_dll_search_path

from qfluentwidgets import Theme, setTheme

from .ui.main_window import MainWindow


def main() -> int:
    ensure_pyinstaller_dll_search_path()
    app = QApplication(sys.argv)
    app.setApplicationName("chuni eventer desktop")
    setTheme(Theme.AUTO)

    w = MainWindow()
    w.show()
    return app.exec()
