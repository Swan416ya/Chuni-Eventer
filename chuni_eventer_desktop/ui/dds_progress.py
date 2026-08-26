from __future__ import annotations

from pathlib import Path
from typing import Literal

from PyQt6.QtCore import QEventLoop, QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget

from ..dds_convert import ingest_to_bc1_dds, ingest_to_bc3_dds
from .fluent_dialogs import safe_dismiss_modal_progress_dialog


class _Bc3Worker(QObject):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, jobs: list[tuple[Path, Path]], tool_path: Path | None, fmt: str) -> None:
        super().__init__()
        self._jobs = jobs
        self._tool = tool_path
        self._fmt = fmt

    def run(self) -> None:
        n = len(self._jobs)
        ingest_fn = ingest_to_bc1_dds if self._fmt == "bc1" else ingest_to_bc3_dds
        for i, (src, dst) in enumerate(self._jobs):
            self.progress.emit(i, f"正在编码 ({i + 1}/{n})：{src.name}")
            try:
                ingest_fn(tool_path=self._tool, input_path=src, output_dds=dst)
            except Exception as e:
                self.failed.emit(str(e))
                return
        self.finished_ok.emit()


def run_bc3_jobs_with_progress(
    *,
    parent: QWidget | None,
    tool_path: Path | None,
    jobs: list[tuple[Path, Path]],
    title: str = "正在生成 DDS",
    fmt: Literal["bc1", "bc3"] = "bc3",
) -> tuple[bool, str | None]:
    """
    在后台线程执行 BC1/BC3 编码并显示进度对话框，避免主界面长时间无响应。
    成功返回 (True, None)，失败返回 (False, 错误信息)。

    ``fmt`` 默认 ``"bc3"``（角色立绘/名牌/avatar 等带 alpha 资源）；
    封面/地图背景/宣传图等无 alpha 资源应传 ``"bc1"``。
    """
    if not jobs:
        return True, None

    err: str | None = None
    dialog = QProgressDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setLabelText("准备中…")
    if len(jobs) == 1:
        dialog.setRange(0, 0)
    else:
        dialog.setRange(0, len(jobs))
        dialog.setValue(0)
    dialog.setMinimumDuration(0)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)
    dialog.setCancelButton(None)

    thread = QThread(parent)
    worker = _Bc3Worker(jobs, tool_path, fmt)
    worker.moveToThread(thread)
    loop = QEventLoop(parent)

    def on_progress(idx: int, msg: str) -> None:
        dialog.setLabelText(msg)
        if len(jobs) > 1:
            dialog.setValue(idx)

    def on_ok() -> None:
        if len(jobs) > 1:
            dialog.setValue(len(jobs))

    def on_fail(msg: str) -> None:
        nonlocal err
        err = msg

    worker.progress.connect(on_progress)
    worker.finished_ok.connect(on_ok)
    worker.finished_ok.connect(thread.quit)
    worker.failed.connect(on_fail)
    worker.failed.connect(thread.quit)
    thread.finished.connect(loop.quit)
    thread.finished.connect(worker.deleteLater)
    thread.started.connect(worker.run)

    dialog.show()
    QApplication.processEvents()
    thread.start()
    loop.exec()
    thread.wait(120_000)
    safe_dismiss_modal_progress_dialog(dialog)

    if err:
        return False, err
    return True, None
