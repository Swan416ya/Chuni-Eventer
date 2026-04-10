from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon,
    MSFluentWindow,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SubtitleLabel,
)

from ..acus_workspace import AcusConfig, ensure_acus_layout, resolve_compressonatorcli_path
from ..version import APP_VERSION
from ..game_data_index import load_cached_game_index
from .index_progress import run_rebuild_game_index_with_progress
from ..sheet_install import install_zip_to_acus
from ..dds_quicktex import quicktex_available
from .manager_widget import ManagerWidget
from .settings_dialog import SettingsDialog
from .chara_add_dialog import CharaAddDialog
from .map_add_dialog import MapAddDialog, RewardCreateDialog, ensure_reward_xml, reward_dialog_bundle
from .nameplate_add_dialog import NamePlateAddDialog
from .trophy_add_dialog import TrophyAddDialog
from .music_add_actions_dialog import MusicSheetChannelsDialog
from .pgko_sheet_download_dialog import PgkoSheetDownloadDialog
from .swan_sheet_download_dialog import SwanSheetDownloadDialog
from .save_patch_dialog import SavePatchDialog
from .event_add_dialog import EventAddDialog
from .quest_add_dialog import QuestAddDialog
from .mapbonus_dialogs import MapBonusEditDialog
from .fluent_dialogs import fly_critical, fly_message


