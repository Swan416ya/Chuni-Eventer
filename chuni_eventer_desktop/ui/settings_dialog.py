from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig
from .fluent_dialogs import fly_warning
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
        self.resize(520, 420)
        self._cfg = cfg
        self._acus_root = acus_root.resolve()
        self._get_tool_path = get_tool_path

        hint = BodyLabel(
            "DDS 预览与 BC3 生成默认使用 quicktex；此处可填写 compressonatorcli 作为备选路径。"
        )
        hint.setWordWrap(True)

        self.compressonator = LineEdit(self)
        self.compressonator.setPlaceholderText("compressonatorcli 可执行文件路径（可选）")
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
        layout.addWidget(card)
        layout.addWidget(pjsk_card)
        layout.addStretch(1)
        layout.addLayout(btns)

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
        self._cfg.save()
