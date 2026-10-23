"""外部工具下载 / 安装进度（可读文案 + 真实百分比进度条）。"""

from __future__ import annotations

import time
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout

from qfluentwidgets import (
    BodyLabel,
    IndeterminateProgressBar,
    ProgressBar,
    PushButton,
)

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
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedSize(480, 200)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setSizeGripEnabled(False)
        self.titleBar.closeBtn.hide()
        self._allow_close = False
        self._on_cancel = on_cancel
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

        # qfluentwidgets 的 ProgressBar 自绘时不渲染 format 文本，百分比另用标签显示；
        # 它也没有不确定态的流动动画，因此「准备中…」阶段改用 IndeterminateProgressBar。
        self._bar = ProgressBar(self)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)

        self._indet = IndeterminateProgressBar(self)

        self._pct = BodyLabel("", self)
        self._pct.setMinimumWidth(44)
        self._pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(8)
        bar_row.addWidget(self._bar, stretch=1)
        bar_row.addWidget(self._indet, stretch=1)
        bar_row.addWidget(self._pct)

        # 取消：worker 卡住或网络长时间无响应时，必须有一条用户可走的退出路径
        self._cancel_btn = PushButton("取消", self)
        self._cancel_btn.setFixedWidth(96)
        self._cancel_btn.setEnabled(on_cancel is not None)
        self._cancel_btn.clicked.connect(self._cancel_requested)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addStretch(1)
        foot.addWidget(self._cancel_btn)

        layout.addWidget(self._label)
        layout.addLayout(bar_row)
        layout.addLayout(foot)

        self._show_indeterminate()

    def _show_indeterminate(self) -> None:
        self._bar.hide()
        self._indet.show()
        # 每次日志更新都会走到这里；已启动时不要再 start()，否则动画会一直回到起点
        if not self._indet.isStarted():
            self._indet.start()
        self._pct.setText("")

    def _show_determinate(self, percent: int) -> None:
        self._indet.stop()
        self._indet.hide()
        self._bar.show()
        self._bar.setRange(0, 100)
        self._bar.setValue(percent)
        self._pct.setText(f"{percent}%")

    def _cancel_requested(self) -> None:
        self._cancel_btn.setEnabled(False)
        self._cancel_btn.setText("正在取消…")
        if self._on_cancel is not None:
            self._on_cancel()
        # 取消后立刻放行关闭：即便 worker 不配合，也不能把用户锁在模态窗口里
        self._allow_close = True
        self.close()

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
            self._show_indeterminate()
        else:
            self._show_determinate(max(0, min(100, int(percent))))

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
    try:
        dlg._allow_close = True
        dlg.setWindowModality(Qt.WindowModality.NonModal)
        dlg.close()
    except RuntimeError:
        # 已随 WA_DeleteOnClose 销毁（重复 dismiss，或用户先点了「取消」）
        return


def dismiss_tool_install_progress_any(dlg) -> None:
    if isinstance(dlg, ToolInstallProgressDialog):
        dismiss_tool_install_progress(dlg)
    else:
        safe_dismiss_modal_progress_dialog(dlg)
