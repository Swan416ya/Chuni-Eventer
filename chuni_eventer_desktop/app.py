from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QPalette

from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("chuni eventer desktop")
    app.setStyle("Fusion")

    # Light, modern-ish palette
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#F6F7FB"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#111827"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#F3F4F6"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#111827"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#111827"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#2563EB"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#111827"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#FFFFFF"))
    app.setPalette(pal)

    # Minimal light QSS for consistency
    app.setStyleSheet(
        """
        QMainWindow { background: #F6F7FB; }
        QTabWidget::pane { border: 1px solid #E5E7EB; border-radius: 10px; background: #FFFFFF; }
        QTabBar::tab {
          background: #EEF2FF;
          color: #111827;
          padding: 8px 14px;
          border: 1px solid #E5E7EB;
          border-bottom: none;
          border-top-left-radius: 10px;
          border-top-right-radius: 10px;
          margin-right: 6px;
        }
        QTabBar::tab:selected { background: #FFFFFF; }
        QPushButton {
          background: #2563EB;
          color: white;
          padding: 8px 12px;
          border: 1px solid #1D4ED8;
          border-radius: 10px;
        }
        QPushButton:hover { background: #1D4ED8; }
        QPushButton:disabled { background: #9CA3AF; border-color: #9CA3AF; }
        QLineEdit, QTextEdit {
          background: #FFFFFF;
          border: 1px solid #E5E7EB;
          border-radius: 10px;
          padding: 8px;
          selection-background-color: #2563EB;
        }
        QComboBox {
          background: #FFFFFF;
          border: 1px solid #E5E7EB;
          border-radius: 10px;
          padding: 6px 10px;
        }
        QHeaderView::section {
          background: #F3F4F6;
          border: none;
          padding: 8px;
          color: #111827;
          font-weight: 600;
        }
        """
    )

    w = MainWindow()
    w.show()
    return app.exec()

