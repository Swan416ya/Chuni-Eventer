"""QFluentWidgets 风格消息框封装（与主窗口 MSFluentWindow 一致）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QDialog, QProgressDialog, QWidget

from qfluentwidgets import MessageBox

log = logging.getLogger(__name__)

_ACTIVE_MESSAGE_BOXES: list[MessageBox] = []

_T = TypeVar("_T")


def _normalize_parent(parent: QWidget | None) -> QWidget | None:
    if parent is None:
        return None
    try:
        # Always attach to a top-level window to avoid non-top-level modal glitches.
        w: QWidget | None = parent
        while w is not None and not w.isWindow():
            w = w.parentWidget()
        if w is not None and w.isWindow():
            return w
        if parent.isWindow():
            return parent
        return None
    except Exception:
        return parent if parent.isWindow() else None


def _run_modal_with_enabled_top(parent: QWidget | None, fn: Callable[[], _T]) -> _T:
    """
    在顶层父窗被 setEnabled(False) 时仍同步弹出 MessageBox，Windows 上会导致
    「全局点击无效 + 系统提示音」。此处仅在 exec 前强制启用顶层；关闭后不再设回
    False，否则成功/失败提示后用户会再次被整窗禁用而无法点按钮（需由业务在适当时机自行禁用）。
    """
    top = _normalize_parent(parent)
    if top is not None and not top.isEnabled():
        top.setEnabled(True)
    try:
        return fn()
    finally:
        if top is not None and top.isWindow():
            try:
                top.raise_()
                top.activateWindow()
            except (RuntimeError, TypeError):
                pass


def safe_dismiss_modal_progress_dialog(dlg: QProgressDialog | None) -> None:
    """
    关闭曾设为 WindowModal 的 QProgressDialog，避免在无边框父窗下残留隐形模态，
    导致后续 MessageBox 无法点击。
    """
    if dlg is None:
        return
    try:
        dlg.reset()
    except RuntimeError:
        return
    try:
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.close()
        dlg.deleteLater()
    except RuntimeError:
        return
    QApplication.processEvents()


def fly_message(parent: QWidget | None, title: str, text: str, *, single_button: bool = True) -> None:
    box_parent = _normalize_parent(parent)

    def _exec() -> None:
        w = MessageBox(title, text, box_parent)
        if single_button:
            w.cancelButton.hide()
        w.setWindowModality(Qt.WindowModality.WindowModal)
        w.exec()

    _run_modal_with_enabled_top(parent, _exec)


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
    box_parent = _normalize_parent(parent)
    w = MessageBox(title, text, box_parent)
    if single_button:
        w.cancelButton.hide()
    w.setWindowModality(Qt.WindowModality.WindowModal if window_modal else Qt.WindowModality.NonModal)

    top = _normalize_parent(parent)
    if window_modal and top is not None and not top.isEnabled():
        top.setEnabled(True)

    _ACTIVE_MESSAGE_BOXES.append(w)
    ts = time.time()
    log.debug(
        "fly_message_async create ts=%.3f title=%r active=%d",
        ts,
        title,
        len(_ACTIVE_MESSAGE_BOXES),
    )

    def _on_finished(_code: int) -> None:
        log.debug("fly_message_async finished code=%s title=%r", _code, title)
        try:
            _ACTIVE_MESSAGE_BOXES.remove(w)
        except ValueError:
            pass
        log.debug("fly_message_async active_after=%d", len(_ACTIVE_MESSAGE_BOXES))
        w.deleteLater()

    w.destroyed.connect(lambda *_: log.debug("fly_message_async destroyed title=%r", title))
    w.finished.connect(_on_finished)
    w.open()
    log.debug("fly_message_async open called title=%r", title)


def fly_question(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    yes_text: str = "确定",
    no_text: str = "取消",
) -> bool:
    """Fluent MessageBox：是 / 否。返回 True 表示点击确认（yes）。"""
    box_parent = _normalize_parent(parent)

    def _exec() -> bool:
        w = MessageBox(title, text, box_parent)
        w.yesButton.setText(yes_text)
        w.cancelButton.setText(no_text)
        w.setWindowModality(Qt.WindowModality.WindowModal)
        return w.exec() == QDialog.DialogCode.Accepted

    return _run_modal_with_enabled_top(parent, _exec)
