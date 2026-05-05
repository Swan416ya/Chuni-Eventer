from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QProgressDialog, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (
    FluentIcon,
    MSFluentWindow,
    NavigationItemPosition,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SegmentedWidget,
    SubtitleLabel,
)

from ..acus_workspace import (
    AcusConfig,
    app_cache_dir,
    ensure_acus_layout,
    refresh_chara_works_sorts_with_game,
    resolve_compressonatorcli_path,
)
from ..version import APP_VERSION
from ..game_data_index import GameDataIndex, load_cached_game_index, rebuild_and_save_game_index
from ..sheet_install import install_zip_to_acus, peek_root_readme_from_archive
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
from .stage_add_dialog import StageAddDialog
from .system_voice_pack_dialog import SystemVoicePackDialog
from .fluent_dialogs import (
    fly_critical,
    fly_message,
    fly_message_async,
    fly_warning,
    show_archive_readme_dialog,
    safe_dismiss_modal_progress_dialog,
)
from .nav_icons import (
    SVG_STAGE_BG,
    SVG_CHARA,
    SVG_MAP,
    SVG_MUSIC,
    SVG_NAMEPLATE,
    SVG_TROPHY,
    nav_qicon,
)


_scan_log_logger: logging.Logger | None = None

# 启动窗口高度：在原先 720 基础上为左侧导航多预留约 2 个 Tab 项的垂直空间（Fluent 侧栏单项约 48～56px）。
_DEFAULT_MAIN_WINDOW_WIDTH = 1160
_DEFAULT_MAIN_WINDOW_HEIGHT = 720 + 2 * 52

# 「其他」分段 routeKey -> (ManagerWidget kind, 标题)
_OTHERS_ROUTE_KIND: dict[str, tuple[str, str]] = {
    "event": ("Event", "事件"),
    "quest": ("Quest", "任务"),
    "reward": ("Reward", "奖励"),
    "mapbonus": ("MapBonus", "加成"),
    "sysvoice": ("SystemVoice", "系统语音"),
}


def _scan_logger() -> logging.Logger:
    global _scan_log_logger
    if _scan_log_logger is not None:
        return _scan_log_logger
    logger = logging.getLogger("chuni.index_scan")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        log_dir = app_cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "index_scan.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except Exception:
        # 日志初始化失败不应影响主流程。
        pass
    _scan_log_logger = logger
    return logger


class _GameIndexWorker(QObject):
    finished = pyqtSignal(object, str)
    progress = pyqtSignal(str, int, int)  # msg, cur, total(0=indeterminate)

    def __init__(
        self,
        game_root: Path,
        compressonatorcli_path: Path | None,
        acus_root: Path,
    ) -> None:
        super().__init__()
        self._game_root = game_root
        self._compressonatorcli_path = compressonatorcli_path
        self._acus_root = acus_root

    def run(self) -> None:
        lg = _scan_logger()
        lg.info("scan_start game_root=%s tool=%s", self._game_root, self._compressonatorcli_path)

        def _on_progress(msg: str, cur: int, total: int) -> None:
            lg.info("scan_progress cur=%s total=%s msg=%s", cur, total, msg)
            self.progress.emit(str(msg), int(cur), int(total))

        try:
            idx, err = rebuild_and_save_game_index(
                self._game_root,
                self._compressonatorcli_path,
                progress=_on_progress,
                prewarm_dds_preview=False,
            )
            if isinstance(idx, GameDataIndex):
                _on_progress("正在刷新 ACUS/charaWorks 排序表 XML …", 0, 0)
                try:
                    refresh_chara_works_sorts_with_game(self._acus_root, self._game_root)
                except Exception as e:
                    lg.exception("scan_finish_with_post_step_error game_root=%s", self._game_root)
                    self.finished.emit(None, f"索引已完成，但刷新 charaWorks 失败：{e}")
                    return
            if isinstance(idx, GameDataIndex):
                lg.info(
                    "scan_finish_ok music=%s stage=%s dds_image=%s dds_map=%s",
                    len(idx.music),
                    len(idx.stage),
                    len(idx.dds_image),
                    len(idx.dds_map),
                )
            else:
                lg.warning("scan_finish_failed err=%s", err)
            self.finished.emit(idx, err)
        except Exception:
            lg.exception("scan_crash_unhandled game_root=%s", self._game_root)
            self.finished.emit(None, "扫描线程发生未处理异常，请查看 .cache/logs/index_scan.log")


