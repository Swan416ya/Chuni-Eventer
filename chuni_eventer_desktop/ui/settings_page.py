from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import PrimaryPushButton, ScrollArea, SegmentedWidget, SubtitleLabel

from .fluent_scroll import apply_fluent_transparent_panel, apply_fluent_transparent_scroll

from ..acus_workspace import AcusConfig
from ..game_data_index import GameDataIndex
from .save_patch_dialog import SavePatchPanel
from .settings_about_panel import SettingsAboutPanel
from .game_data_settings_panel import GameDataSettingsPanel
from .settings_dialog import SettingsExperimentalPanel
from .tools_settings_panel import ToolsSettingsPanel


def _scroll_wrap(inner: QWidget) -> ScrollArea:
    apply_fluent_transparent_panel(inner)
    scroll = ScrollArea()
    scroll.setWidget(inner)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    apply_fluent_transparent_scroll(scroll)
    return scroll


class SettingsPage(QWidget):
    """主窗口内设置页：关于 / 游戏数据 / 外部工具 / 存档编辑器 / 实验性功能。"""

    _ROUTE_INDEX: dict[str, int] = {
        "about": 0,
        "game_data": 1,
        "tools": 2,
        "save_patch": 3,
        "experimental": 4,
    }

    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        on_settings_saved: Callable[[], None] | None = None,
        get_game_index: Callable[[], GameDataIndex | None] | None = None,
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        apply_fluent_transparent_panel(self)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 8, 24, 16)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("设置", self))
        header.addStretch(1)
        root.addLayout(header)

        self._seg = SegmentedWidget(self)
        self._seg.addItem("about", "关于")
        self._seg.addItem("game_data", "游戏数据")
        self._seg.addItem("tools", "外部工具")
        self._seg.addItem("save_patch", "存档编辑器")
        self._seg.addItem("experimental", "实验性功能")
        root.addWidget(self._seg)

        self._stack = QStackedWidget(self)
        self._about = SettingsAboutPanel(parent=self)
        self._game_data = GameDataSettingsPanel(
            cfg=cfg,
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            get_game_index=get_game_index or (lambda: None),
            on_request_game_rescan=on_request_game_rescan,
            parent=self,
        )
        self._tools = ToolsSettingsPanel(cfg=cfg, parent=self)
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
        self._stack.addWidget(_scroll_wrap(self._game_data))
        self._stack.addWidget(_scroll_wrap(self._tools))
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
        self._save_bar.setVisible(route_key in ("game_data", "tools", "experimental"))
        if route_key == "about":
            self._about.check_for_updates()
        if route_key == "game_data":
            self._game_data.refresh_index_display()
        if route_key == "tools":
            self._tools.refresh_status()

    def _on_save_clicked(self) -> None:
        self._experimental.apply_fields()
        tools_ok = self._tools.apply_fields()
        game_data_ok = self._game_data.apply()
        if tools_ok and game_data_ok and self._on_settings_saved is not None:
            self._on_settings_saved()

    def show_save_patch_tab(self) -> None:
        self._seg.setCurrentItem("save_patch")

    def show_tools_tab(self) -> None:
        self._seg.setCurrentItem("tools")

    def refresh_game_data_view(self) -> None:
        self._game_data.refresh_index_display()