class MainWindow(MSFluentWindow):
    """主窗口：Fluent 底栏导航 + 单一内容区（ACUS 管理）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Chuni Eventer v{APP_VERSION}")
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
        self._game_music_browser_btn = PushButton("游戏乐曲资源…")
        self._game_music_browser_btn.setToolTip(
            "只读浏览游戏目录内已扫描数据包中的全部乐曲（含版本标签、流派）"
        )
        self._game_music_browser_btn.setVisible(False)
        self._game_music_browser_btn.clicked.connect(self._on_game_music_browser)
        self._refresh_btn = PushButton("刷新")
        self._refresh_btn.clicked.connect(self._on_refresh)
        self._add_btn = PrimaryPushButton("新增")
        self._add_btn.clicked.connect(self._on_add)
        header.addWidget(self._title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._search, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._game_music_browser_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._refresh_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._add_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        wlay.addLayout(header)

        self._manager = ManagerWidget(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path_or_none,
            get_game_index=self._resolve_game_index,
            get_game_root=lambda: self._cfg.game_root or "",
            embedded=True,
        )
        self._search.textChanged.connect(self._manager.set_search_text)
        wlay.addWidget(self._manager, stretch=1)

        self.stackedWidget.addWidget(self._workspace)

        self._nav_specs: list[tuple[str, FluentIcon, str, str, str]] = [
            ("nav_chara", FluentIcon.PEOPLE, "角色", "Chara", "角色"),
            ("nav_map", FluentIcon.GAME, "地图", "Map", "地图"),
            ("nav_event", FluentIcon.CALENDAR, "事件", "Event", "事件"),
            ("nav_quest", FluentIcon.DOCUMENT, "任务", "Quest", "任务"),
            ("nav_music", FluentIcon.MUSIC, "歌曲", "Music", "歌曲"),
            ("nav_trophy", FluentIcon.CERTIFICATE, "称号", "Trophy", "称号"),
            ("nav_nameplate", FluentIcon.EMOJI_TAB_SYMBOLS, "名牌", "NamePlate", "名牌"),
            ("nav_reward", FluentIcon.SHOPPING_CART, "奖励", "Reward", "奖励"),
            ("nav_mapbonus", FluentIcon.DOCUMENT, "加成", "MapBonus", "加成"),
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
        self._current_category_index = 4
        self.navigationInterface.setCurrentItem("nav_music")
        self._apply_category("Music", "歌曲")

        QTimer.singleShot(0, self._ensure_game_root_first_run)

    def _resolve_game_index(self):
        gr = (self._cfg.game_root or "").strip()
        if not gr:
            return None
        return load_cached_game_index(gr)

    def _ensure_game_root_first_run(self) -> None:
        gr_raw = (self._cfg.game_root or "").strip()
        if gr_raw:
            gr = Path(gr_raw).expanduser()
            if load_cached_game_index(str(gr)) is None:
                _idx, err = run_rebuild_game_index_with_progress(
                    self,
                    game_root=gr,
                    compressonatorcli_path=self._get_tool_path_or_none(),
                )
                if _idx is None and err:
                    fly_critical(
                        self,
                        "游戏索引失败",
                        f"{err}\n可在【设置】中重新选择目录并点击「重新扫描游戏索引」。",
                    )
            return
        picked = QFileDialog.getExistingDirectory(
            self,
            "首次使用：请选择游戏数据目录（含 A001，或为含 A001 / Option\\A001 的安装根目录）",
        )
        if not picked:
            fly_message(
                self,
                "提示",
                "未设置游戏目录时，乐曲/场景/ddsMap 等下拉列表仅包含 ACUS 内已有数据。\n"
                "稍后可打开【设置】填写「游戏数据目录」并扫描。",
            )
            return
        self._cfg.game_root = picked
        self._cfg.save()
        _idx, err = run_rebuild_game_index_with_progress(
            self,
            game_root=Path(picked).expanduser(),
            compressonatorcli_path=self._get_tool_path_or_none(),
        )
        if _idx is None:
            fly_critical(self, "扫描失败", err or "无法建立游戏索引。")
        else:
            fly_message(
                self,
                "索引完成",
                f"已缓存游戏内乐曲 {len(_idx.music)}、场景 {len(_idx.stage)}、"
                f"DDSImage {len(_idx.dds_image)}、ddsMap {len(_idx.dds_map)} 条（仅 ID 与名称）。",
            )

    def _get_tool_path_or_none(self) -> Path | None:
        return resolve_compressonatorcli_path(self._cfg)

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
            "Quest": "搜索任务…",
            "Trophy": "搜索称号…",
            "NamePlate": "搜索名牌…",
            "Reward": "搜索奖励…",
            "MapBonus": "搜索 MapBonus…",
        }
        self._search.setPlaceholderText(placeholders.get(kind, "搜索当前列表…"))
        self._game_music_browser_btn.setVisible(kind == "Music")
        self._manager.set_kind(kind)

    def _on_game_music_browser(self) -> None:
        from .game_music_browser_dialog import GameMusicBrowserDialog

        raw = (self._cfg.game_root or "").strip()
        if not raw:
            fly_message(self, "提示", "请先在【设置】中配置「游戏数据目录」。")
            return
        dlg = GameMusicBrowserDialog(
            game_root=Path(raw).expanduser(),
            get_index=self._resolve_game_index,
            parent=self,
        )
        dlg.exec()

    def _open_save_patch(self) -> None:
        dlg = SavePatchDialog(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path_or_none,
            parent=self,
        )
        dlg.exec()

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            cfg=self._cfg,
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path_or_none,
            parent=self,
        )
        if dlg.exec() == dlg.DialogCode.Accepted:
            dlg.apply()
            fly_message(self, "已保存", "设置已保存。")
            self._on_refresh()

    def _on_refresh(self) -> None:
        self._manager.reload()

    def _on_add(self) -> None:
        idx = self._current_category_index
        kind = self._nav_specs[idx][3] if 0 <= idx < len(self._nav_specs) else ""
        if kind == "Reward":
            gi = self._resolve_game_index()
            music_r, chara_r, trophy_r, np_r, stage_r, default_id = reward_dialog_bundle(
                self._acus_root, game_index=gi
            )
            dlg = RewardCreateDialog(
                default_id=default_id,
                music_refs=music_r,
                chara_refs=chara_r,
                trophy_refs=trophy_r,
                nameplate_refs=np_r,
                stage_refs=stage_r,
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_cell is not None:
                ensure_reward_xml(self._acus_root, dlg.result_cell, gi)
                self._on_refresh()
            return

        if kind == "Music":
            pick = MusicSheetChannelsDialog(parent=self)
            if pick.exec() != pick.DialogCode.Accepted:
                return
            act = pick.selected_action()
            if act == "swan":
                SwanSheetDownloadDialog(acus_root=self._acus_root, parent=self).exec()
                self._on_refresh()
            elif act == "pgko":
                PgkoSheetDownloadDialog(parent=self).exec()
                self._on_refresh()
            elif act == "local_zip":
                path, _ = QFileDialog.getOpenFileName(
                    self,
                    "选择自制谱压缩包",
                    "",
                    "ZIP / TAR / 7z (*.zip *.tar *.tar.gz *.tar.bz2 *.tar.xz *.7z);;所有文件 (*.*)",
                )
                if not path.strip():
                    return
                zp = Path(path).expanduser().resolve()
                try:
                    written = install_zip_to_acus(zp, self._acus_root)
                    fly_message(
                        self,
                        "已导入",
                        f"已写入 {len(written)} 个文件到 ACUS。",
                    )
                except Exception as e:
                    fly_critical(self, "导入失败", str(e))
                self._on_refresh()
            return

        if kind == "Quest":
            dlg = QuestAddDialog(
                acus_root=self._acus_root,
                game_index=self._resolve_game_index(),
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        if kind == "Event":
            dlg = EventAddDialog(
                acus_root=self._acus_root,
                tool_path=self._get_tool_path_or_none(),
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        if kind == "MapBonus":
            dlg = MapBonusEditDialog(acus_root=self._acus_root, game_index=self._resolve_game_index(), parent=self)
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

        if kind == "Chara":
            dlg = CharaAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif kind == "Map":
            dlg = MapAddDialog(
                acus_root=self._acus_root,
                tool_path=tool,
                game_index=self._resolve_game_index(),
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif kind == "Trophy":
            dlg = TrophyAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        elif kind == "NamePlate":
            dlg = NamePlateAddDialog(acus_root=self._acus_root, tool_path=tool, parent=self)
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
        else:
            QMessageBox.information(
                self,
                "未实现",
                "当前已实现【新增角色】【新增地图】【新增事件】【新增任务】【新增歌曲课题称号】【新增称号】【新增名牌】【新增奖励】。"
                "DDSImage 请直接在 ACUS 目录维护或用其它工具。",
            )
