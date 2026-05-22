"""DDS 预览控件（与 ACUS 浏览器角色页共用布局）。"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from qfluentwidgets import isDarkTheme


class WidthScaledPreviewLabel(QLabel):
    """随容器变宽等比缩放，最大宽高框内显示。"""

    _DISPLAY_MAX_W = 400
    _DISPLAY_MAX_H = 340

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._source: QPixmap | None = None
        border = "#4B5563" if isDarkTheme() else "#D1D5DB"
        self.setStyleSheet(f"border: 1px solid {border}; border-radius: 4px;")

    def clear_source(self) -> None:
        self._source = None
        super().setPixmap(QPixmap())
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)

    def setSourcePixmap(self, pm: QPixmap | None) -> None:
        self._source = pm if pm is not None and not pm.isNull() else None
        self._apply_scale()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_scale()

    def _apply_scale(self) -> None:
        mw, mh = self._DISPLAY_MAX_W, self._DISPLAY_MAX_H
        if self._source is None or self._source.isNull():
            super().setPixmap(QPixmap())
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            return
        w_avail = self.width()
        if w_avail <= 1:
            par = self.parentWidget()
            guess = (par.width() * 4 // 5) if par is not None and par.width() > 0 else mw
            w_avail = max(120, min(mw, guess))
        box_w = min(max(w_avail, 48), mw)
        scaled = self._source.scaled(
            QSize(box_w, mh),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)


class CharaDdsPreviewWidget(QWidget):
    """左：ddsFile0；右：ddsFile1 / ddsFile2 上下等高，总高与左侧一致。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pm: tuple[QPixmap | None, QPixmap | None, QPixmap | None] = (None, None, None)
        self._left = QLabel()
        self._r1 = QLabel()
        self._r2 = QLabel()
        border = "#4B5563" if isDarkTheme() else "#D1D5DB"
        for lb in (self._left, self._r1, self._r2):
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet(f"border: 1px solid {border}; border-radius: 4px;")
        self._right_wrap = QWidget()
        rv = QVBoxLayout(self._right_wrap)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        rv.addWidget(self._r1, 1)
        rv.addWidget(self._r2, 1)
        lay = QHBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._left, 0, Qt.AlignmentFlag.AlignTop)
        lay.addWidget(self._right_wrap, 0, Qt.AlignmentFlag.AlignTop)

    def clear(self) -> None:
        self._pm = (None, None, None)
        for lb in (self._left, self._r1, self._r2):
            lb.clear()
            lb.setText("")
        self.setMinimumHeight(0)

    def set_pixmaps(self, p0: QPixmap | None, p1: QPixmap | None, p2: QPixmap | None) -> None:
        self._pm = (p0, p1, p2)
        self._relayout()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _fit_in(self, pm: QPixmap | None, rw: int, rh: int) -> QPixmap:
        if pm is None or pm.isNull() or rw < 1 or rh < 1:
            return QPixmap()
        return pm.scaled(
            rw,
            rh,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def _relayout(self) -> None:
        W = self.width()
        if W < 32:
            return
        lay = self.layout()
        gap = lay.spacing() if lay is not None else 8
        col_w = max(1, (W - gap) // 2)
        p0, p1, p2 = self._pm
        if p0 is not None and not p0.isNull():
            s0 = p0.scaledToWidth(col_w, Qt.TransformationMode.SmoothTransformation)
            h = max(s0.height(), 1)
        else:
            s0 = QPixmap()
            h = 160
        h1 = h // 2
        h2 = h - h1
        s1 = self._fit_in(p1, col_w, h1)
        s2 = self._fit_in(p2, col_w, h2)
        self._left.setPixmap(s0)
        self._left.setFixedSize(col_w, h)
        self._right_wrap.setFixedSize(col_w, h)
        self._r1.setPixmap(s1)
        self._r1.setFixedSize(col_w, h1)
        self._r2.setPixmap(s2)
        self._r2.setFixedSize(col_w, h2)
        self.setMinimumHeight(h)
