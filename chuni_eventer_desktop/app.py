from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from qfluentwidgets import Theme, setTheme

from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("chuni eventer desktop")
    setTheme(Theme.AUTO)

    w = MainWindow()
    w.show()
    return app.exec()
