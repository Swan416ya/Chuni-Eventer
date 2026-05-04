from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QVBoxLayout

from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .system_voice_page import SystemVoicePackPage


class SystemVoicePackDialog(FluentCaptionDialog):
    """系统语音打包向导（嵌入 SystemVoicePackPage）。"""

    packed = pyqtSignal()

    def __init__(
        self,
        *,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        get_game_root: Callable[[], str],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("系统语音打包")
        self.setModal(True)
        self.resize(980, 720)

        self._page = SystemVoicePackPage(
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            get_game_root=get_game_root,
            parent=self,
        )
        self._page.packed.connect(self.packed.emit)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(0)
        lay.addWidget(self._page, stretch=1)
