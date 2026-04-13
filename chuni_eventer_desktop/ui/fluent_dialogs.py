"""QFluentWidgets 风格消息框封装（与主窗口 MSFluentWindow 一致）。"""

from __future__ import annotations

from PyQt6.QtWidgets import QDialog, QWidget

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


def fly_question(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    yes_text: str = "确定",
    no_text: str = "取消",
) -> bool:
    """Fluent MessageBox：是 / 否。返回 True 表示点击确认（yes）。"""
    w = MessageBox(title, text, parent)
    w.yesButton.setText(yes_text)
    w.cancelButton.setText(no_text)
    return w.exec() == QDialog.DialogCode.Accepted
