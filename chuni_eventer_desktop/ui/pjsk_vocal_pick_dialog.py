"""
PJSK 同一乐曲多个人声版本时，由用户选择要下载的 long 音频（对齐 SusPatcher 的 chartvocal 选择）。
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton

from ..pjsk_sheet_client import PjskVocalRow


class PjskVocalPickDialog(QDialog):
    """
    返回码：
    - Accepted + skip_audio=True → 不下载音频，其余照常
    - Accepted + skip_audio=False + selected_row → 下载该 assetbundle
    - Rejected → 取消整次缓存（不开始下载）
    """

    def __init__(self, vocals: list[PjskVocalRow], *, parent=None) -> None:
        super().__init__(parent=parent)
        self.setModal(True)
        self.setWindowTitle("选择人声 / 伴奏版本")
        self.resize(520, 360)
        self.skip_audio = False
        self.selected: PjskVocalRow | None = None

        tip = BodyLabel(
            "该曲目在 PJSK 中有多个音频版本（不同演唱组合、セカイ版、虚拟歌手版等）。"
            "列表中会尽量显示角色名与官方 caption（来自 musicVocals）；"
            "鼠标悬停一行可查看资源包名 assetbundleName。"
            "请选择要下载的一条完整音频，或「不下载音频」仅拉取封面与谱面。"
        )
        tip.setWordWrap(True)

        self._list = QListWidget(self)
        for v in vocals:
            it = QListWidgetItem(v.caption)
            it.setData(Qt.ItemDataRole.UserRole, v)
            it.setToolTip(v.tooltip if v.tooltip else v.assetbundle_name)
            self._list.addItem(it)
        if self._list.count():
            self._list.setCurrentRow(0)

        ok_btn = PrimaryPushButton("下载所选版本", self)
        ok_btn.clicked.connect(self._on_ok)
        skip_btn = PushButton("不下载音频", self)
        skip_btn.clicked.connect(self._on_skip)
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(ok_btn)
        row.addWidget(skip_btn)
        row.addStretch(1)
        row.addWidget(cancel_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(tip)
        root.addWidget(self._list, stretch=1)
        root.addLayout(row)

    def _on_ok(self) -> None:
        it = self._list.currentItem()
        if it is None:
            return
        v = it.data(Qt.ItemDataRole.UserRole)
        if not isinstance(v, PjskVocalRow):
            return
        self.skip_audio = False
        self.selected = v
        self.accept()

    def _on_skip(self) -> None:
        self.skip_audio = True
        self.selected = None
        self.accept()
