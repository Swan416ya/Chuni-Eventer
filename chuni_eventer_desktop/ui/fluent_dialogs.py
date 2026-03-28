"""QFluentWidgets 风格消息框封装（与主窗口 MSFluentWindow 一致）。"""

from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from qfluentwidgets import MessageBox


def fly_message(parent: QWidget | None, title: str, text: str, *, single_button: bool = True) -> None:
    w = MessageBox(title, text, parent)
    if single_button:
        w.cancelButton.hide()
    w.exec()


def fly_warning(parent: QWidget | None, title: str, text: str) -> None:
    fly_message(parent, title, text, single_button=True)


def fly_critical(parent: QWidget | None, title: str, text: str) -> None:
    fly_message(parent, title, text, single_button=True)
