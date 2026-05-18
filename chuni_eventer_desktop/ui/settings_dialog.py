from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CardWidget, CheckBox, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig, app_cache_dir, resolve_compressonatorcli_path
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .pjsk_hub_dialog import PjskHubDialog

_settings_log_logger: logging.Logger | None = None


def _settings_logger() -> logging.Logger:
    global _settings_log_logger
    if _settings_log_logger is not None:
        return _settings_log_logger
    logger = logging.getLogger("chuni.settings_dialog")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        log_dir = app_cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "settings_save.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except Exception:
        pass
    _settings_log_logger = logger
    return logger


class SettingsPanel(QWidget):
    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._cfg = cfg
        self._acus_root = acus_root.resolve()
        self._get_tool_path = get_tool_path
        self._on_request_game_rescan = on_request_game_rescan

        game_hint = BodyLabel(
            "指定已安装游戏中的 **A001** 数据位置（或包含 `A001` / `Option/A001` 的安装根目录）。"
            "用于扫描全量乐曲、场景、DDS 贴图与地图 ddsMap，供地图/奖励编辑下拉里选择。"
        )
        game_hint.setWordWrap(True)
        self.game_root = LineEdit(self)
        self.game_root.setPlaceholderText("例如 D:\\Games\\CHUNITHM 或 …\\A001 的上一级")
        if cfg.game_root:
            self.game_root.setText(cfg.game_root)
        game_browse = PushButton("浏览文件夹…", self)
        game_browse.clicked.connect(self._pick_game_root)
        rescan = PushButton("重新扫描游戏索引", self)
        rescan.clicked.connect(self._rescan_game_index)

        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_row.addWidget(self.game_root, stretch=1)
        game_row.addWidget(game_browse)

        game_card = CardWidget(self)
        game_layout = QVBoxLayout(game_card)
        game_layout.setContentsMargins(16, 16, 16, 16)
        game_layout.setSpacing(12)
        game_layout.addWidget(BodyLabel("游戏数据目录", self))
        game_layout.addWidget(game_hint)
        game_layout.addLayout(game_row)
        game_layout.addWidget(rescan)

        tools_hint = BodyLabel(
            "DDS 工具、FFmpeg、PenguinTools.CLI、mua 等外部程序请在【设置 → 外部工具】中按需下载或指定路径。"
        )
        tools_hint.setWordWrap(True)
        tools_hint.setStyleSheet("color:#6B7280;font-size:13px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        layout.addWidget(game_card)
        layout.addWidget(tools_hint)
        layout.addStretch(1)

    def _pick_game_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择游戏数据目录（含 A001）")
        if d:
            self.game_root.setText(d)

    def _rescan_game_index(self) -> None:
        raw = self.game_root.text().strip()
        if not raw:
            fly_warning(self, "未设置", "请先填写或浏览选择游戏数据目录。")
            return
        root = Path(raw).expanduser()
        tool_path = resolve_compressonatorcli_path(self._cfg)
        if self._on_request_game_rescan is None:
            fly_warning(self, "不可用", "当前窗口未提供后台扫描入口。")
            return
        self._on_request_game_rescan(root, tool_path)

    def apply(self) -> bool:
        lg = _settings_logger()
        lg.info("save_button_clicked")
        try:
            return self._apply_impl()
        except Exception:
            lg.exception("save_button_crash")
            fly_critical(self, "保存失败", "设置保存时发生未处理异常，请提供 settings_save.log。")
            return False

    def _apply_impl(self) -> bool:
        lg = _settings_logger()
        lg.info("apply_start")
        gr = self.game_root.text().strip()
        self._cfg.game_root = gr
        self._cfg.save()
        lg.info("apply_done game_root=%s", gr)
        return True


class SettingsExperimentalPanel(QWidget):
    """实验性功能（烤谱、PGKO UGC 直转等）。"""

    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._cfg = cfg
        self._acus_root = acus_root.resolve()
        self._get_tool_path = get_tool_path

        exp_hint = BodyLabel(
            "以下功能不稳定或仅供体验，可能随时调整或移除。正式制谱请优先使用歌曲页的 SwanSite 导入。"
        )
        exp_hint.setWordWrap(True)
        exp_hint.setStyleSheet("color:#6B7280;font-size:13px;")

        pjsk_card = CardWidget(self)
        pjsk_layout = QVBoxLayout(pjsk_card)
        pjsk_layout.setContentsMargins(16, 16, 16, 16)
        pjsk_layout.setSpacing(12)
        pjsk_layout.addWidget(BodyLabel("烤谱（Project SEKAI · 实验）", self))
        pjsk_hint = BodyLabel(
            "本功能仅供图一乐：从游戏导出的 SUS 与自动转换结果不经精修几乎无法正常游玩。\n"
            "需要可玩的自制谱，请在歌曲页点击「新增」→ 选择 SwanSite，下载已精修谱面并导入。"
        )
        pjsk_hint.setWordWrap(True)
        pjsk_hint.setStyleSheet("color:#b45309;font-size:13px;")
        pjsk_layout.addWidget(pjsk_hint)
        pjsk_open = PushButton("打开烤谱下载与本地缓存…", self)
        pjsk_open.clicked.connect(self._open_pjsk_hub)
        pjsk_layout.addWidget(pjsk_open)

        pgko_card = CardWidget(self)
        pgko_layout = QVBoxLayout(pgko_card)
        pgko_layout.setContentsMargins(16, 16, 16, 16)
        pgko_layout.setSpacing(12)
        pgko_layout.addWidget(BodyLabel("PGKO UGC 直转 c2s（实验）", self))
        pgko_hint = BodyLabel(
            "默认关闭。关闭时，主流程只允许 mgxc -> c2s；"
            "UGC 直转仅作为实验功能在 UGC 引导页中可见。"
        )
        pgko_hint.setWordWrap(True)
        pgko_hint.setStyleSheet("color:#b45309;font-size:13px;")
        pgko_layout.addWidget(pgko_hint)
        self.pgko_exp_checkbox = CheckBox("启用实验性 UGC 直转入口", self)
        self.pgko_exp_checkbox.setChecked(bool(getattr(cfg, "enable_pgko_ugc_experimental", False)))
        pgko_layout.addWidget(self.pgko_exp_checkbox)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        layout.addWidget(exp_hint)
        layout.addWidget(pjsk_card)
        layout.addWidget(pgko_card)
        layout.addStretch(1)

    def _open_pjsk_hub(self) -> None:
        hub = PjskHubDialog(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path,
            parent=self.window(),
        )
        hub.exec()

    def apply_fields(self) -> None:
        self._cfg.enable_pgko_ugc_experimental = bool(self.pgko_exp_checkbox.isChecked())


class SettingsDialog(FluentCaptionDialog):
    """独立弹窗版设置（兼容）；主窗口请使用 SettingsPage。"""

    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(520, 520)
        self._general = SettingsPanel(
            cfg=cfg,
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            on_request_game_rescan=on_request_game_rescan,
            parent=self,
        )
        self._experimental = SettingsExperimentalPanel(
            cfg=cfg,
            acus_root=acus_root,
            get_tool_path=get_tool_path,
            parent=self,
        )
        save = PrimaryPushButton("保存设置", self)
        save.clicked.connect(self._save_all)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*fluent_caption_content_margins())
        layout.setSpacing(16)
        layout.addWidget(self._general)
        layout.addWidget(self._experimental)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(save)
        layout.addLayout(btns)

    def _save_all(self) -> None:
        self._experimental.apply_fields()
        if self._general.apply():
            self.accept()