class MainWindow(MSFluentWindow):
    """主窗口：Fluent 底栏导航 + 单一内容区（ACUS 管理）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Chuni Eventer v{APP_VERSION}")
        self.resize(_DEFAULT_MAIN_WINDOW_WIDTH, _DEFAULT_MAIN_WINDOW_HEIGHT)

        self._cfg = AcusConfig.load()
        self._acus_root = ensure_acus_layout(game_root=self._cfg.game_root or None)
        self._in_others_mode = False

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

        self._primary_body = QWidget(self._workspace)
        pl = QVBoxLayout(self._primary_body)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addWidget(self._manager, stretch=1)

        self._page_others = QWidget(self._workspace)
        ol = QVBoxLayout(self._page_others)
        ol.setContentsMargins(0, 8, 0, 0)
        ol.setSpacing(8)
        self._others_seg = SegmentedWidget(self._page_others)
        self._others_seg.addItem("event", "事件")
        self._others_seg.addItem("quest", "任务")
        self._others_seg.addItem("reward", "奖励")
        self._others_seg.addItem("mapbonus", "加成")
        self._others_seg.addItem("sysvoice", "系统语音")
        self._others_seg.currentItemChanged.connect(self._on_others_segment_changed)
        ol.addWidget(self._others_seg)
        self._others_manager_slot = QWidget(self._page_others)
        self._others_manager_layout = QVBoxLayout(self._others_manager_slot)
        self._others_manager_layout.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(self._others_manager_slot, stretch=1)

        self._content_stack = QStackedWidget(self._workspace)
        self._content_stack.addWidget(self._primary_body)
        self._content_stack.addWidget(self._page_others)
        wlay.addWidget(self._content_stack, stretch=1)

        self.stackedWidget.addWidget(self._workspace)

        self._nav_specs: list[tuple[str, object, str, str, str]] = [
            ("nav_chara", nav_qicon(SVG_CHARA), "角色", "Chara", "角色"),
            ("nav_map", nav_qicon(SVG_MAP), "地图", "Map", "地图"),
            ("nav_music", nav_qicon(SVG_MUSIC), "歌曲", "Music", "歌曲"),
            ("nav_stage", nav_qicon(SVG_STAGE_BG), "背景", "Stage", "背景"),
            ("nav_trophy", nav_qicon(SVG_TROPHY), "称号", "Trophy", "称号"),
            ("nav_nameplate", nav_qicon(SVG_NAMEPLATE), "名牌", "NamePlate", "名牌"),
            ("nav_others", FluentIcon.APPLICATION, "其他", "__Others__", "其他"),
        ]
        for route_key, icon, text, kind, title in self._nav_specs:
            if kind == "__Others__":
                self.navigationInterface.addItem(
                    routeKey=route_key,
                    icon=icon,
                    text=text,
                    onClick=lambda r=route_key: self._enter_others_mode(r),
                    position=NavigationItemPosition.TOP,
                )
                continue
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
        self._current_category_index = 2
        self.navigationInterface.setCurrentItem("nav_music")
        # 延后到事件循环下一轮再扫 ACUS / 建歌曲卡片，让窗口先完成 show()，体感启动更快
        QTimer.singleShot(0, lambda: self._apply_category("Music", "歌曲"))

        self._index_thread: QThread | None = None
        self._index_worker: _GameIndexWorker | None = None
        self._index_progress: QProgressDialog | None = None
        QTimer.singleShot(0, self._ensure_game_index_background)

    def _resolve_game_index(self):
        gr = (self._cfg.game_root or "").strip()
        if not gr:
            return None
        return load_cached_game_index(gr)

    def _ensure_game_index_background(self) -> None:
        gr_raw = (self._cfg.game_root or "").strip()
        if not gr_raw:
            fly_message_async(
                self,
                "提示",
                "未设置游戏目录时，乐曲/场景/ddsMap 等下拉列表仅包含 ACUS 内已有数据。\n"
                "稍后可打开【设置】填写「游戏数据目录」并扫描。",
                single_button=True,
                window_modal=False,
            )
            return

        gr = Path(gr_raw).expanduser()
        if load_cached_game_index(str(gr)) is not None:
            return

        self._start_index_thread(gr)

    def _start_index_thread(self, game_root: Path, compressonatorcli_path: Path | None = None) -> None:
        if self._index_thread is not None:
            _scan_logger().info("scan_skip_already_running game_root=%s", game_root)
            return
        _scan_logger().info("scan_request game_root=%s", game_root)
        self._show_index_progress_dialog("正在扫描游戏数据…")
        thread = QThread(self)
        worker = _GameIndexWorker(
            game_root=game_root,
            compressonatorcli_path=compressonatorcli_path if compressonatorcli_path is not None else self._get_tool_path_or_none(),
            acus_root=self._acus_root,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_background_index_progress)
        worker.finished.connect(self._on_background_index_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_index_thread_stopped)
        self._index_thread = thread
        self._index_worker = worker
        thread.start()

    def _on_background_index_finished(self, idx: object, err: str) -> None:
        if not isinstance(idx, GameDataIndex):
            _scan_logger().warning("scan_result_failed err=%s", err)
            fly_message_async(
                self,
                "游戏索引失败",
                f"{err or '无法建立游戏索引。'}\n可在【设置】中重新选择目录并点击「重新扫描游戏索引」。",
                single_button=True,
                window_modal=True,
            )
            return
        _scan_logger().info("scan_result_ok")
        fly_message_async(
            self,
            "索引完成",
            f"已缓存游戏内乐曲 {len(idx.music)}、场景 {len(idx.stage)}、"
            f"DDSImage {len(idx.dds_image)}、ddsMap {len(idx.dds_map)} 条（仅 ID 与名称）。",
            single_button=True,
            window_modal=True,
        )

    def _on_index_thread_stopped(self) -> None:
        _scan_logger().info("scan_thread_stopped")
        self._hide_index_progress_dialog()
        self._index_thread = None
        self._index_worker = None

    def _show_index_progress_dialog(self, text: str) -> None:
        self._hide_index_progress_dialog()
        dlg = QProgressDialog(self)
        dlg.setWindowTitle("扫描游戏数据")
        dlg.setLabelText(text)
        dlg.setRange(0, 0)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        # 禁止用户在扫描期间操作其它界面；完成后自动关闭。
        dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        dlg.show()
        self._index_progress = dlg

    def _on_background_index_progress(self, msg: str, cur: int, total: int) -> None:
        dlg = self._index_progress
        if dlg is None:
            return
        dlg.setLabelText(msg)
        if total > 0:
            dlg.setRange(0, total)
            dlg.setValue(min(max(cur, 0), total))
        else:
            dlg.setRange(0, 0)

    def _hide_index_progress_dialog(self) -> None:
        if self._index_progress is None:
            return
        safe_dismiss_modal_progress_dialog(self._index_progress)
        self._index_progress = None

    def _get_tool_path_or_none(self) -> Path | None:
        return resolve_compressonatorcli_path(self._cfg)

    def _mount_manager_primary(self) -> None:
        if self._manager.parentWidget() is self._primary_body:
            return
        old = self._manager.parentWidget()
        if old is not None:
            lay = old.layout()
            if lay is not None:
                lay.removeWidget(self._manager)
        pl = self._primary_body.layout()
        if isinstance(pl, QVBoxLayout):
            pl.addWidget(self._manager, stretch=1)

    def _mount_manager_others(self) -> None:
        if self._manager.parentWidget() is self._others_manager_slot:
            return
        old = self._manager.parentWidget()
        if old is not None:
            lay = old.layout()
            if lay is not None:
                lay.removeWidget(self._manager)
        self._others_manager_layout.addWidget(self._manager, stretch=1)

    def _exit_others_mode(self) -> None:
        if not self._in_others_mode:
            return
        self._in_others_mode = False
        self._content_stack.setCurrentWidget(self._primary_body)
        self._mount_manager_primary()

    def _enter_others_mode(self, route_key: str) -> None:
        self.switchTo(self._workspace)
        self.navigationInterface.setCurrentItem(route_key)
        self._in_others_mode = True
        self._current_category_index = -1
        self._content_stack.setCurrentWidget(self._page_others)
        self._mount_manager_others()
        self._others_seg.blockSignals(True)
        if not self._others_seg.currentRouteKey():
            self._others_seg.setCurrentItem("event")
        self._others_seg.blockSignals(False)
        rk = self._others_seg.currentRouteKey() or "event"
        kind, title = _OTHERS_ROUTE_KIND[rk]
        self._apply_category(kind, title)

    def _on_others_segment_changed(self, route_key: str) -> None:
        if not self._in_others_mode:
            return
        pair = _OTHERS_ROUTE_KIND.get(route_key)
        if not pair:
            return
        kind, title = pair
        self._apply_category(kind, title)

    def _select_category(self, route_key: str, kind: str, title: str) -> None:
        self.switchTo(self._workspace)
        self.navigationInterface.setCurrentItem(route_key)
        self._exit_others_mode()
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
            "Stage": "搜索背景（Stage）…",
            "MapBonus": "搜索 MapBonus…",
            "SystemVoice": "搜索系统语音 ID、名称…",
        }
        self._search.setPlaceholderText(placeholders.get(kind, "搜索当前列表…"))
        self._game_music_browser_btn.setVisible(kind == "Music")
        self._manager.set_kind(kind)

    def _restore_current_category_header(self) -> None:
        if self._in_others_mode:
            rk = self._others_seg.currentRouteKey() or "event"
            kind, title = _OTHERS_ROUTE_KIND.get(rk, ("Event", "事件"))
            self._apply_category(kind, title)
            return
        idx = self._current_category_index
        if 0 <= idx < len(self._nav_specs):
            _rk, _icon, _text, kind, title = self._nav_specs[idx]
            if kind != "__Others__":
                self._apply_category(kind, title)

    def _on_game_music_browser(self) -> None:
        try:
            _scan_logger().info("ui_click_game_music_browser")
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
        except Exception:
            _scan_logger().exception("ui_click_game_music_browser_crash")
            fly_critical(self, "操作失败", "打开游戏乐曲浏览时发生异常，请提供日志。")

    def _open_save_patch(self) -> None:
        try:
            _scan_logger().info("ui_click_save_patch")
            dlg = SavePatchDialog(
                acus_root=self._acus_root,
                get_tool_path=self._get_tool_path_or_none,
                parent=self,
            )
            dlg.exec()
        except Exception:
            _scan_logger().exception("ui_click_save_patch_crash")
            fly_critical(self, "操作失败", "打开存档装备时发生异常，请提供日志。")

    def _open_settings(self) -> None:
        try:
            dlg = SettingsDialog(
                cfg=self._cfg,
                acus_root=self._acus_root,
                get_tool_path=self._get_tool_path_or_none,
                on_request_game_rescan=self._request_game_index_rescan,
                parent=self,
            )
            _scan_logger().info("settings_dialog_open")
            if dlg.exec() == dlg.DialogCode.Accepted:
                _scan_logger().info("settings_save_click accepted=1")
                _scan_logger().info("settings_save_apply_done")
                fly_message(self, "已保存", "设置已保存。")
                self._on_refresh()
            else:
                _scan_logger().info("settings_dialog_close_without_save")
        except Exception:
            _scan_logger().exception("settings_dialog_crash")
            fly_critical(self, "操作失败", "打开或保存设置时发生异常，请提供日志。")

    def _request_game_index_rescan(self, game_root: Path, compressonatorcli_path: Path | None) -> None:
        if self._index_thread is not None:
            fly_message_async(
                self,
                "扫描进行中",
                "已有游戏索引扫描任务在后台运行，请稍候完成。",
                single_button=True,
                window_modal=False,
            )
            return
        self._start_index_thread(game_root, compressonatorcli_path)

    def _on_refresh(self) -> None:
        self._manager.reload()

    def _on_add(self) -> None:
        try:
            if self._in_others_mode:
                kind = self._manager._kind_key()
            else:
                idx = self._current_category_index
                kind = self._nav_specs[idx][3] if 0 <= idx < len(self._nav_specs) else ""
            _scan_logger().info("ui_click_add kind=%s", kind)
        except Exception:
            _scan_logger().exception("ui_click_add_precheck_crash")
            fly_critical(self, "操作失败", "新增入口初始化失败，请提供日志。")
            return
        if kind == "Reward":
            gi = self._resolve_game_index()
            music_r, chara_r, trophy_r, np_r, stage_r, sysvoice_r, default_id = reward_dialog_bundle(
                self._acus_root, game_index=gi
            )
            dlg = RewardCreateDialog(
                default_id=default_id,
                music_refs=music_r,
                chara_refs=chara_r,
                trophy_refs=trophy_r,
                nameplate_refs=np_r,
                stage_refs=stage_r,
                sysvoice_refs=sysvoice_r,
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
                    readme = peek_root_readme_from_archive(zp)
                    if readme is not None and readme.strip():
                        show_archive_readme_dialog(self, readme)
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

        if kind == "SystemVoice":
            dlg = SystemVoicePackDialog(
                acus_root=self._acus_root,
                get_tool_path=self._get_tool_path_or_none,
                get_game_root=lambda: self._cfg.game_root or "",
                parent=self,
            )
            dlg.packed.connect(self._on_refresh)
            dlg.exec()
            return

        if kind == "Stage":
            dlg = StageAddDialog(
                acus_root=self._acus_root,
                tool_path=self._get_tool_path_or_none(),
                game_root=self._cfg.game_root or "",
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        tool = self._get_tool_path_or_none()
        if tool is None and not quicktex_available():
            fly_critical(
                self,
                "无法生成 DDS",
                "请任选其一：\n"
                "• 运行 pip install quicktex（推荐，可不装 compressonator）\n"
                "• 或在【设置】里配置 compressonatorcli 可执行文件路径",
            )
            return

        if kind == "Chara":
            dlg = CharaAddDialog(
                acus_root=self._acus_root,
                tool_path=tool,
                parent=self,
                locked_variant=0,
                variant_lock_reason="new_chara",
            )
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
            fly_warning(
                self,
                "未实现",
                "当前已实现【新增角色】【新增地图】【新增事件】【新增任务】【新增歌曲课题称号】【新增称号】【新增名牌】【新增奖励】【系统语音打包向导】。"
                "DDSImage 请直接在 ACUS 目录维护或用其它工具。",
            )
