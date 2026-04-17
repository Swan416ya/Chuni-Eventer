"""QFluentWidgets 风格消息框封装（与主窗口 MSFluentWindow 一致）。"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QWidget

from qfluentwidgets import MessageBox

_ACTIVE_MESSAGE_BOXES: list[MessageBox] = []


def _normalize_parent(parent: QWidget | None) -> QWidget | None:
    if parent is None:
        return None
    try:
        # Always attach to a top-level window to avoid non-top-level modal glitches.
        w = parent.window()
        return w if isinstance(w, QWidget) else parent
    except Exception:
        return parent


def fly_message(parent: QWidget | None, title: str, text: str, *, single_button: bool = True) -> None:
    w = MessageBox(title, text, _normalize_parent(parent))
    if single_button:
        w.cancelButton.hide()
    w.setWindowModality(Qt.WindowModality.WindowModal)
    w.exec()


def fly_warning(parent: QWidget | None, title: str, text: str) -> None:
    fly_message(parent, title, text, single_button=True)


def fly_critical(parent: QWidget | None, title: str, text: str) -> None:
    fly_message(parent, title, text, single_button=True)


def fly_message_async(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    single_button: bool = True,
    window_modal: bool = False,
) -> None:
    """
    非阻塞提示框：用于避免连环模态框导致 UI 卡死。
    """
    w = MessageBox(title, text, _normalize_parent(parent))
    if single_button:
        w.cancelButton.hide()
    w.setWindowModality(Qt.WindowModality.WindowModal if window_modal else Qt.WindowModality.NonModal)

    _ACTIVE_MESSAGE_BOXES.append(w)
    ts = time.time()
    print(f"[dialog-debug] fly_message_async create ts={ts:.3f} title={title!r} active={len(_ACTIVE_MESSAGE_BOXES)}")

    def _on_finished(_code: int) -> None:
        print(f"[dialog-debug] fly_message_async finished code={_code} title={title!r}")
        try:
            _ACTIVE_MESSAGE_BOXES.remove(w)
        except ValueError:
            pass
        print(f"[dialog-debug] fly_message_async active_after={len(_ACTIVE_MESSAGE_BOXES)}")
        w.deleteLater()

    w.destroyed.connect(lambda *_: print(f"[dialog-debug] fly_message_async destroyed title={title!r}"))
    w.finished.connect(_on_finished)
    w.open()
    print(f"[dialog-debug] fly_message_async open called title={title!r}")


def fly_question(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    yes_text: str = "确定",
    no_text: str = "取消",
) -> bool:
    """Fluent MessageBox：是 / 否。返回 True 表示点击确认（yes）。"""
    w = MessageBox(title, text, _normalize_parent(parent))
    w.yesButton.setText(yes_text)
    w.cancelButton.setText(no_text)
    w.setWindowModality(Qt.WindowModality.WindowModal)
    return w.exec() == QDialog.DialogCode.Accepted
