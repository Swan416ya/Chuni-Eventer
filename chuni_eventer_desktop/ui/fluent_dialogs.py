"""应用内统一提示 / 确认框：Qt 原生 QMessageBox + Fluent 风格 QSS（与 qfluentwidgets 明暗主题对齐）。"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Callable
from typing import TypeVar

from PyQt6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QWidget,
)

log = logging.getLogger(__name__)

_FLY_MSGBOX_OBJECT_NAME = "FlyNativeMessageBox"
# Accent for primary actions (matches app branding request)
_FLY_PRIMARY = "#009faa"
_FLY_PRIMARY_HOVER = "#008896"
_FLY_PRIMARY_BORDER = "#009faa"


def _is_app_dark_theme() -> bool:
    try:
        from qfluentwidgets import isDarkTheme

        return bool(isDarkTheme())
    except Exception:
        return False


def _fluent_native_message_box_stylesheet() -> str:
    """QSS approximating Fluent / QFluentWidgets dialog look on top of QMessageBox."""
    if _is_app_dark_theme():
        bg = "#2b2b2b"
        border = "rgba(255, 255, 255, 0.12)"
        body_fg = "#d1d5db"
        primary_bg = _FLY_PRIMARY
        primary_border = _FLY_PRIMARY_BORDER
        primary_hover = _FLY_PRIMARY_HOVER
        secondary_bg = "rgba(255, 255, 255, 0.06)"
        secondary_border = "rgba(255, 255, 255, 0.18)"
        secondary_hover = "rgba(255, 255, 255, 0.10)"
        secondary_fg = "#e5e7eb"
    else:
        bg = "#ffffff"
        border = "#d8dee9"
        body_fg = "#374151"
        primary_bg = _FLY_PRIMARY
        primary_border = _FLY_PRIMARY_BORDER
        primary_hover = _FLY_PRIMARY_HOVER
        secondary_bg = "#ffffff"
        secondary_border = "#d1d5db"
        secondary_hover = "#f3f4f6"
        secondary_fg = "#374151"

    return f"""
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} {{
            background-color: {bg};
            border: 1px solid {border};
            border-radius: 8px;
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QLabel {{
            color: {body_fg};
            font-size: 13px;
            padding: 0px 2px;
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QLabel#qt_msgbox_label {{
            color: {body_fg};
            min-width: 280px;
            padding: 8px 10px 4px 10px;
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QLabel#qt_msgboxex_icon_label,
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QLabel#qt_msgbox_icon_label {{
            max-width: 0px;
            min-width: 0px;
            width: 0px;
            padding: 0px;
            margin: 0px;
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QDialogButtonBox {{
            padding: 2px 6px 6px 6px;
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QDialogButtonBox QPushButton {{
            min-height: 22px;
            min-width: 0px;
            border-radius: 6px;
            padding: 2px 8px;
            font-size: 13px;
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QDialogButtonBox QPushButton:default {{
            background-color: {primary_bg};
            color: #ffffff;
            border: 1px solid {primary_border};
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QDialogButtonBox QPushButton:default:hover {{
            background-color: {primary_hover};
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QDialogButtonBox QPushButton:!default {{
            background-color: {secondary_bg};
            color: {secondary_fg};
            border: 1px solid {secondary_border};
        }}
        QMessageBox#{_FLY_MSGBOX_OBJECT_NAME} QDialogButtonBox QPushButton:!default:hover {{
            background-color: {secondary_hover};
        }}
    """.strip()


def _hide_native_message_box_icon(mb: QMessageBox, *, strip_icon: bool) -> None:
    """Remove left icon column for confirm dialogs; keep icons for info/warning/critical."""
    if not strip_icon:
        return
    try:
        mb.setIcon(QMessageBox.Icon.NoIcon)
        for lab in mb.findChildren(QLabel):
            try:
                on = (lab.objectName() or "").lower()
                if "icon" in on:
                    lab.hide()
                    lab.setMaximumWidth(0)
                    continue
                if on == "qt_msgbox_label":
                    continue
                pm = lab.pixmap()
                if pm is not None and not pm.isNull():
                    lab.hide()
                    lab.setMaximumWidth(0)
            except Exception:
                continue
    except Exception:
        pass


def _layout_native_message_box_button_row(mb: QMessageBox) -> None:
    """Make dialog buttons expand to fill the bottom row (remove centering spacers when possible)."""
    try:
        box = mb.findChild(QDialogButtonBox)
        if box is None:
            return
        lay = box.layout()
        if isinstance(lay, QHBoxLayout):
            idx = 0
            while idx < lay.count():
                it = lay.itemAt(idx)
                if it is not None and it.spacerItem() is not None:
                    lay.removeItem(it)
                    continue
                idx += 1
            lay.setContentsMargins(6, 2, 6, 6)
            lay.setSpacing(6)
            for i in range(lay.count()):
                it = lay.itemAt(i)
                if it is None:
                    continue
                w = it.widget()
                if isinstance(w, QPushButton):
                    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                    lay.setStretch(i, 1)
        else:
            for b in box.findChildren(QPushButton):
                b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    except Exception:
        pass


def _apply_fluent_style_to_native_message_box(mb: QMessageBox, *, strip_icon: bool = False) -> None:
    """Best-effort Fluent-like skin; native QMessageBox still respects platform quirks."""
    try:
        mb.setObjectName(_FLY_MSGBOX_OBJECT_NAME)
        mb.setMinimumWidth(400)
        mb.setStyleSheet(_fluent_native_message_box_stylesheet())
        _hide_native_message_box_icon(mb, strip_icon=strip_icon)
        _layout_native_message_box_button_row(mb)

        def _relayout() -> None:
            try:
                _layout_native_message_box_button_row(mb)
            except RuntimeError:
                return

        QTimer.singleShot(0, _relayout)
    except Exception:
        log.exception("apply fluent style to QMessageBox failed")

_ACTIVE_MESSAGE_BOXES: list[QWidget] = []
_PENDING_DIALOG_OPS: list[Callable[[], None]] = []
_DIALOG_OPENING: bool = False
_MOUSE_PROBE_INSTALLED: bool = False
_MOUSE_PROBE: QObject | None = None

_T = TypeVar("_T")


def _native_question_accepted(code: int) -> bool:
    return code == int(QMessageBox.StandardButton.Yes)


def _configure_native_message_box(
    mb: QMessageBox,
    *,
    title: str,
    text: str,
    icon: QMessageBox.Icon,
    single_button: bool,
) -> None:
    mb.setWindowTitle(title)
    mb.setText(text)
    mb.setIcon(icon)
    if single_button:
        mb.setStandardButtons(QMessageBox.StandardButton.Ok)
        mb.setDefaultButton(QMessageBox.StandardButton.Ok)
    else:
        mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        mb.setDefaultButton(QMessageBox.StandardButton.Yes)
    _apply_fluent_style_to_native_message_box(mb, strip_icon=False)


def _configure_native_question_box(
    mb: QMessageBox,
    *,
    title: str,
    text: str,
    yes_text: str,
    no_text: str,
) -> None:
    mb.setWindowTitle(title)
    mb.setText(text)
    mb.setIcon(QMessageBox.Icon.NoIcon)
    mb.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    y = mb.button(QMessageBox.StandardButton.Yes)
    n = mb.button(QMessageBox.StandardButton.No)
    if y is not None:
        y.setText(yes_text)
    if n is not None:
        n.setText(no_text)
    mb.setDefaultButton(QMessageBox.StandardButton.Yes)
    _apply_fluent_style_to_native_message_box(mb, strip_icon=True)


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


class _GlobalMouseProbe(QObject):
    def eventFilter(self, obj: QObject | None, event: QEvent | None) -> bool:  # noqa: N802
        if not _dialog_debug_enabled():
            return False
        if not _ACTIVE_MESSAGE_BOXES:
            return False
        if event is None:
            return False
        t = event.type()
        if t not in {
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonRelease,
            QEvent.Type.MouseButtonDblClick,
        }:
            return False
        try:
            target = obj if isinstance(obj, QWidget) else None
            focus = QApplication.focusWidget()
            active = QApplication.activeModalWidget()
            log.warning(
                "[dialog-debug] mouse_probe type=%s target=%s focus=%s active_modal=%s",
                int(t),
                _dbg_widget_short(target),
                _dbg_widget_short(focus),
                _dbg_widget_short(active if isinstance(active, QWidget) else None),
            )
        except Exception:
            log.exception("[dialog-debug] mouse_probe logging failed")
        return False


def _ensure_global_mouse_probe() -> None:
    global _MOUSE_PROBE_INSTALLED, _MOUSE_PROBE
    if _MOUSE_PROBE_INSTALLED or not _dialog_debug_enabled():
        return
    app = QApplication.instance()
    if app is None:
        return
    try:
        _MOUSE_PROBE = _GlobalMouseProbe()
        app.installEventFilter(_MOUSE_PROBE)
        _MOUSE_PROBE_INSTALLED = True
        log.warning("[dialog-debug] global mouse probe installed")
    except Exception:
        log.exception("[dialog-debug] install global mouse probe failed")


def _attach_message_box_debug_watchers(
    w: QWidget,
    *,
    parent: QWidget | None,
    title: str,
    tag: str,
) -> None:
    if not _dialog_debug_enabled():
        return
    _ensure_global_mouse_probe()
    try:
        if isinstance(w, QMessageBox):
            yes_btn = w.button(QMessageBox.StandardButton.Yes) or w.button(QMessageBox.StandardButton.Ok)
            cancel_btn = w.button(QMessageBox.StandardButton.No) or w.button(QMessageBox.StandardButton.Cancel)
        else:
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
    _release_windows_input_capture()


def _release_windows_input_capture() -> None:
    """Release native Win32 mouse capture. Do not post WM_CANCELMODE here — it can
    dismiss or break a QMessageBox that was just opened on the same event loop tick."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.user32.ReleaseCapture()
    except Exception:
        if _dialog_debug_enabled():
            log.exception("[dialog-debug] release_windows_input_capture failed")


def _stabilize_message_box_focus(
    w: QWidget,
    *,
    window_modal: bool,
    title: str,
    tag: str,
) -> None:
    """
    After QMessageBox.open(), nudge raise/focus. Do not change modality here:
    QDialog.open() already uses window-modal semantics; re-applying ApplicationModal
    breaks native QMessageBox on some Windows setups.
    """
    _ = window_modal

    def _nudge_focus() -> None:
        try:
            if not w.isVisible():
                return
            w.raise_()
            w.activateWindow()
            btn = None
            if isinstance(w, QMessageBox):
                btn = w.defaultButton()
                if btn is None and w.buttons():
                    btn = w.buttons()[0]
            else:
                btn = getattr(w, "yesButton", None)
            if btn is not None:
                btn.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
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

    try:
        _nudge_focus()
    except Exception:
        if _dialog_debug_enabled():
            log.exception("[dialog-debug] %s stabilize failed title=%r", tag, title)

    QTimer.singleShot(0, _nudge_focus)
    QTimer.singleShot(80, _nudge_focus)


def _enqueue_dialog_open(op: Callable[[], None]) -> None:
    global _DIALOG_OPENING
    _PENDING_DIALOG_OPS.append(op)
    if _DIALOG_OPENING:
        return
    _DIALOG_OPENING = True
    _drain_dialog_queue()


def _drain_dialog_queue() -> None:
    global _DIALOG_OPENING
    # C++-deleted dialogs can leave stale Python refs and block the queue forever.
    alive: list[QWidget] = []
    for x in _ACTIVE_MESSAGE_BOXES:
        try:
            _ = x.isVisible()
        except RuntimeError:
            continue
        alive.append(x)
    _ACTIVE_MESSAGE_BOXES[:] = alive
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
    fly_message_async(
        parent,
        title,
        text,
        single_button=True,
        window_modal=True,
        icon=QMessageBox.Icon.Warning,
    )


def fly_critical(parent: QWidget | None, title: str, text: str) -> None:
    fly_message_async(
        parent,
        title,
        text,
        single_button=True,
        window_modal=True,
        icon=QMessageBox.Icon.Critical,
    )


def fly_message_async(
    parent: QWidget | None,
    title: str,
    text: str,
    *,
    single_button: bool = True,
    window_modal: bool = False,
    icon: QMessageBox.Icon = QMessageBox.Icon.Information,
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
        w = QMessageBox(box_parent)
        _configure_native_message_box(
            w,
            title=title,
            text=text,
            icon=icon,
            single_button=single_button,
        )
        # Must match QDialog.open(): window-modal over parent. ApplicationModal here
        # conflicts with open() and can prevent native QMessageBox from appearing.
        w.setWindowModality(
            Qt.WindowModality.WindowModal if window_modal else Qt.WindowModality.NonModal
        )
        w.setModal(bool(window_modal))
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
        if not w.isVisible():
            w.show()
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
        w = QMessageBox(box_parent)
        _configure_native_question_box(
            w,
            title=title,
            text=text,
            yes_text=yes_text,
            no_text=no_text,
        )
        w.setWindowModality(Qt.WindowModality.WindowModal)
        w.setModal(True)
        out = {"accepted": False}
        loop = QEventLoop()

        def _done(code: int) -> None:
            out["accepted"] = _native_question_accepted(code)
            loop.quit()

        w.finished.connect(_done)
        w.open()
        if not w.isVisible():
            w.show()
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
        w = QMessageBox(box_parent)
        _configure_native_question_box(
            w,
            title=title,
            text=text,
            yes_text=yes_text,
            no_text=no_text,
        )
        w.setWindowModality(
            Qt.WindowModality.WindowModal if window_modal else Qt.WindowModality.NonModal
        )
        w.setModal(bool(window_modal))
        _attach_message_box_debug_watchers(w, parent=parent, title=title, tag="fly_question_async")

        top = _normalize_parent(parent)
        if window_modal and top is not None and not top.isEnabled():
            top.setEnabled(True)

        _ACTIVE_MESSAGE_BOXES.append(w)

        def _on_finished(code: int) -> None:
            accepted = _native_question_accepted(code)
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
        if not w.isVisible():
            w.show()
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
