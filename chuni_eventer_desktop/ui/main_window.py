from __future__ import annotations

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QProgressDialog, QStackedWidget, QVBoxLayout, QWidget

from qfluentwidgets import (
    BodyLabel,
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
from ..external_tools import apply_resolved_paths_to_config, has_bundled_ffmpeg
from .external_tools_bootstrap import run_external_tools_bootstrap
from ..version import APP_VERSION
from ..game_data_index import GameDataIndex, load_cached_game_index, rebuild_and_save_game_index
from ..sheet_install import install_zip_to_acus, peek_root_readme_from_archive
from ..dds_quicktex import quicktex_available
from .manager_widget import ManagerWidget
from .chara_add_dialog import CharaAddDialog
from .map_add_dialog import MapAddDialog, RewardCreateDialog, ensure_reward_xml, reward_dialog_bundle
from .map_icon_dialog import MapIconAddEditDialog
from .nameplate_add_dialog import NamePlateAddDialog
from .trophy_add_dialog import TrophyAddDialog
from .music_add_actions_dialog import MusicSheetChannelsDialog
from .pgko_sheet_download_dialog import PgkoSheetDownloadDialog
from .swan_sheet_download_dialog import SwanSheetDownloadDialog
from .event_add_dialog import EventAddDialog
from .quest_add_dialog import QuestAddDialog
from .mapbonus_dialogs import MapBonusEditDialog
from .stage_add_dialog import StageAddDialog
from .course_rank_dialog import CourseRankEditDialog
from .system_voice_pack_dialog import SystemVoicePackDialog
from .fluent_dialogs import (
    fly_critical,
    fly_message,
    fly_message_async,
    fly_warning,
    show_archive_readme_dialog,
    safe_dismiss_modal_progress_dialog,
)
from .external_tools_bootstrap import abort_tool_install_on_parent
from .qthread_lifecycle import shutdown_qthreads_for_exit
from .nav_icons import (
    SVG_AVATAR,
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

# 「其他」分段 routeKey -> (ManagerWidget kind, 标题)；dict 插入顺序与 Segmented addItem 一致
_OTHERS_ROUTE_KIND: dict[str, tuple[str, str]] = {
    "mapicon": ("MapIcon", "跑图小人"),
    "sysvoice": ("SystemVoice", "系统语音"),
    "rankcourse": ("RankCourse", "段位组曲"),
    "event": ("Event", "事件"),
    "quest": ("Quest", "任务"),
    "reward": ("Reward", "奖励"),
    "mapbonus": ("MapBonus", "加成"),
}

# 装扮分段 routeKey -> (是否已实现列表+编辑, category 1～9, 分段标题)
# 手部与官机一致为 category=5；披风槽位为 category=7。
_AVATAR_SEGMENTS: tuple[tuple[str, bool, int, str], ...] = (
    ("acc_wear", True, 1, "衣服"),
    ("acc_head", True, 2, "帽子"),
    ("acc_face", True, 3, "面具"),
    ("acc_hand", True, 5, "手部"),
    ("acc_back", True, 7, "披风"),
)


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
                    "scan_finish_ok music=%s chara=%s trophy=%s nameplate=%s stage=%s dds_image=%s dds_map=%s",
                    len(idx.music),
                    len(idx.chara),
                    len(idx.trophy),
                    len(idx.nameplate),
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
        # Mica 首次 show 在部分机器上极慢；保留默认 DWM 阴影/圆角，仅关闭 Mica。
        self.setMicaEffectEnabled(False)
        self.navigationInterface.hide()

        self._cfg = AcusConfig.load()
        apply_resolved_paths_to_config(self._cfg)
        self._acus_root = ensure_acus_layout(game_root=self._cfg.game_root or None)

        self._heavy_ui_built = False
        self._startup_shell: QWidget | None = None
        self._manager = None
        self._settings_page = None
        self._in_others_mode = False
        self._in_avatar_mode = False
        self._in_settings_mode = False
        self._current_category_index = 2
        self._nav_specs: list[tuple[str, object, str, str, str]] = []

        self._index_thread: QThread | None = None
        self._index_worker: _GameIndexWorker | None = None
        self._index_progress: QProgressDialog | None = None
        self._bootstrap_thread: QThread | None = None
        self._shutting_down = False
        self._install_startup_shell()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._shutting_down = True
        if self._settings_page is not None:
            tools = getattr(self._settings_page, "_tools", None)
            if tools is not None and hasattr(tools, "cancel_bg_download"):
                tools.cancel_bg_download()
        abort_tool_install_on_parent(self)
        self._hide_index_progress_dialog()
        shutdown_qthreads_for_exit(self._index_thread, self._bootstrap_thread)
        self._index_thread = None
        self._bootstrap_thread = None
        super().closeEvent(event)

    def _install_startup_shell(self) -> None:
        """纯 Qt 占位页 + switchTo：避免空 stackedWidget 首次 show 触发 Fluent 重 init。"""
        self._startup_shell = QWidget()
        self._startup_shell.setObjectName("startupShell")
        shell_lay = QVBoxLayout(self._startup_shell)
        shell_lay.setContentsMargins(24, 24, 24, 24)
        shell_hint = QLabel("正在加载工作区…", self._startup_shell)
        shell_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        shell_lay.addStretch(1)
        shell_lay.addWidget(shell_hint)
        shell_lay.addStretch(1)
        self.stackedWidget.addWidget(self._startup_shell)
        self.switchTo(self._startup_shell)

    def _apply_default_window_size(self, phase: str) -> None:
        self.resize(_DEFAULT_MAIN_WINDOW_WIDTH, _DEFAULT_MAIN_WINDOW_HEIGHT)

    def _restore_frameless_chrome(self) -> None:
        """show 后确保 Win11 圆角与窗口阴影（启动阶段仍不启用 Mica）。"""
        if sys.platform != "win32":
            return
        try:
            from ctypes import byref, c_int

            from qframelesswindow.utils.win32_utils import isGreaterEqualWin11
            from qframelesswindow.windows.c_structures import DWMWINDOWATTRIBUTE

            hwnd = int(self.winId())
            self.windowEffect.addShadowEffect(hwnd)
            if isGreaterEqualWin11():
                round_pref = c_int(2)  # DWMWCP_ROUND
                self.windowEffect.DwmSetWindowAttribute(
                    hwnd,
                    DWMWINDOWATTRIBUTE.DWMWA_WINDOW_CORNER_PREFERENCE.value,
                    byref(round_pref),
                    4,
                )
        except Exception:
            pass

    def apply_deferred_window_chrome(self) -> None:
        """show() 之后设置标题。实机测试 setWindowTitle 在 super 后同步调用可阻塞数秒。"""
        self.setWindowTitle(f"Chuni Eventer v{APP_VERSION}")
        self._apply_default_window_size("post_show")
        self._restore_frameless_chrome()

    def deferred_build_ui(self) -> None:
        """show() 之后构建 UI 并加载首屏数据（隐藏窗口上创建 Fluent 控件极慢）。"""
        if self._heavy_ui_built:
            return
        self._build_workspace_ui()
        self._build_navigation()
        if self._startup_shell is not None:
            self.stackedWidget.removeWidget(self._startup_shell)
            self._startup_shell.deleteLater()
            self._startup_shell = None
        self.switchTo(self._workspace)
        self.navigationInterface.show()
        self.navigationInterface.setCurrentItem("nav_music")
        self._apply_default_window_size("post_build")
        self._heavy_ui_built = True
        QTimer.singleShot(0, lambda: self._apply_category("Music", "歌曲"))
        QTimer.singleShot(0, self._ensure_game_index_background)
        QTimer.singleShot(0, self._bootstrap_external_tools)

    def _build_workspace_ui(self) -> None:
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
        self._index_status = BodyLabel("", self)
        self._index_status.setWordWrap(True)
        self._index_status.setTextColor("#B45309", "#FBBF24")
        self._index_status.hide()
        self._add_btn = PrimaryPushButton("新增")
        self._add_btn.clicked.connect(self._on_add)
        header.addWidget(self._title_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self._search, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._index_status, alignment=Qt.AlignmentFlag.AlignVCenter)
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
        self._others_seg.addItem("mapicon", "跑图小人")
        self._others_seg.addItem("sysvoice", "系统语音")
        self._others_seg.addItem("rankcourse", "段位组曲")
        self._others_seg.addItem("event", "事件")
        self._others_seg.addItem("quest", "任务")
        self._others_seg.addItem("reward", "奖励")
        self._others_seg.addItem("mapbonus", "加成")
        self._others_seg.currentItemChanged.connect(self._on_others_segment_changed)
        ol.addWidget(self._others_seg)
        self._others_manager_slot = QWidget(self._page_others)
        self._others_manager_layout = QVBoxLayout(self._others_manager_slot)
        self._others_manager_layout.setContentsMargins(0, 0, 0, 0)
        ol.addWidget(self._others_manager_slot, stretch=1)

        self._page_avatar = QWidget(self._workspace)
        avl = QVBoxLayout(self._page_avatar)
        avl.setContentsMargins(0, 8, 0, 0)
        avl.setSpacing(8)
        self._avatar_seg = SegmentedWidget(self._page_avatar)
        for rk, _impl, _cat, label in _AVATAR_SEGMENTS:
            self._avatar_seg.addItem(rk, label)
        self._avatar_seg.currentItemChanged.connect(self._on_avatar_segment_changed)
        avl.addWidget(self._avatar_seg)
        self._avatar_stack = QStackedWidget(self._page_avatar)
        self._avatar_manager_slot = QWidget(self._page_avatar)
        self._avatar_manager_layout = QVBoxLayout(self._avatar_manager_slot)
        self._avatar_manager_layout.setContentsMargins(0, 0, 0, 0)
        self._avatar_placeholder = QWidget(self._page_avatar)
        aph = QVBoxLayout(self._avatar_placeholder)
        aph.setContentsMargins(0, 24, 0, 0)
        ph = BodyLabel("敬请期待", self._avatar_placeholder)
        ph.setTextColor("#6B7280", "#9CA3AF")
        aph.addWidget(ph)
        aph.addStretch(1)
        self._avatar_stack.addWidget(self._avatar_manager_slot)
        self._avatar_stack.addWidget(self._avatar_placeholder)
        avl.addWidget(self._avatar_stack, stretch=1)

        self._content_stack = QStackedWidget(self._workspace)
        self._content_stack.addWidget(self._primary_body)
        self._content_stack.addWidget(self._page_others)
        self._content_stack.addWidget(self._page_avatar)
        wlay.addWidget(self._content_stack, stretch=1)

        self.stackedWidget.addWidget(self._workspace)

    def _build_navigation(self) -> None:
        self._nav_specs = [
            ("nav_chara", nav_qicon(SVG_CHARA), "角色", "Chara", "角色"),
            ("nav_map", nav_qicon(SVG_MAP), "地图", "Map", "地图"),
            ("nav_music", nav_qicon(SVG_MUSIC), "歌曲", "Music", "歌曲"),
            ("nav_avatar", nav_qicon(SVG_AVATAR), "装扮", "__Avatar__", "装扮"),
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
            if kind == "__Avatar__":
                self.navigationInterface.addItem(
                    routeKey=route_key,
                    icon=icon,
                    text=text,
                    onClick=lambda r=route_key: self._enter_avatar_mode(r),
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
            routeKey="nav_settings",
            icon=FluentIcon.SETTING,
            text="设置",
            onClick=self._enter_settings_mode,
            position=NavigationItemPosition.BOTTOM,
        )

    def _ensure_settings_page(self):
        from .settings_page import SettingsPage

        if self._settings_page is not None:
            return self._settings_page
        self._settings_page = SettingsPage(
            cfg=self._cfg,
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path_or_none,
            get_game_index=self._resolve_game_index,
            on_settings_saved=self._on_settings_saved,
            on_request_game_rescan=self._request_game_index_rescan,
            parent=self,
        )
        self.stackedWidget.addWidget(self._settings_page)
        return self._settings_page

    def _bootstrap_external_tools(self) -> None:
        """Lite 单 exe 首次启动：在 exe 旁自动下载 .tools；懒人包已含工具则跳过。"""
        if not getattr(sys, "frozen", False):
            return
        if self._cfg.external_tools_bootstrap_done:
            return
        if has_bundled_ffmpeg(self._cfg):
            self._cfg.external_tools_bootstrap_done = True
            self._cfg.save()
            return
        if self._bootstrap_thread is not None:
            return
        started = run_external_tools_bootstrap(self, self._cfg)
        if not started:
            self._cfg.external_tools_bootstrap_done = True
            self._cfg.save()

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
        cached = load_cached_game_index(str(gr))
        if cached is not None:
            return

        fly_message_async(
            self,
            "后台扫描",
            "正在后台建立游戏数据索引，可先浏览 ACUS 内容。\n"
            "进度见窗口顶部提示；完成后会弹出摘要。",
            single_button=True,
            window_modal=False,
        )
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
            f"已缓存游戏内乐曲 {len(idx.music)}、角色 {len(idx.chara)}、"
            f"称号 {len(idx.trophy)}、名牌 {len(idx.nameplate)}；"
            f"场景 {len(idx.stage)}、DDSImage {len(idx.dds_image)}、ddsMap {len(idx.dds_map)} 供编辑功能使用。",
            single_button=True,
            window_modal=True,
        )
        if self._settings_page is not None:
            self._settings_page.refresh_game_data_view()

    def _on_index_thread_stopped(self) -> None:
        _scan_logger().info("scan_thread_stopped")
        self._hide_index_progress_dialog()
        self._index_thread = None
        self._index_worker = None

    def _show_index_progress_dialog(self, text: str) -> None:
        self._hide_index_progress_dialog()
        self._index_status.setText(text)
        self._index_status.show()
        dlg = QProgressDialog(self)
        dlg.setWindowTitle("扫描游戏数据")
        dlg.setLabelText(text)
        dlg.setRange(0, 0)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        # 非模态：不阻塞首屏与其它 ACUS 操作
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.show()
        self._index_progress = dlg

    def _on_background_index_progress(self, msg: str, cur: int, total: int) -> None:
        self._index_status.setText(msg)
        self._index_status.show()
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
        self._index_status.hide()
        self._index_status.setText("")
        if self._index_progress is None:
            return
        safe_dismiss_modal_progress_dialog(self._index_progress)
        self._index_progress = None

    def _get_tool_path_or_none(self) -> Path | None:
        return resolve_compressonatorcli_path(self._cfg)

    def _mount_manager_primary(self) -> None:
        if self._manager is None:
            return
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
        if self._manager is None:
            return
        if self._manager.parentWidget() is self._others_manager_slot:
            return
        old = self._manager.parentWidget()
        if old is not None:
            lay = old.layout()
            if lay is not None:
                lay.removeWidget(self._manager)
        self._others_manager_layout.addWidget(self._manager, stretch=1)

    def _mount_manager_avatar(self) -> None:
        if self._manager is None:
            return
        if self._manager.parentWidget() is self._avatar_manager_slot:
            return
        old = self._manager.parentWidget()
        if old is not None:
            lay = old.layout()
            if lay is not None:
                lay.removeWidget(self._manager)
        self._avatar_manager_layout.addWidget(self._manager, stretch=1)

    def _exit_avatar_mode(self) -> None:
        if not self._in_avatar_mode:
            return
        self._in_avatar_mode = False
        self._content_stack.setCurrentWidget(self._primary_body)
        self._mount_manager_primary()

    def _exit_others_mode(self) -> None:
        if not self._in_others_mode:
            return
        self._in_others_mode = False
        self._content_stack.setCurrentWidget(self._primary_body)
        self._mount_manager_primary()

    def _exit_settings_mode(self) -> None:
        if not self._in_settings_mode:
            return
        self._in_settings_mode = False

    def open_settings_tools_tab(self) -> None:
        """进入设置页并切换到「外部工具」分段（供弹窗引导下载 PenguinTools.CLI 等）。"""
        self._enter_settings_mode()
        self._ensure_settings_page().show_tools_tab()

    def _enter_settings_mode(self) -> None:
        try:
            _scan_logger().info("ui_enter_settings")
            self._exit_avatar_mode()
            self._exit_others_mode()
            self._in_settings_mode = True
            self.switchTo(self._ensure_settings_page())
            self.navigationInterface.setCurrentItem("nav_settings")
        except Exception:
            _scan_logger().exception("ui_enter_settings_crash")
            fly_critical(self, "操作失败", "打开设置页时发生异常，请提供日志。")

    def _on_settings_saved(self) -> None:
        fly_message(self, "已保存", "设置已保存。")
        self._on_refresh()

    def _enter_others_mode(self, route_key: str) -> None:
        self._exit_avatar_mode()
        self._exit_settings_mode()
        self.switchTo(self._workspace)
        self.navigationInterface.setCurrentItem(route_key)
        self._in_others_mode = True
        self._current_category_index = -1
        self._content_stack.setCurrentWidget(self._page_others)
        self._mount_manager_others()
        self._others_seg.blockSignals(True)
        if not self._others_seg.currentRouteKey():
            self._others_seg.setCurrentItem("mapicon")
        self._others_seg.blockSignals(False)
        rk = self._others_seg.currentRouteKey() or "mapicon"
        kind, title = _OTHERS_ROUTE_KIND[rk]
        self._apply_category(kind, title)

    def _enter_avatar_mode(self, route_key: str) -> None:
        self._exit_others_mode()
        self._exit_settings_mode()
        self.switchTo(self._workspace)
        self.navigationInterface.setCurrentItem(route_key)
        self._in_avatar_mode = True
        for i, (rk, *_rest) in enumerate(self._nav_specs):
            if rk == route_key:
                self._current_category_index = i
                break
        self._content_stack.setCurrentWidget(self._page_avatar)
        self._mount_manager_avatar()
        self._avatar_seg.blockSignals(True)
        self._avatar_seg.setCurrentItem("acc_wear")
        self._avatar_seg.blockSignals(False)
        self._apply_avatar_segment(self._avatar_seg.currentRouteKey() or "acc_wear")

    def _apply_avatar_segment(self, route_key: str) -> None:
        meta = next((t for t in _AVATAR_SEGMENTS if t[0] == route_key), None)
        if meta is None:
            return
        _rk, implemented, category, label = meta
        self._search.setText("")
        if implemented:
            self._avatar_stack.setCurrentWidget(self._avatar_manager_slot)
            self._apply_category("AvatarAccessory", "装扮")
            self._manager.set_avatar_accessory_category(category)
        else:
            self._avatar_stack.setCurrentWidget(self._avatar_placeholder)
            self._title_lbl.setText(f"{label}（敬请期待）")
            self._search.setPlaceholderText("该分类尚未开放…")

    def _on_avatar_segment_changed(self, route_key: str) -> None:
        if not self._in_avatar_mode:
            return
        self._apply_avatar_segment(route_key)

    def _on_others_segment_changed(self, route_key: str) -> None:
        if not self._in_others_mode:
            return
        pair = _OTHERS_ROUTE_KIND.get(route_key)
        if not pair:
            return
        kind, title = pair
        self._apply_category(kind, title)

    def _select_category(self, route_key: str, kind: str, title: str) -> None:
        self._exit_settings_mode()
        self.switchTo(self._workspace)
        self.navigationInterface.setCurrentItem(route_key)
        self._exit_avatar_mode()
        self._exit_others_mode()
        for i, (rk, *_rest) in enumerate(self._nav_specs):
            if rk == route_key:
                self._current_category_index = i
                break
        self._apply_category(kind, title)

    def _apply_category(self, kind: str, title: str) -> None:
        if self._manager is None:
            return
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
            "MapIcon": "搜索跑图小人…",
            "SystemVoice": "搜索系统语音 ID、名称…",
            "RankCourse": "搜索段位组曲 ID、名称、曲目…",
            "AvatarAccessory": "搜索企鹅装扮…",
        }
        self._search.setPlaceholderText(placeholders.get(kind, "搜索当前列表…"))
        self._game_music_browser_btn.setVisible(kind == "Music")
        self._manager.set_kind(kind)

    def _restore_current_category_header(self) -> None:
        if self._in_avatar_mode:
            rk = self._avatar_seg.currentRouteKey() or "acc_wear"
            self._apply_avatar_segment(rk)
            return
        if self._in_others_mode:
            rk = self._others_seg.currentRouteKey() or "mapicon"
            kind, title = _OTHERS_ROUTE_KIND.get(rk, ("MapIcon", "跑图小人"))
            self._apply_category(kind, title)
            return
        idx = self._current_category_index
        if 0 <= idx < len(self._nav_specs):
            _rk, _icon, _text, kind, title = self._nav_specs[idx]
            if kind not in ("__Others__", "__Avatar__"):
                self._apply_category(kind, title)

    def _on_game_music_browser(self) -> None:
        try:
            _scan_logger().info("ui_click_game_music_browser")
            from .game_data_browse_dialog import GameDataBrowseDialog

            raw = (self._cfg.game_root or "").strip()
            if not raw:
                fly_message(self, "提示", "请先在【设置】中配置「游戏数据目录」。")
                return
            dlg = GameDataBrowseDialog(
                kind="music",
                game_root=Path(raw).expanduser(),
                acus_root=self._acus_root,
                get_index=self._resolve_game_index,
                get_tool_path=self._get_tool_path_or_none,
                parent=self,
            )
            dlg.exec()
        except Exception:
            _scan_logger().exception("ui_click_game_music_browser_crash")
            fly_critical(self, "操作失败", "打开游戏乐曲浏览时发生异常，请提供日志。")

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
        if self._manager is None:
            return
        self._manager.reload()

    def _on_add(self) -> None:
        try:
            if self._in_avatar_mode:
                rk = self._avatar_seg.currentRouteKey() or "acc_wear"
                _scan_logger().info("ui_click_add avatar seg=%s", rk)
            elif self._in_others_mode:
                kind = self._manager._kind_key()
                _scan_logger().info("ui_click_add kind=%s", kind)
            else:
                idx = self._current_category_index
                kind = self._nav_specs[idx][3] if 0 <= idx < len(self._nav_specs) else ""
                _scan_logger().info("ui_click_add kind=%s", kind)
        except Exception:
            _scan_logger().exception("ui_click_add_precheck_crash")
            fly_critical(self, "操作失败", "新增入口初始化失败，请提供日志。")
            return

        if self._in_avatar_mode:
            rk = self._avatar_seg.currentRouteKey() or "acc_wear"
            if rk not in ("acc_wear", "acc_head", "acc_face", "acc_hand", "acc_back"):
                fly_message(
                    self,
                    "敬请期待",
                    "该装扮分类尚未实现，请先在「衣服」「帽子」「面具」「手部」或「披风」分段操作。",
                )
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
            from .avatar_back_compose_dialog import AvatarBackComposeDialog
            from .avatar_hand_compose_dialog import AvatarHandComposeDialog
            from .avatar_hat_compose_dialog import AvatarHatComposeDialog
            from .avatar_mask_compose_dialog import AvatarMaskComposeDialog
            from .avatar_wear_compose_dialog import AvatarWearComposeDialog

            if rk == "acc_wear":
                dlg = AvatarWearComposeDialog(
                    acus_root=self._acus_root,
                    tool_path=tool,
                    parent=self,
                )
            elif rk == "acc_head":
                dlg = AvatarHatComposeDialog(
                    acus_root=self._acus_root,
                    tool_path=tool,
                    parent=self,
                )
            elif rk == "acc_face":
                dlg = AvatarMaskComposeDialog(
                    acus_root=self._acus_root,
                    tool_path=tool,
                    parent=self,
                )
            elif rk == "acc_hand":
                dlg = AvatarHandComposeDialog(
                    acus_root=self._acus_root,
                    tool_path=tool,
                    parent=self,
                )
            else:
                dlg = AvatarBackComposeDialog(
                    acus_root=self._acus_root,
                    tool_path=tool,
                    parent=self,
                )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
            return

        if kind == "Reward":
            gi = self._resolve_game_index()
            (
                music_r,
                chara_r,
                trophy_r,
                np_r,
                stage_r,
                sysvoice_r,
                mapicon_r,
                default_id,
            ) = reward_dialog_bundle(self._acus_root, game_index=gi)
            dlg = RewardCreateDialog(
                default_id=default_id,
                music_refs=music_r,
                chara_refs=chara_r,
                trophy_refs=trophy_r,
                nameplate_refs=np_r,
                stage_refs=stage_r,
                sysvoice_refs=sysvoice_r,
                mapicon_refs=mapicon_r,
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
                QTimer.singleShot(0, self._on_refresh)
            elif act == "pgko":
                PgkoSheetDownloadDialog(parent=self).exec()
                QTimer.singleShot(0, self._on_refresh)
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

        if kind == "MapIcon":
            dlg = MapIconAddEditDialog(
                acus_root=self._acus_root,
                tool_path=self._get_tool_path_or_none(),
                game_index=self._resolve_game_index(),
                parent=self,
            )
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

        if kind == "RankCourse":
            dlg = CourseRankEditDialog(
                acus_root=self._acus_root,
                game_root=self._cfg.game_root or "",
                get_index=self._resolve_game_index,
                parent=self,
            )
            if dlg.exec() == dlg.DialogCode.Accepted:
                self._on_refresh()
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
                "当前已实现【新增角色】【新增地图】【新增事件】【新增任务】【新增歌曲课题称号】【新增称号】【新增名牌】【新增奖励】【系统语音打包向导】【段位组曲】。"
                "DDSImage 请直接在 ACUS 目录维护或用其它工具。",
            )
