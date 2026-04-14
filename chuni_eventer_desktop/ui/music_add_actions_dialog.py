from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import PushButton, SubtitleLabel

def _logo_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "logo" / filename


_BTN_H = 44
_BTN_W = int(round(_BTN_H * 2.5))


class MusicSheetChannelsDialog(QDialog):
    """
    乐曲页「新增」：选择自制谱下载渠道（Swan / pgko）。
    """

    def __init__(self, *, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("自制谱下载渠道")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(420, 280)

        self._action: str | None = None

        card = QWidget(self)
        self._card = card
        card.setObjectName("channelDialogCard")
        card.setStyleSheet(
            "#channelDialogCard{"
            "background-color: rgba(255,255,255,190);"
            "border: 1px solid rgba(255,255,255,70);"
            "border-radius: 14px;"
            "}"
        )
        cly = QVBoxLayout(card)
        cly.setContentsMargins(24, 22, 24, 20)
        cly.setSpacing(18)

        hint = SubtitleLabel("请选择自制谱下载渠道", card)
        hint.setWordWrap(True)

        row = QHBoxLayout()
        row.setSpacing(12)
        row.setContentsMargins(0, 0, 0, 0)
        icon_sz = QSize(_BTN_W - 12, _BTN_H - 8)

        def mk(fname: str, tip: str, *, enabled: bool, act: str) -> QToolButton:
            b = QToolButton(card)
            b.setToolTip(tip)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            p = _logo_path(fname)
            if p.is_file():
                b.setIcon(QIcon(str(p)))
            b.setIconSize(icon_sz)
            b.setFixedSize(_BTN_W, _BTN_H)
            b.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            b.setEnabled(enabled)
            if enabled:
                b.clicked.connect(lambda _=False, a=act: self._pick(a))
            return b

        row.addWidget(mk("SwanSite.png", "从 Swan 站获取自制谱", enabled=True, act="swan"))
        row.addWidget(
            mk(
                "pgko.jpg",
                "从 pgko.dev 获取自制谱",
                enabled=True,
                act="pgko",
            )
        )

        cly.addWidget(hint)
        cly.addLayout(row)

        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        self._close_btn = PushButton("关闭", card)
        self._close_btn.setToolTip(
            "左键：关闭。右键：从本地压缩包导入（与 Swan 下载后相同的解压与落盘逻辑）。"
        )
        self._close_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self._close_btn.clicked.connect(self.reject)
        self._close_btn.installEventFilter(self)
        foot.addWidget(self._close_btn, stretch=1)
        cly.addLayout(foot)

        sh = QGraphicsDropShadowEffect(card)
        sh.setBlurRadius(36)
        sh.setOffset(0, 10)
        sh.setColor(QColor(0, 0, 0, 85))
        card.setGraphicsEffect(sh)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(card, stretch=1)

        min_w = _BTN_W * 2 + 12 * 1 + 48
        card.setMinimumWidth(min_w)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        win = self.parentWidget()
        if win is not None:
            top = win.window()
            self.adjustSize()
            g = top.frameGeometry()
            sz = self.size()
            x = g.x() + max(0, (g.width() - sz.width()) // 2)
            y = g.y() + max(0, (g.height() - sz.height()) // 2)
            self.move(x, y)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def eventFilter(self, obj: QWidget | None, event: QEvent | None) -> bool:
        if obj is self._close_btn and event is not None and event.type() == QEvent.Type.MouseButtonPress:
            me = event
            if isinstance(me, QMouseEvent) and me.button() == Qt.MouseButton.RightButton:
                self._pick("local_zip")
                return True
        return super().eventFilter(obj, event)

    def _pick(self, act: str) -> None:
        self._action = act
        self.accept()

    def selected_action(self) -> str | None:
        return self._action
