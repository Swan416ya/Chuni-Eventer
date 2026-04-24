"""QFluentWidgets 风格消息框封装（与主窗口 MSFluentWindow 一致）。"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import TypeVar

from PyQt6.QtCore import QEventLoop, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

log = logging.getLogger(__name__)

_ACTIVE_MESSAGE_BOXES: list[QWidget] = []
_PENDING_DIALOG_OPS: list[Callable[[], None]] = []
_DIALOG_OPENING: bool = False

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


def _attach_message_box_debug_watchers(
    w: QWidget,
    *,
    parent: QWidget | None,
    title: str,
    tag: str,
) -> None:
    if not _dialog_debug_enabled():
        return
    try:
        yes_btn = getattr(w, "yesButton", None)
        cancel_btn = getattr(w, "cancelButton", None)

        def _log_btn_state(prefix: str) -> None:
            try:
                log.warning(
                    "[dialog-debug] %s title=%r yes(vis=%s,en=%s) cancel(vis=%s,en=%s)",
                    prefix,
                    title,
                    yes_btn.isVisible() if yes_btn is not None else None,
                    yes_btn.isEnabled() if yes_btn is not None else None,
                    cancel_btn.isVisible() if cancel_btn is not None else None,
                    cancel_btn.isEnabled() if cancel_btn is not None else None,
                )
            except Exception:
                log.exception("[dialog-debug] %s btn_state failed title=%r", prefix, title)

        def _poll() -> None:
            if w is None:
                return
            try:
                if not w.isVisible():
                    return
                active = QApplication.activeModalWidget()
                popup = QApplication.activePopupWidget()
                focus = QApplication.focusWidget()
                par = w.parentWidget()
                log.warning(
                    "[dialog-debug] %s poll title=%r w(vis=%s,en=%s,modal=%s) parent=%s parent_en=%s active_modal=%s active_popup=%s focus=%s",
                    tag,
                    title,
                    w.isVisible(),
                    w.isEnabled(),
                    w.windowModality(),
                    _dbg_widget_short(par),
                    par.isEnabled() if par is not None else None,
                    _dbg_widget_short(active),
                    _dbg_widget_short(popup),
                    _dbg_widget_short(focus),
                )
                _log_btn_state(f"{tag}:poll_buttons")
                QTimer.singleShot(1000, _poll)
            except RuntimeError:
                return
            except Exception:
                log.exception("[dialog-debug] %s poll failed title=%r", tag, title)

        if yes_btn is not None:
            yes_btn.clicked.connect(
                lambda *_: log.warning("[dialog-debug] %s yes_clicked title=%r", tag, title)
            )
        if cancel_btn is not None:
            cancel_btn.clicked.connect(
                lambda *_: log.warning("[dialog-debug] %s cancel_clicked title=%r", tag, title)
            )

        w.finished.connect(
            lambda code: log.warning("[dialog-debug] %s finished title=%r code=%s", tag, title, code)
        )
        w.destroyed.connect(
            lambda *_: log.warning("[dialog-debug] %s destroyed title=%r", tag, title)
        )
        _log_btn_state(f"{tag}:create_buttons")
        QTimer.singleShot(250, _poll)
    except Exception:
        log.exception("[dialog-debug] attach watchers failed tag=%s title=%r", tag, title)


def _create_safe_dialog_widget(
    *,
    title: str,
    text: str,
    parent: QWidget | None,
    kind: str,  # "message" | "question"
    single_button: bool = True,
    yes_text: str = "确定",
    no_text: str = "取消",
) -> QDialog:
    """
    Windows fallback dialog shell to avoid intermittent click-loss in QFluent MessageBox.
    Keep explicit yesButton/cancelButton attrs for debug/watchers compatibility.
    """
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.setModal(True)
    d.setObjectName("SafeDialogShell")
    d.resize(560, 320)

    root = QVBoxLayout(d)
    root.setContentsMargins(16, 14, 16, 14)
    root.setSpacing(10)

    body = QLabel(text, d)
    body.setWordWrap(True)
    body.setTextInteractionFlags(
        Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
    )
    body.setObjectName("SafeDialogBody")
    root.addWidget(body, 1)

    row = QHBoxLayout()
    row.addStretch(1)
    yes_btn = QPushButton(yes_text if kind == "question" else "OK", d)
    cancel_btn = QPushButton(no_text, d)

    yes_btn.clicked.connect(lambda: d.done(int(QDialog.DialogCode.Accepted)))
    cancel_btn.clicked.connect(lambda: d.done(int(QDialog.DialogCode.Rejected)))

    row.addWidget(cancel_btn)
    row.addWidget(yes_btn)
    root.addLayout(row)

    if kind == "message" and single_button:
        cancel_btn.hide()

    # Compatibility for existing debug hooks.
    d.yesButton = yes_btn  # type: ignore[attr-defined]
    d.cancelButton = cancel_btn  # type: ignore[attr-defined]
    return d


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


def _resolve_dialog_parent_now(parent: QWidget | None) -> QWidget | None:
    """
    Resolve parent at open-time:
    - Prefer currently active visible modal dialog (same modal layer)
    - Fallback to normalized top-level choice
    """
    try:
        am = QApplication.activeModalWidget()
        if isinstance(am, QDialog) and am.isVisible():
            return am
    except Exception:
        pass
    return _best_message_parent(parent)


def _defer_dialog_open_when_safe(
    *,
    parent: QWidget | None,
    title: str,
    tag: str,
    open_fn: Callable[[], None],
    attempt: int = 0,
    max_attempts: int = 80,
) -> None:
    """
    Open dialog only when modal/popup state is stable. This avoids "click beep + no response"
    caused by opening a MessageBox in a different modal layer.
    """
    # If there is an active popup/menu, wait for it to close first.
    try:
        ap = QApplication.activePopupWidget()
        if ap is not None and ap.isVisible():
            if _dialog_debug_enabled():
                log.warning("[dialog-debug] %s delayed by active_popup=%s", tag, _dbg_widget_short(ap))
            if attempt < max_attempts:
                QTimer.singleShot(
                    25,
                    lambda: _defer_dialog_open_when_safe(
                        parent=parent,
                        title=title,
                        tag=tag,
                        open_fn=open_fn,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                    ),
                )
                return
    except Exception:
        pass
    open_fn()


def _ensure_enabled_for_dialog_parent(box_parent: QWidget | None) -> None:
    """Ensure the actual dialog parent chain is enabled before open()."""
    if box_parent is None:
        return
    try:
        w: QWidget | None = box_parent
        hops = 0
        while w is not None and hops < 12:
            if not w.isEnabled():
                w.setEnabled(True)
            w = w.parentWidget()
            hops += 1
    except Exception:
        pass


def _release_qt_input_grabs() -> None:
    """
    Defensive: release stale mouse/keyboard grabs before opening a modal dialog.
    This can happen after complex widget interactions and causes dialog buttons
    to be visible but never receive click events.
    """
    try:
        mg = QWidget.mouseGrabber()
        if mg is not None:
            if _dialog_debug_enabled():
                log.warning("[dialog-debug] release stale mouse grabber=%s", _dbg_widget_short(mg))
            try:
                mg.releaseMouse()
            except Exception:
                pass
    except Exception:
        pass
    try:
        kg = QWidget.keyboardGrabber()
        if kg is not None:
            if _dialog_debug_enabled():
                log.warning("[dialog-debug] release stale keyboard grabber=%s", _dbg_widget_short(kg))
            try:
                kg.releaseKeyboard()
            except Exception:
                pass
    except Exception:
        pass


def _stabilize_message_box_focus(
    w: QWidget,
    *,
    window_modal: bool,
    title: str,
    tag: str,
) -> None:
    """
    On some Windows + frameless stacks, MessageBox shows but does not receive click events
    unless we explicitly re-activate and focus button after open.
    """
    try:
        if window_modal:
            w.setWindowModality(Qt.WindowModality.ApplicationModal)
        w.raise_()
        w.activateWindow()
        yes_btn = getattr(w, "yesButton", None)
        if yes_btn is not None:
            yes_btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    except Exception:
        if _dialog_debug_enabled():
            log.exception("[dialog-debug] %s stabilize failed title=%r", tag, title)

    # Re-apply once in next tick to survive style/framework post-show adjustments.
    def _tick() -> None:
        try:
            if not w.isVisible():
                return
            if window_modal:
                w.setWindowModality(Qt.WindowModality.ApplicationModal)
            w.raise_()
            w.activateWindow()
            yes_btn = getattr(w, "yesButton", None)
            if yes_btn is not None:
                yes_btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
            if _dialog_debug_enabled():
                log.warning(
                    "[dialog-debug] %s stabilize_tick title=%r active_window=%s focus=%s",
                    tag,
                    title,
                    _dbg_widget_short(QApplication.activeWindow()),
                    _dbg_widget_short(QApplication.focusWidget()),
                )
        except Exception:
            if _dialog_debug_enabled():
                log.exception("[dialog-debug] %s stabilize_tick failed title=%r", tag, title)

    QTimer.singleShot(0, _tick)
    QTimer.singleShot(80, _tick)


def _enqueue_dialog_open(op: Callable[[], None]) -> None:
    global _DIALOG_OPENING
    _PENDING_DIALOG_OPS.append(op)
    if _DIALOG_OPENING:
        return
    _DIALOG_OPENING = True
    _drain_dialog_queue()


def _drain_dialog_queue() -> None:
    global _DIALOG_OPENING
    if _ACTIVE_MESSAGE_BOXES:
        QTimer.singleShot(25, _drain_dialog_queue)
        return
    if not _PENDING_DIALOG_OPS:
        _DIALOG_OPENING = False
        return
    op = _PENDING_DIALOG_OPS.pop(0)
    try:
        op()
    finally:
        if _PENDING_DIALOG_OPS:
            QTimer.singleShot(0, _drain_dialog_queue)
        elif not _ACTIVE_MESSAGE_BOXES:
            _DIALOG_OPENING = False


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
    # Global safety policy: all info/warn/error popups use async modal opening path.
    # This avoids nested local event-loops and reduces Windows input deadlock risk.
    fly_message_async(parent, title, text, single_button=single_button, window_modal=True)


def fly_warning(parent: QWidget | None, title: str, text: str) -> None:
    fly_message_async(parent, title, text, single_button=True, window_modal=True)


def fly_critical(parent: QWidget | None, title: str, text: str) -> None:
    fly_message_async(parent, title, text, single_button=True, window_modal=True)


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
        box_parent = _resolve_dialog_parent_now(parent)
        _debug_state("fly_message_async:create", parent, title=title)
        if box_parent is None:
            log.warning("fly_message_async skipped: no valid parent title=%r text=%r", title, text)
            return
        _release_qt_input_grabs()
        _ensure_enabled_for_dialog_parent(box_parent)
        w = _create_safe_dialog_widget(
            title=title,
            text=text,
            parent=box_parent,
            kind="message",
            single_button=single_button,
        )
        w.setWindowModality(
            Qt.WindowModality.ApplicationModal if window_modal else Qt.WindowModality.NonModal
        )
        _attach_message_box_debug_watchers(w, parent=parent, title=title, tag="fly_message_async")

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
        _stabilize_message_box_focus(
            w,
            window_modal=window_modal,
            title=title,
            tag="fly_message_async",
        )
        _debug_state("fly_message_async:after_open", parent, title=title, message_box=w)
        log.debug("fly_message_async open called title=%r", title)

    _debug_defer("fly_message_async", parent, title=title)
    _enqueue_dialog_open(
        lambda: _defer_dialog_open_when_safe(
            parent=parent,
            title=title,
            tag="fly_message_async",
            open_fn=lambda: _defer_to_next_event_loop(_show),
        )
    )


def fly_question(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    yes_text: str = "确定",
    no_text: str = "取消",
) -> bool:
    """是 / 否。返回 True 表示点击确认（yes）。"""
    box_parent = _resolve_dialog_parent_now(parent)
    _debug_state("fly_question:create", parent, title=title)
    if box_parent is None:
        log.warning("fly_question fallback=False: no valid parent title=%r text=%r", title, text)
        return False

    def _exec() -> bool:
        w = _create_safe_dialog_widget(
            title=title,
            text=text,
            parent=box_parent,
            kind="question",
            yes_text=yes_text,
            no_text=no_text,
        )
        w.setWindowModality(Qt.WindowModality.ApplicationModal)
        out = {"accepted": False}
        loop = QEventLoop()

        def _done(code: int) -> None:
            out["accepted"] = code == int(QDialog.DialogCode.Accepted)
            loop.quit()

        w.finished.connect(_done)
        w.open()
        loop.exec()
        return bool(out["accepted"])

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
        box_parent = _resolve_dialog_parent_now(parent)
        _debug_state("fly_question_async:create", parent, title=title)
        if box_parent is None:
            log.warning("fly_question_async fallback=False: no valid parent title=%r text=%r", title, text)
            try:
                on_result(False)
            except Exception:
                log.exception("fly_question_async on_result failed during fallback")
            return
        _release_qt_input_grabs()
        _ensure_enabled_for_dialog_parent(box_parent)
        w = _create_safe_dialog_widget(
            title=title,
            text=text,
            parent=box_parent,
            kind="question",
            yes_text=yes_text,
            no_text=no_text,
        )
        w.setWindowModality(
            Qt.WindowModality.ApplicationModal if window_modal else Qt.WindowModality.NonModal
        )
        _attach_message_box_debug_watchers(w, parent=parent, title=title, tag="fly_question_async")

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
        _stabilize_message_box_focus(
            w,
            window_modal=window_modal,
            title=title,
            tag="fly_question_async",
        )
        _debug_state("fly_question_async:after_open", parent, title=title, message_box=w)

    _debug_defer("fly_question_async", parent, title=title)
    _enqueue_dialog_open(
        lambda: _defer_dialog_open_when_safe(
            parent=parent,
            title=title,
            tag="fly_question_async",
            open_fn=lambda: _defer_to_next_event_loop(_show),
        )
    )
