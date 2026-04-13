from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEventLoop, QObject, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget

from ..dds_convert import ingest_to_bc3_dds


class _Bc3Worker(QObject):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, jobs: list[tuple[Path, Path]], tool_path: Path | None) -> None:
        super().__init__()
        self._jobs = jobs
        self._tool = tool_path

    def run(self) -> None:
        n = len(self._jobs)
        for i, (src, dst) in enumerate(self._jobs):
            self.progress.emit(i, f"正在编码 ({i + 1}/{n})：{src.name}")
            try:
                ingest_to_bc3_dds(tool_path=self._tool, input_path=src, output_dds=dst)
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
) -> tuple[bool, str | None]:
    """
    在后台线程执行 BC3 编码并显示进度对话框，避免主界面长时间无响应。
    成功返回 (True, None)，失败返回 (False, 错误信息)。
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
    worker = _Bc3Worker(jobs, tool_path)
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
    # 显式重置并解除模态，避免在某些无边框父窗体下残留“隐形模态层”
    # 导致后续完成提示框无法点击。
    dialog.reset()
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.close()
    dialog.deleteLater()
    QApplication.processEvents()

    if err:
        return False, err
    return True, None
