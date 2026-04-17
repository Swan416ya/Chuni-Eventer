from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, CardWidget, ComboBox as FluentComboBox, PrimaryPushButton, PushButton

from ..acus_scan import StageItem, scan_stages
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins


class MusicStageSelectDialog(FluentCaptionDialog):
    def __init__(self, *, acus_root: Path, current_stage_id: int | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("修改歌曲背景")
        self.setModal(True)
        self.resize(520, 240)
        self._stage_id: int | None = None
        self._stage_str: str = ""

        self._items: list[StageItem] = scan_stages(acus_root)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        hint = BodyLabel("选择 ACUS 内已有的 Stage，确认后会回写 Music.xml 的 stageName。")
        hint.setWordWrap(True)
        self._combo = FluentComboBox(self)
        for it in self._items:
            self._combo.addItem(f"{it.name.id} · {it.name.str}", None, it.name.id)
        if self._items:
            idx = 0
            if current_stage_id is not None:
                for i, it in enumerate(self._items):
                    if it.name.id == current_stage_id:
                        idx = i
                        break
            self._combo.setCurrentIndex(idx)
        cly.addWidget(hint)
        cly.addWidget(self._combo)

        ok = PrimaryPushButton("确定", self)
        cancel = PushButton("取消", self)
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        idx = self._combo.currentIndex()
        if idx < 0 or idx >= len(self._items):
            self.reject()
            return
        it = self._items[idx]
        self._stage_id = it.name.id
        self._stage_str = it.name.str
        self.accept()

    @property
    def selected_stage_id(self) -> int | None:
        return self._stage_id

    @property
    def selected_stage_str(self) -> str:
        return self._stage_str

