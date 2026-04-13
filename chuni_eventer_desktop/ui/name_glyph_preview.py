from __future__ import annotations

from PyQt6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, FluentIcon, TransparentToolButton
from qfluentwidgets.common.screen import getCurrentScreenGeometry


def _is_cp932_char(ch: str) -> bool:
    try:
        ch.encode("cp932")
        return True
    except UnicodeEncodeError:
        return False


def _preview_text(src: str) -> tuple[str, str]:
    shown = "".join(ch for ch in src if _is_cp932_char(ch))
    removed = "".join(ch for ch in src if not _is_cp932_char(ch))
    if not removed:
        msg = f"预览（可显示）:\n{shown}"
    else:
        uniq_removed = "".join(dict.fromkeys(removed))
        msg = (
            f"预览（可显示）:\n{shown}\n\n"
            f"不可显示字符已被过滤:\n{uniq_removed}"
        )
    return shown, msg


class _GlyphPreviewPopup(QWidget):
    """圆角卡片预览；独立顶层窗口，悬停出现，指针离开整窗后由外层计时隐藏。"""

    _RADIUS = 10
    _ANCHOR_GAP = 6
    _SCREEN_MARGIN = 4

    pointer_entered = pyqtSignal()
    pointer_left = pyqtSignal()

    def __init__(self) -> None:
        # 无 parent：独立窗口，不受父对话框裁剪；Tool 便于叠在当前应用界面之上
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 14)
        outer.setSpacing(0)

        self._card = CardWidget(self)
        self._card.setBorderRadius(self._RADIUS)
        self._card.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._card.setMouseTracking(True)
        inner = QVBoxLayout(self._card)
        inner.setContentsMargins(14, 12, 14, 12)
        self._label = BodyLabel(self._card)
        self._label.setWordWrap(True)
        self._label.setMinimumWidth(220)
        self._label.setMaximumWidth(380)
        self._label.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._label.setMouseTracking(True)
        inner.addWidget(self._label)
        outer.addWidget(self._card)

        sh = QGraphicsDropShadowEffect(self._card)
        sh.setBlurRadius(28)
        sh.setOffset(0, 6)
        sh.setColor(QColor(0, 0, 0, 72))
        self._card.setGraphicsEffect(sh)

    def enterEvent(self, event) -> None:
        self.pointer_entered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.pointer_left.emit()
        super().leaveEvent(event)

    def set_preview_text(self, text: str) -> None:
        self._label.setText(text)
        self.adjustSize()

    def show_near(self, anchor: QWidget, text: str) -> None:
        self._label.setText(text)
        self.adjustSize()
        self.place_beside_anchor(anchor)
        self.show()
        self.raise_()

    def place_beside_anchor(self, anchor: QWidget) -> None:
        """优先在图标右侧，不够放则左侧，再不行则紧贴图标下缘。"""
        self.adjustSize()
        ar = QRect(anchor.mapToGlobal(QPoint(0, 0)), anchor.size())
        scr = getCurrentScreenGeometry()
        g = self._ANCHOR_GAP
        m = self._SCREEN_MARGIN
        w, h = self.width(), self.height()

        x = ar.right() + g
        y = ar.top()
        if x + w > scr.right() - m:
            x = ar.left() - w - g
        if x < scr.left() + m:
            x = ar.left()
            y = ar.bottom() + g
        if x + w > scr.right() - m:
            x = max(scr.left() + m, scr.right() - m - w)

        if y + h > scr.bottom() - m:
            y = max(scr.top() + m, scr.bottom() - m - h)
        if y < scr.top() + m:
            y = scr.top() + m

        self.move(x, y)


class NameGlyphPreviewRow(QWidget):
    """一行：输入框 + 搜索图标；悬停在图标上显示字库预览，移开即消失。"""

    _HIDE_MS = 220

    def __init__(self, edit: QLineEdit, *, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._edit = edit
        self._btn = TransparentToolButton(FluentIcon.SEARCH, self)
        self._btn.setToolTip("")
        self._btn.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._btn.installEventFilter(self)

        self._popup = _GlyphPreviewPopup()
        self._popup.pointer_entered.connect(self._cancel_hide_timer)
        self._popup.pointer_left.connect(self._schedule_hide_popup)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._popup.hide)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(edit, stretch=1)
        row.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignVCenter)
        edit.textChanged.connect(lambda _: self._refresh_popup_if_open())
        self._sync_btn_size()

    def _sync_btn_size(self) -> None:
        h = self._edit.height()
        if h <= 0:
            h = max(self._edit.sizeHint().height(), self._edit.minimumSizeHint().height())
        self._btn.setFixedSize(h, h)
        side = max(14, min(18, int(round(h * 0.52))))
        self._btn.setIconSize(QSize(side, side))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_btn_size()

    def _preview_message(self) -> str:
        _, msg = _preview_text((self._edit.text() or "").strip())
        return msg

    def _cancel_hide_timer(self) -> None:
        self._hide_timer.stop()

    def _schedule_hide_popup(self) -> None:
        self._hide_timer.start(self._HIDE_MS)

    def _show_hover_popup(self) -> None:
        self._cancel_hide_timer()
        if self._popup.isVisible():
            self._popup.set_preview_text(self._preview_message())
            self._popup.place_beside_anchor(self._btn)
            self._popup.raise_()
            return
        self._popup.show_near(self._btn, self._preview_message())

    def _refresh_popup_if_open(self) -> None:
        if self._popup.isVisible():
            self._popup.set_preview_text(self._preview_message())
            self._popup.place_beside_anchor(self._btn)

    def eventFilter(self, obj: QWidget | None, event: QEvent | None) -> bool:
        if obj is self._btn and event is not None:
            if event.type() == QEvent.Type.Enter:
                self._show_hover_popup()
            elif event.type() == QEvent.Type.Leave:
                self._schedule_hide_popup()
        return super().eventFilter(obj, event)


def wrap_name_input_with_preview(edit: QLineEdit, *, parent: QWidget | None = None) -> QWidget:
    return NameGlyphPreviewRow(edit, parent=parent or edit.parentWidget())
