from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import QProgressDialog, QWidget

from ..acus_workspace import AcusConfig
from ..external_tools import install_tool, missing_auto_download_tools
from .fluent_dialogs import fly_critical, fly_message, safe_dismiss_modal_progress_dialog


class _BootstrapWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, cfg: AcusConfig, specs: list) -> None:
        super().__init__()
        self._cfg = cfg
        self._specs = specs

    def run(self) -> None:
        installed: list[str] = []
        errors: list[str] = []
        for spec in self._specs:
            try:
                self.progress.emit(f"正在安装 {spec.name}…")
                install_tool(
                    spec,
                    self._cfg,
                    on_progress=lambda msg, n=spec.name: self.progress.emit(f"{n}\n{msg}"),
                )
                installed.append(spec.name)
            except Exception as e:
                errors.append(f"{spec.name}：{e}")
        self.finished.emit((installed, errors))


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

    dlg = QProgressDialog("正在准备外部工具环境…", None, 0, 0, parent)
    dlg.setWindowTitle("外部工具")
    dlg.setMinimumDuration(0)
    dlg.setCancelButton(None)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.show()

    thread = QThread(parent)
    worker = _BootstrapWorker(cfg, missing)
    worker.moveToThread(thread)
    if hasattr(parent, "_bootstrap_thread"):
        parent._bootstrap_thread = thread  # type: ignore[attr-defined]

    def _finish(payload: object) -> None:
        safe_dismiss_modal_progress_dialog(dlg)
        cfg.external_tools_bootstrap_done = True
        cfg.save()
        if on_finished is not None:
            on_finished()
        if not isinstance(payload, tuple) or len(payload) != 2:
            fly_critical(parent, "安装失败", "外部工具自动安装异常结束。")
            return
        installed, errors = payload
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
        if hasattr(parent, "_bootstrap_thread"):
            parent._bootstrap_thread = None  # type: ignore[attr-defined]

    thread.started.connect(worker.run)
    worker.progress.connect(dlg.setLabelText)
    worker.finished.connect(_finish)
    worker.finished.connect(thread.quit)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(_stopped)
    thread.start()
    return True
