from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QDialog, QGridLayout, QSizePolicy, QToolButton, QVBoxLayout

from qfluentwidgets import BodyLabel, PushButton


def _logo_path(filename: str) -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "logo" / filename


# 按钮为横向长方形：宽:高 = 2.5:1
_BTN_H = 44
_BTN_W = int(round(_BTN_H * 2.5))


class MusicAddActionsDialog(QDialog):
    """乐曲页「新增」：四个图标入口（两行 × 每行两个，2.5:1 矩形按钮）。"""

    def __init__(self, *, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新增 — 歌曲")
        self.setModal(True)
        self._action: str | None = None

        hint = BodyLabel("请选择操作：")
        hint.setWordWrap(True)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setContentsMargins(0, 0, 0, 0)

        # 图标区域略小于按钮，留出边距
        icon_sz = QSize(_BTN_W - 12, _BTN_H - 8)

        def mk(fname: str, tip: str, *, enabled: bool, act: str) -> QToolButton:
            b = QToolButton(self)
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

        # 第一行：课题称号、Swan
        grid.addWidget(mk("add_trophy.jpg", "增加课题称号（奖杯 XML）", enabled=True, act="trophy"), 0, 0)
        grid.addWidget(mk("SwanSite.png", "从 Swan 站下载铺面", enabled=True, act="swan"), 0, 1)
        # 第二行：pjsk、pgko（未实现）
        grid.addWidget(mk("pjsk.png", "从 Project SEKAI 获取（尚未支持）", enabled=False, act="pjsk"), 1, 0)
        grid.addWidget(mk("pgko.jpg", "从 pgko 获取（尚未支持）", enabled=False, act="pgko"), 1, 1)

        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(16)
        lay.addWidget(hint)
        lay.addLayout(grid)
        lay.addStretch(1)
        lay.addWidget(cancel)

        self.setMinimumWidth(_BTN_W * 2 + 14 + 40)

    def _pick(self, act: str) -> None:
        self._action = act
        self.accept()

    def selected_action(self) -> str | None:
        return self._action
