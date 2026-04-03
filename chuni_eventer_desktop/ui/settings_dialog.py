from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .index_progress import run_rebuild_game_index_with_progress
from .pjsk_hub_dialog import PjskHubDialog


class SettingsDialog(QDialog):
    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(520, 520)
        self._cfg = cfg
        self._acus_root = acus_root.resolve()
        self._get_tool_path = get_tool_path

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

        if getattr(sys, "frozen", False):
            dds_hint = (
                "打包版已在 exe 同级的 .tools\\CompressonatorCLI 附带 AMD Compressonator CLI。"
                "此处留空则自动使用该副本；填写路径则优先使用您指定的 compressonatorcli.exe。"
            )
            ph = "留空用附带 CLI；或浏览选择自定义 compressonatorcli.exe"
        else:
            dds_hint = (
                "DDS 预览与 BC3 生成默认使用 quicktex；此处可填写 compressonatorcli 作为备选路径。"
            )
            ph = "compressonatorcli 可执行文件路径（可选）"
        hint = BodyLabel(dds_hint)
        hint.setWordWrap(True)

        self.compressonator = LineEdit(self)
        self.compressonator.setPlaceholderText(ph)
        if cfg.compressonatorcli_path:
            self.compressonator.setText(cfg.compressonatorcli_path)

        browse = PushButton("浏览…", self)
        browse.clicked.connect(self._pick_tool)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.compressonator, stretch=1)
        row.addWidget(browse)

        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)
        card_layout.addWidget(BodyLabel("compressonator CLI", self))
        card_layout.addLayout(row)

        pjsk_card = CardWidget(self)
        pjsk_layout = QVBoxLayout(pjsk_card)
        pjsk_layout.setContentsMargins(16, 16, 16, 16)
        pjsk_layout.setSpacing(12)
        pjsk_layout.addWidget(BodyLabel("烤谱（Project SEKAI · 实验）", self))
        pjsk_hint = BodyLabel(
            "本功能仅供图一乐：从游戏导出的 SUS 与自动转换结果不经精修几乎无法正常游玩。\n"
            "需要可玩的自制谱，请在歌曲页点击「新增」→ 选择 Swan 站，下载已精修谱面并导入。"
        )
        pjsk_hint.setWordWrap(True)
        pjsk_hint.setStyleSheet("color:#b45309;font-size:13px;")
        pjsk_layout.addWidget(pjsk_hint)
        pjsk_open = PushButton("打开烤谱下载与本地缓存…", self)
        pjsk_open.clicked.connect(self._open_pjsk_hub)
        pjsk_layout.addWidget(pjsk_open)

        ok = PrimaryPushButton("保存", self)
        ok.clicked.connect(self.accept)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        layout.addWidget(hint)
        layout.addWidget(game_card)
        layout.addWidget(card)
        layout.addWidget(pjsk_card)
        layout.addStretch(1)
        layout.addLayout(btns)

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
        tool_raw = (self.compressonator.text() or "").strip()
        tool_path: Path | None = None
        if tool_raw:
            try:
                tp = Path(tool_raw).expanduser().resolve(strict=False)
                if tp.is_file():
                    tool_path = tp
            except OSError:
                tool_path = None
        idx, err = run_rebuild_game_index_with_progress(
            self, game_root=root, compressonatorcli_path=tool_path
        )
        if idx is None:
            fly_critical(self, "扫描失败", err)
            return
        fly_message(
            self,
            "扫描完成",
            f"已索引乐曲 {len(idx.music)}、场景 {len(idx.stage)}、"
            f"DDSImage {len(idx.dds_image)}、ddsMap {len(idx.dds_map)}。\n"
            f"数据根：{idx.a001_root}",
        )

    def _pick_tool(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 compressonatorcli")
        if path:
            self.compressonator.setText(path)

    def _open_pjsk_hub(self) -> None:
        hub = PjskHubDialog(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path,
            parent=self,
        )
        hub.exec()

    def apply(self) -> None:
        raw = self.compressonator.text().strip()
        if raw:
            p = Path(raw).expanduser()
            try:
                p = p.resolve(strict=False)
            except OSError:
                fly_warning(self, "路径无效", "无法解析该路径，请检查拼写。")
                return
            if not p.is_file():
                fly_warning(
                    self,
                    "路径无效",
                    "DDS 工具必须指向 compressonatorcli 的「可执行文件」本体。\n"
                    "不要填「.」、不要选文件夹；请用「浏览…」选择实际程序文件。",
                )
                return
        self._cfg.compressonatorcli_path = raw
        gr = self.game_root.text().strip()
        self._cfg.game_root = gr
        self._cfg.save()
        if gr:
            _idx, err = run_rebuild_game_index_with_progress(
                self,
                game_root=Path(gr).expanduser(),
                compressonatorcli_path=self._get_tool_path(),
            )
            if _idx is None and err:
                fly_warning(self, "游戏索引未更新", err)
