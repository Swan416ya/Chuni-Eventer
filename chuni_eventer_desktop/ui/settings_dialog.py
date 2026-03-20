from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
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
        raw = self.compressonator.text().strip()
        if raw:
            p = Path(raw).expanduser()
            try:
                p = p.resolve(strict=False)
            except OSError:
                QMessageBox.warning(self, "路径无效", "无法解析该路径，请检查拼写。")
                return
            if not p.is_file():
                QMessageBox.warning(
                    self,
                    "路径无效",
                    "DDS 工具必须指向 compressonatorcli 的「可执行文件」本体。\n"
                    "不要填「.」、不要选文件夹；请用「浏览…」选择实际程序文件。",
                )
                return
        self._cfg.compressonatorcli_path = raw
        self._cfg.save()

