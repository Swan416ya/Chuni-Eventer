from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon,
    MSFluentWindow,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
)

from ..acus_workspace import AcusConfig, ensure_acus_layout
from ..dds_quicktex import quicktex_available
from .manager_widget import ManagerWidget
from .settings_dialog import SettingsDialog
from .chara_add_dialog import CharaAddDialog
from .map_add_dialog import MapAddDialog, RewardCreateDialog, ensure_reward_xml, reward_dialog_bundle
from .nameplate_add_dialog import NamePlateAddDialog
from .trophy_add_dialog import TrophyAddDialog
from .music_trophy_dialog import MusicTrophyDialog
from .save_patch_dialog import SavePatchDialog
from .event_add_dialog import EventAddDialog
from .fluent_dialogs import fly_message


class MainWindow(MSFluentWindow):
    """主窗口：Fluent 底栏导航 + 单一内容区（ACUS 管理）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Chuni Eventer")
        self.resize(1160, 720)

        self._acus_root = ensure_acus_layout()
        self._cfg = AcusConfig.load()

        self._workspace = QWidget()
        self._workspace.setObjectName("acusWorkspace")
        wlay = QVBoxLayout(self._workspace)
        wlay.setContentsMargins(24, 8, 24, 16)
        wlay.setSpacing(12)

        header = QHBoxLayout()
        self._title_lbl = SubtitleLabel("歌曲")
        self._search = SearchLineEdit()
        self._search.setPlaceholderText("搜索乐曲、艺术家、流派…")
        self._search.setFixedWidth(300)
        self._refresh_btn = PushButton("刷新")
        self._refresh_btn.clicked.connect(self._on_refresh)
        self._add_btn = PrimaryPushButton("新增")
        self._add_btn.clicked.connect(self._on_add)
        header.addWidget(self._title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._search, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._refresh_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        wlay.addLayout(header)

        self._manager = ManagerWidget(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path_or_none,
            embedded=True,
        )
        self._search.textChanged.connect(self._manager.set_search_text)
        wlay.addWidget(self._manager, stretch=1)

        self.stackedWidget.addWidget(self._workspace)

        self._nav_specs: list[tuple[str, FluentIcon, str, str, str]] = [
            ("nav_chara", FluentIcon.PEOPLE, "角色", "Chara", "角色"),
            ("nav_map", FluentIcon.GAME, "地图", "Map", "地图"),
            ("nav_event", FluentIcon.CALENDAR, "事件", "Event", "事件"),
            ("nav_music", FluentIcon.MUSIC, "歌曲", "Music", "歌曲"),
            ("nav_trophy", FluentIcon.CERTIFICATE, "称号", "Trophy", "称号"),
            ("nav_nameplate", FluentIcon.EMOJI_TAB_SYMBOLS, "名牌", "NamePlate", "名牌"),
            ("nav_reward", FluentIcon.SHOPPING_CART, "奖励", "Reward", "奖励"),
        ]
        for route_key, icon, text, kind, title in self._nav_specs:
            self.navigationInterface.addItem(
                routeKey=route_key,
                icon=icon,
                text=text,
                onClick=lambda _=False, k=kind, t=title, r=route_key: self._select_category(r, k, t),
                position=NavigationItemPosition.TOP,
            )

        self.navigationInterface.addItem(
            routeKey="nav_save_patch",
            icon=FluentIcon.SAVE,
            text="存档装备",
            onClick=self._open_save_patch,
            position=NavigationItemPosition.BOTTOM,
            selectable=False,
        )
        self.navigationInterface.addItem(
            routeKey="nav_settings",
            icon=FluentIcon.SETTING,
            text="设置",
            onClick=self._open_settings,
            position=NavigationItemPosition.BOTTOM,
            selectable=False,
        )

        self.switchTo(self._workspace)
        self._current_category_index = 3
        self.navigationInterface.setCurrentItem("nav_music")
        self._apply_category("Music", "歌曲")

    def _get_tool_path_or_none(self) -> Path | None:
        raw = (self._cfg.compressonatorcli_path or "").strip()
        if not raw:
            return None
        p = Path(raw).expanduser()
        try:
            p = p.resolve(strict=False)
        except OSError:
            return None
        return p if p.is_file() else None

    def _select_category(self, route_key: str, kind: str, title: str) -> None:
        self.switchTo(self._workspace)
        self.navigationInterface.setCurrentItem(route_key)
        for i, (rk, *_rest) in enumerate(self._nav_specs):
            if rk == route_key:
                self._current_category_index = i
                break
        self._apply_category(kind, title)

    def _apply_category(self, kind: str, title: str) -> None:
        self._search.setText("")
        self._title_lbl.setText(title)
        placeholders = {
            "Music": "搜索乐曲、艺术家、流派…",
            "Chara": "搜索角色…",
            "Map": "搜索地图…",
            "Event": "搜索事件…",
            "Trophy": "搜索称号…",
            "NamePlate": "搜索名牌…",
            "Reward": "搜索奖励…",
        }
        self._search.setPlaceholderText(placeholders.get(kind, "搜索当前列表…"))
        self._manager.set_kind(kind)

    def _open_save_patch(self) -> None:
        dlg = SavePatchDialog(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path_or_none,
            parent=self,
        )
        dlg.exec()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(cfg=self._cfg, parent=self)
        if dlg.exec() == dlg.DialogCode.Accepted:
            dlg.apply()
            fly_message(self, "已保存", "设置已保存。")
            self._on_refresh()

    def _on_refresh(self) -> None:
        self._manager.reload()

    def _on_add(self) -> None:
        idx = self._current_category_index
        if idx == 6:
            music_r, chara_r, trophy_r, np_r, default_id = reward_dialog_bundle(self._acus_root)
            dlg = RewardCreateDialog(
                default_id=default_id,
                music_refs=music_r,
                chara_refs=chara_r,
                trophy_refs=trophy_r,
                nameplate_refs=np_r,
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_cell is not None:
                ensure_reward_xml(self._acus_root, dlg.result_cell)
                self._on_refresh()
            return

        if idx == 3:
            dlg = MusicTrophyDialog(acus_root=self._acus_root, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        if idx == 2:
            dlg = EventAddDialog(
                acus_root=self._acus_root,
                tool_path=self._get_tool_path_or_none(),
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        tool = self._get_tool_path_or_none()
        if tool is None and not quicktex_available():
            QMessageBox.critical(
                self,
                "无法生成 DDS",
                "请任选其一：\n"
                "• 运行 pip install quicktex（推荐，可不装 compressonator）\n"
                "• 或在【设置】里配置 compressonatorcli 可执行文件路径",
            )
            return

        if idx == 0:
            dlg = CharaAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif idx == 1:
            dlg = MapAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif idx == 4:
            dlg = TrophyAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif idx == 5:
            dlg = NamePlateAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        else:
            QMessageBox.information(
                self,
                "未实现",
                "当前已实现【新增角色】【新增地图】【新增歌曲课题称号】【新增称号】【新增名牌】【新增奖励】。"
                "DDSImage 请直接在 ACUS 目录维护或用其它工具。",
            )
