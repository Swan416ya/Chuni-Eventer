from __future__ import annotations

import threading
from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QWidget

from ..acus_workspace import AcusConfig
from ..external_tools import ToolInstallCancelled, install_tool, missing_auto_download_tools
from .fluent_dialogs import fly_critical, fly_message
from .tool_install_progress import ToolInstallProgressDialog, dismiss_tool_install_progress


class _BootstrapWorker(QObject):
    progress = pyqtSignal(str, int)  # message, percent (-1 = indeterminate)
    finished = pyqtSignal(object)

    def __init__(
        self,
        cfg: AcusConfig,
        specs: list,
        cancel: threading.Event,
    ) -> None:
        super().__init__()
        self._cfg = cfg
        self._specs = specs
        self._cancel = cancel

    def run(self) -> None:
        installed: list[str] = []
        errors: list[str] = []
        for spec in self._specs:
            if self._cancel.is_set():
                break
            try:
                self.progress.emit(f"正在安装 {spec.name}…", 0)
                install_tool(
                    spec,
                    self._cfg,
                    on_progress=lambda msg, pct, n=spec.name: self.progress.emit(
                        f"{n}\n{msg}",
                        -1 if pct is None else int(pct),
                    ),
                    cancel=self._cancel,
                )
                installed.append(spec.name)
            except ToolInstallCancelled:
                break
            except Exception as e:
                errors.append(f"{spec.name}：{e}")
        self.finished.emit((installed, errors, self._cancel.is_set()))


def abort_tool_install_on_parent(parent: QWidget) -> None:
    """关闭窗口时请求中止外部工具下载，并关掉进度弹窗。"""
    cancel = getattr(parent, "_tool_install_cancel", None)
    if isinstance(cancel, threading.Event):
        cancel.set()
    dlg = getattr(parent, "_bootstrap_progress_dialog", None)
    dismiss_tool_install_progress(dlg)
    parent._bootstrap_progress_dialog = None  # type: ignore[attr-defined]


def run_external_tools_bootstrap(
    parent: QWidget,
    cfg: AcusConfig,
    *,
    on_finished: Callable[[], None] | None = None,
) -> bool:
    """
    首次启动：若缺少可自动下载的工具则后台安装。
    返回 True 表示已启动安装任务；False 表示无需安装。
    """
    if cfg.external_tools_bootstrap_done:
        return False

    missing = missing_auto_download_tools(cfg)
    if not missing:
        cfg.external_tools_bootstrap_done = True
        cfg.save()
        return False

    cancel = threading.Event()
    parent._tool_install_cancel = cancel  # type: ignore[attr-defined]

    dlg = ToolInstallProgressDialog(parent, title="外部工具", initial="正在准备外部工具环境…")
    parent._bootstrap_progress_dialog = dlg  # type: ignore[attr-defined]
    dlg.show_progress()

    thread = QThread(parent)
    worker = _BootstrapWorker(cfg, missing, cancel)
    worker.moveToThread(thread)
    parent._bootstrap_thread = thread  # type: ignore[attr-defined]

    def _on_progress(msg: str, percent: int) -> None:
        if cancel.is_set():
            return
        dlg.update_progress(msg, None if percent < 0 else percent)

    def _finish(payload: object) -> None:
        dismiss_tool_install_progress(dlg)
        parent._bootstrap_progress_dialog = None  # type: ignore[attr-defined]
        parent._tool_install_cancel = None  # type: ignore[attr-defined]

        if getattr(parent, "_shutting_down", False):
            return

        cancelled = False
        if isinstance(payload, tuple) and len(payload) == 3:
            installed, errors, cancelled = payload
        elif isinstance(payload, tuple) and len(payload) == 2:
            installed, errors = payload
        else:
            fly_critical(parent, "安装失败", "外部工具自动安装异常结束。")
            return

        if cancelled:
            return

        cfg.external_tools_bootstrap_done = True
        cfg.save()
        if on_finished is not None:
            on_finished()
        if errors and not installed:
            fly_critical(
                parent,
                "外部工具安装失败",
                "未能自动安装所需工具，请检查网络后在【设置 → 外部工具】重试。\n\n"
                + "\n".join(errors),
            )
            return
        if errors:
            fly_message(
                parent,
                "部分工具已安装",
                "已安装："
                + "、".join(installed)
                + "\n\n以下失败（可在设置中手动安装）：\n"
                + "\n".join(errors),
            )
            return
        if installed:
            fly_message(parent, "外部工具已就绪", "已自动安装：" + "、".join(installed))

    def _stopped() -> None:
        parent._bootstrap_thread = None  # type: ignore[attr-defined]

    thread.started.connect(worker.run)
    worker.progress.connect(_on_progress, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(_finish, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(_stopped)
    thread.start()
    return True
