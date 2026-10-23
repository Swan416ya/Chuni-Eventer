"""外部工具下载 / 安装进度（可读文案 + 真实百分比进度条）。"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QApplication, QSizePolicy, QVBoxLayout

from qfluentwidgets import BodyLabel, ProgressBar

from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import safe_dismiss_modal_progress_dialog


class ToolInstallProgressDialog(FluentCaptionDialog):
    """避免 QProgressDialog 在深色系统主题下黑底无字、且仅能显示不确定进度的问题。"""

    _UI_THROTTLE_S = 0.12

    def __init__(
        self,
        parent,
        *,
        title: str = "外部工具",
        initial: str = "准备中…",
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(480, 180)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setSizeGripEnabled(False)
        self.titleBar.closeBtn.hide()
        self._allow_close = False
        self._last_paint = 0.0
        self._last_percent: int | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            *fluent_caption_content_margins(left=24, right=24, bottom=20)
        )
        layout.setSpacing(12)

        self._label = BodyLabel(initial, self)
        self._label.setWordWrap(True)
        self._label.setMaximumHeight(56)
        self._label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._bar = ProgressBar(self)
        # Start in indeterminate mode ("准备中…") until first real percent arrives.
        self._bar.setRange(0, 0)
        self._bar.setFormat("准备中…")

        layout.addWidget(self._label)
        layout.addWidget(self._bar)

    @staticmethod
    def _compact_message(message: str) -> str:
        line = (message or "").strip().replace("\r\n", "\n")
        if not line:
            return "处理中…"
        parts = [p.strip() for p in line.split("\n") if p.strip()]
        if not parts:
            return "处理中…"
        if len(parts) == 1:
            return parts[0]
        return f"{parts[0]}\n{parts[1]}"

    def update_progress(self, message: str, percent: int | None = None) -> None:
        now = time.monotonic()
        force = percent in (0, 100) or percent is None
        if (
            not force
            and percent == self._last_percent
            and now - self._last_paint < self._UI_THROTTLE_S
        ):
            return
        self._last_paint = now
        self._last_percent = percent

        self._label.setText(self._compact_message(message))
        if percent is None:
            self._bar.setRange(0, 0)
            self._bar.setFormat("")
        else:
            p = max(0, min(100, int(percent)))
            self._bar.setRange(0, 100)
            self._bar.setValue(p)
            self._bar.setFormat(f"{p}%")

    def show_progress(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Keep the modal owner alive until its worker performs a controlled dismiss."""
        if not self._allow_close:
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:
        # Escape and programmatic reject must follow the same worker-lifetime rule.
        if not self._allow_close:
            return
        super().reject()


def dismiss_tool_install_progress(dlg: ToolInstallProgressDialog | None) -> None:
    if dlg is None:
        return
    dlg._allow_close = True
    try:
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.close()
    except RuntimeError:
        return
    QApplication.processEvents()


def dismiss_tool_install_progress_any(dlg) -> None:
    if isinstance(dlg, ToolInstallProgressDialog):
        dismiss_tool_install_progress(dlg)
    else:
        safe_dismiss_modal_progress_dialog(dlg)
