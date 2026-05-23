"""QThread 生命周期辅助：避免弹窗/窗口关闭时出现 “Destroyed while thread is still running”。"""

from __future__ import annotations

from PyQt6.QtCore import QThread, QTimer

DEFAULT_QTHREAD_JOIN_MS = 300_000
EXIT_QTHREAD_JOIN_MS = 2_500


def qthread_running_safe(th: QThread | None) -> bool:
    if th is None:
        return False
    try:
        return th.isRunning()
    except RuntimeError:
        return False


def await_qthreads(*threads: QThread | None, timeout_ms: int = DEFAULT_QTHREAD_JOIN_MS) -> None:
    for th in threads:
        if qthread_running_safe(th):
            th.wait(timeout_ms)


def shutdown_qthreads_for_exit(
    *threads: QThread | None,
    timeout_ms: int = EXIT_QTHREAD_JOIN_MS,
) -> None:
    """应用退出：短时等待后台线程结束，避免 closeEvent 阻塞数分钟。"""
    for th in threads:
        if not qthread_running_safe(th):
            continue
        th.quit()
        if th.wait(timeout_ms):
            continue
        th.terminate()
        th.wait(1000)


def finalize_qthread(th: QThread | None, *, timeout_ms: int = DEFAULT_QTHREAD_JOIN_MS) -> None:
    if th is None:
        return
    if qthread_running_safe(th):
        th.wait(timeout_ms)
    th.deleteLater()


def defer_finalize_qthread(th: QThread | None, *, timeout_ms: int = DEFAULT_QTHREAD_JOIN_MS) -> None:
    """推迟到下一事件循环再 wait/deleteLater，避免 finished 与 ok 槽入队顺序问题。"""

    def _run() -> None:
        finalize_qthread(th, timeout_ms=timeout_ms)

    QTimer.singleShot(0, _run)
