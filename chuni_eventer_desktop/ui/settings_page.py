from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import PrimaryPushButton, ScrollArea, SegmentedWidget, SubtitleLabel

from ..acus_workspace import AcusConfig
from .save_patch_dialog import SavePatchPanel
from .settings_about_panel import SettingsAboutPanel
from .settings_dialog import SettingsExperimentalPanel, SettingsPanel


def _scroll_wrap(inner: QWidget) -> ScrollArea:
    scroll = ScrollArea()
    scroll.setWidget(inner)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(ScrollArea.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    return scroll


class SettingsPage(QWidget):
    """主窗口内设置页：关于 / 常规 / 存档编辑器 / 实验性功能。"""

    _ROUTE_INDEX: dict[str, int] = {
        "about": 0,
        "general": 1,
        "save_patch": 2,
        "experimental": 3,
    }

    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        on_settings_saved: Callable[[], None] | None = None,
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 8, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("设置", self))
        header.addStretch(1)
        root.addLayout(header)

        self._seg = SegmentedWidget(self)
        self._seg.addItem("about", "关于")
        self._seg.addItem("general", "常规")
        self._seg.addItem("save_patch", "存档编辑器")
        self._seg.addItem("experimental", "实验性功能")
        root.addWidget(self._seg)

        self._stack = QStackedWidget(self)
        self._about = SettingsAboutPanel(parent=self)
        self._general = SettingsPanel(
            cfg=cfg,
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            on_request_game_rescan=on_request_game_rescan,
            parent=self,
        )
        self._save_patch = SavePatchPanel(
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            parent=self,
        )
        self._experimental = SettingsExperimentalPanel(
            cfg=cfg,
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            parent=self,
        )
        self._stack.addWidget(_scroll_wrap(self._about))
        self._stack.addWidget(_scroll_wrap(self._general))
        self._stack.addWidget(_scroll_wrap(self._save_patch))
        self._stack.addWidget(_scroll_wrap(self._experimental))
        root.addWidget(self._stack, stretch=1)

        self._on_settings_saved = on_settings_saved
        self._save_bar = QWidget(self)
        save_lay = QHBoxLayout(self._save_bar)
        save_lay.setContentsMargins(0, 0, 0, 0)
        save_lay.addStretch(1)
        save_btn = PrimaryPushButton("保存设置", self._save_bar)
        save_btn.clicked.connect(self._on_save_clicked)
        save_lay.addWidget(save_btn)
        root.addWidget(self._save_bar)

        self._seg.currentItemChanged.connect(self._on_segment_changed)
        self._seg.setCurrentItem("about")
        self._on_segment_changed("about")

    def _on_segment_changed(self, route_key: str) -> None:
        self._stack.setCurrentIndex(self._ROUTE_INDEX.get(route_key, 0))
        self._save_bar.setVisible(route_key in ("general", "experimental"))
        if route_key == "about":
            self._about.check_for_updates()

    def _on_save_clicked(self) -> None:
        self._experimental.apply_fields()
        if self._general.apply() and self._on_settings_saved is not None:
            self._on_settings_saved()

    def show_save_patch_tab(self) -> None:
        self._seg.setCurrentItem("save_patch")
