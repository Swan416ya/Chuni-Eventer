"""QFluentWidgets 风格消息框封装（与主窗口 MSFluentWindow 一致）。"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import TypeVar

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QProgressDialog, QWidget

from qfluentwidgets import MessageBox

log = logging.getLogger(__name__)

_ACTIVE_MESSAGE_BOXES: list[MessageBox] = []

_T = TypeVar("_T")


def _dialog_debug_enabled() -> bool:
    return os.getenv("CHUNI_DIALOG_DEBUG", "").strip() in {"1", "true", "TRUE", "yes", "YES"}


def _dbg_widget_short(w: QWidget | None) -> str:
    if w is None:
        return "None"
    try:
        nm = (w.objectName() or "").strip() or "-"
        return f"{type(w).__name__}[{nm}](win={w.isWindow()},en={w.isEnabled()},vis={w.isVisible()})"
    except Exception:
        return f"<{type(w).__name__} err>"


def _dbg_parent_chain(start: QWidget | None, *, max_hops: int = 24) -> str:
    if start is None:
        return "(no parent)"
    parts: list[str] = []
    cur: QWidget | None = start
    for _ in range(max_hops):
        if cur is None:
            break
        parts.append(_dbg_widget_short(cur))
        cur = cur.parentWidget()
    return " <- ".join(parts)


def _debug_state(
    tag: str,
    parent: QWidget | None,
    *,
    title: str | None = None,
    message_box: QWidget | None = None,
) -> None:
    if not _dialog_debug_enabled():
        return
    try:
        norm = _normalize_parent(parent)
        best = _best_message_parent(parent)
        qt_win = parent.window() if parent is not None else None
        active = QApplication.activeModalWidget()
        popup = QApplication.activePopupWidget()
        aw = QApplication.activeWindow()
        focus = QApplication.focusWidget()
        log.warning(
            "[dialog-debug] %s title=%r\n"
            "  parent_chain=%s\n"
            "  qt.window(parent)=%s normalized=%s best=%s\n"
            "  same_id(qtwin,norm)=%s same_id(norm,best)=%s norm_enabled=%s\n"
            "  active_modal=%s active_popup=%s active_window=%s focus=%s\n"
            "  active_boxes=%d",
            tag,
            title,
            _dbg_parent_chain(parent),
            _dbg_widget_short(qt_win),
            _dbg_widget_short(norm),
            _dbg_widget_short(best),
            qt_win is norm,
            norm is best,
            norm.isEnabled() if norm is not None else None,
            _dbg_widget_short(active),
            _dbg_widget_short(popup),
            _dbg_widget_short(aw),
            _dbg_widget_short(focus),
            len(_ACTIVE_MESSAGE_BOXES),
        )
        if message_box is not None:
            try:
                mod = message_box.windowModality()
                try:
                    ism = message_box.isModal()
                except Exception:
                    ism = None
                log.warning(
                    "[dialog-debug] %s message_box=%s mb.parent=%s modality=%s isModal=%s",
                    tag,
                    _dbg_widget_short(message_box),
                    _dbg_widget_short(message_box.parentWidget()),
                    mod,
                    ism,
                )
            except Exception:
                log.exception("[dialog-debug] message_box probe failed tag=%s", tag)
    except Exception:
        log.exception("[dialog-debug] failed to collect state for %s", tag)


def _debug_defer(tag: str, parent: QWidget | None, *, title: str | None = None) -> None:
    if not _dialog_debug_enabled():
        return
    log.warning(
        "[dialog-debug] %s QTimer.singleShot(0) scheduled title=%r caller_parent=%s",
        tag,
        title,
        _dbg_widget_short(parent),
    )


def _normalize_parent(parent: QWidget | None) -> QWidget | None:
    """
    用于 MessageBox / 模态的父窗口：必须是带 window handle 的**层级根**窗口。

    不能沿用「沿 parent 找到第一个 isWindow()」：在 MSFluentWindow 里，
    stackedWidget 等子控件可能 isWindow()==True 却仍有 parent（内部 QWidgetWindow），
    此时 `QWidget.window()` 会停在这一层，进而触发
    "StackedWidgetClassWindow must be a top level window" 且模态点击失效。
    正确做法是沿 parentWidget() 一直走到无 parent 的根，再校验 isWindow()。
    """
    if parent is None:
        return None
    try:
        w: QWidget | None = parent
        while w.parentWidget() is not None:
            w = w.parentWidget()
        return w if w is not None and w.isWindow() else None
    except Exception:
        return None


def _best_message_parent(parent: QWidget | None) -> QWidget | None:
    """Return a stable top-level parent for MessageBox, or None."""
    # If caller itself is a visible modal dialog, keep MessageBox attached to it.
    # Otherwise we may end up parenting to MainWindow while the dialog is still modal,
    # which can produce an unclickable "back-layer" message box on Windows.
    if parent is not None:
        try:
            if isinstance(parent, QDialog) and parent.isVisible() and parent.isModal():
                return parent
        except Exception:
            pass
    p = _normalize_parent(parent)
    if p is not None:
        return p
    try:
        aw = QApplication.activeWindow()
        p = _normalize_parent(aw)
        if p is not None:
            return p
    except Exception:
        pass
    try:
        for w in QApplication.topLevelWidgets():
            if w is None or not w.isVisible():
                continue
            p = _normalize_parent(w)
            if p is not None:
                return p
    except Exception:
        pass
    return None


def _run_modal_with_enabled_top(parent: QWidget | None, fn: Callable[[], _T]) -> _T:
    """
    在顶层父窗被 setEnabled(False) 时仍同步弹出 MessageBox，Windows 上会导致
    「全局点击无效 + 系统提示音」。此处仅在 exec 前强制启用顶层；关闭后不再设回
    False，否则成功/失败提示后用户会再次被整窗禁用而无法点按钮（需由业务在适当时机自行禁用）。
    """
    top = _normalize_parent(parent)
    _debug_state("before_modal_exec", parent)
    if top is not None and not top.isEnabled():
        top.setEnabled(True)
    # Avoid force-activating parent window here: in some widget hierarchies
    # (e.g. stacked views) this can emit "must be a top level window" and
    # may destabilize modal input routing on Windows.
    out = fn()
    _debug_state("after_modal_exec", parent)
    return out


def _defer_to_next_event_loop(fn: Callable[[], None]) -> None:
    """
    推迟到当前事件处理结束后再执行。Fluent 右键菜单等在同一次交付里若立刻
    open() 一个 WindowModal MessageBox，在 Windows 上会出现「看得见但点不了」；
    这与启动略慢时（例如 python -X faulthandler）现象不一致，故用单次 0ms
    定时器与菜单栈 unwind 对齐。
    """
    QTimer.singleShot(0, fn)


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
    box_parent = _best_message_parent(parent)
    _debug_state("fly_message:create", parent, title=title)
    if box_parent is None:
        log.warning("fly_message skipped: no valid parent title=%r text=%r", title, text)
        return

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
    def _show() -> None:
        box_parent = _best_message_parent(parent)
        _debug_state("fly_message_async:create", parent, title=title)
        if box_parent is None:
            log.warning("fly_message_async skipped: no valid parent title=%r text=%r", title, text)
            return
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
            _debug_state("fly_message_async:finished", parent, title=title)
            log.debug("fly_message_async finished code=%s title=%r", _code, title)
            try:
                _ACTIVE_MESSAGE_BOXES.remove(w)
            except ValueError:
                pass
            log.debug("fly_message_async active_after=%d", len(_ACTIVE_MESSAGE_BOXES))
            w.deleteLater()

        w.destroyed.connect(lambda *_: log.debug("fly_message_async destroyed title=%r", title))
        w.finished.connect(_on_finished)
        _debug_state("fly_message_async:before_open", parent, title=title, message_box=w)
        w.open()
        _debug_state("fly_message_async:after_open", parent, title=title, message_box=w)
        log.debug("fly_message_async open called title=%r", title)

    _debug_defer("fly_message_async", parent, title=title)
    _defer_to_next_event_loop(_show)


def fly_question(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    yes_text: str = "确定",
    no_text: str = "取消",
) -> bool:
    """Fluent MessageBox：是 / 否。返回 True 表示点击确认（yes）。"""
    box_parent = _best_message_parent(parent)
    _debug_state("fly_question:create", parent, title=title)
    if box_parent is None:
        log.warning("fly_question fallback=False: no valid parent title=%r text=%r", title, text)
        return False

    def _exec() -> bool:
        w = MessageBox(title, text, box_parent)
        w.yesButton.setText(yes_text)
        w.cancelButton.setText(no_text)
        w.setWindowModality(Qt.WindowModality.WindowModal)
        return w.exec() == QDialog.DialogCode.Accepted

    return _run_modal_with_enabled_top(parent, _exec)


def fly_question_async(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    on_result: Callable[[bool], None],
    yes_text: str = "确定",
    no_text: str = "取消",
    window_modal: bool = True,
) -> None:
    """
    非阻塞确认框：避免在复杂层级中使用 exec() 造成卡死。
    on_result(True) 表示确认，False 表示取消/关闭。
    """
    def _show() -> None:
        box_parent = _best_message_parent(parent)
        _debug_state("fly_question_async:create", parent, title=title)
        if box_parent is None:
            log.warning("fly_question_async fallback=False: no valid parent title=%r text=%r", title, text)
            try:
                on_result(False)
            except Exception:
                log.exception("fly_question_async on_result failed during fallback")
            return
        w = MessageBox(title, text, box_parent)
        w.yesButton.setText(yes_text)
        w.cancelButton.setText(no_text)
        w.setWindowModality(
            Qt.WindowModality.WindowModal if window_modal else Qt.WindowModality.NonModal
        )

        top = _normalize_parent(parent)
        if window_modal and top is not None and not top.isEnabled():
            top.setEnabled(True)

        _ACTIVE_MESSAGE_BOXES.append(w)

        def _on_finished(code: int) -> None:
            accepted = code == int(QDialog.DialogCode.Accepted)
            _debug_state("fly_question_async:finished", parent, title=title)
            if _dialog_debug_enabled():
                log.warning(
                    "[dialog-debug] fly_question_async result title=%r code=%s accepted=%s",
                    title,
                    code,
                    bool(accepted),
                )
            try:
                on_result(bool(accepted))
            except Exception:
                log.exception("fly_question_async on_result failed")
            try:
                _ACTIVE_MESSAGE_BOXES.remove(w)
            except ValueError:
                pass
            w.deleteLater()

        w.finished.connect(_on_finished)
        _debug_state("fly_question_async:before_open", parent, title=title, message_box=w)
        w.open()
        _debug_state("fly_question_async:after_open", parent, title=title, message_box=w)

    _debug_defer("fly_question_async", parent, title=title)
    _defer_to_next_event_loop(_show)
