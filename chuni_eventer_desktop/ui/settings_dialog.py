from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..acus_workspace import AcusConfig


class SettingsDialog(QDialog):
    def __init__(self, *, cfg: AcusConfig, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self._cfg = cfg

        self.compressonator = QLineEdit()
        self.compressonator.setPlaceholderText("compressonatorcli 可执行文件路径")
        if cfg.compressonatorcli_path:
            self.compressonator.setText(cfg.compressonatorcli_path)

        browse = QPushButton("浏览…")
        browse.clicked.connect(self._pick_tool)

        row = QHBoxLayout()
        row.addWidget(self.compressonator, stretch=1)
        row.addWidget(browse)

        form = QFormLayout()
        form.addRow("DDS 工具", row)

        ok = QPushButton("保存")
        ok.clicked.connect(self.accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btns)

    def _pick_tool(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 compressonatorcli")
        if path:
            self.compressonator.setText(path)

    def apply(self) -> None:
        self._cfg.compressonatorcli_path = self.compressonator.text().strip()
        self._cfg.save()

