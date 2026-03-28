from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig
from .fluent_dialogs import fly_warning


class SettingsDialog(QDialog):
    def __init__(self, *, cfg: AcusConfig, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(520, 220)
        self._cfg = cfg

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
        layout.addWidget(card, stretch=1)
        layout.addLayout(btns)

    def _pick_tool(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 compressonatorcli")
        if path:
            self.compressonator.setText(path)

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
