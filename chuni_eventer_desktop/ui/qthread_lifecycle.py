"""QThread 生命周期辅助：避免弹窗/窗口关闭时出现 “Destroyed while thread is still running”。"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QObject, QThread, QTimer

DEFAULT_QTHREAD_JOIN_MS = 300_000
EXIT_QTHREAD_JOIN_MS = 2_500


def qthread_running_safe(th: QThread | None) -> bool:
    if th is None:
        return False
    try:
        return th.isRunning()
    except RuntimeError:
        return False


def threads_still_running(*threads: QThread | None) -> bool:
    return any(qthread_running_safe(t) for t in threads)


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
    """收尾线程对象。线程仍在跑时不再阻塞调用线程，改为结束后再 deleteLater。"""
    if th is None:
        return
    if qthread_running_safe(th):
        th.finished.connect(th.deleteLater)
        return
    th.deleteLater()


def defer_finalize_qthread(th: QThread | None, *, timeout_ms: int = DEFAULT_QTHREAD_JOIN_MS) -> None:
    """推迟到下一事件循环再 wait/deleteLater，避免 finished 与 ok 槽入队顺序问题。"""

    def _run() -> None:
        finalize_qthread(th, timeout_ms=timeout_ms)

    QTimer.singleShot(0, _run)


def defer_until_threads_done(
    owner: QObject,
    *threads: QThread | None,
    on_done: Callable[[], None],
    poll_ms: int = 100,
) -> bool:
    """线程仍在运行时，不阻塞 GUI：轮询到全部结束再回调 ``on_done``。

    返回 True 表示已推迟；False 表示当前没有线程在跑，调用方应立即继续。
    轮询定时器挂在 ``owner`` 上，owner 销毁时定时器随之回收。
    """
    alive = [t for t in threads if qthread_running_safe(t)]
    if not alive:
        return False

    timer = QTimer(owner)
    timer.setInterval(poll_ms)

    def _tick() -> None:
        if any(qthread_running_safe(t) for t in alive):
            return
        timer.stop()
        timer.deleteLater()
        try:
            on_done()
        except RuntimeError:
            # 窗口已随线程一起销毁
            pass

    timer.timeout.connect(_tick)
    timer.start()
    return True


def defer_dialog_close(dialog, *threads: QThread | None, poll_ms: int = 100) -> bool:
    """关闭弹窗时若后台线程仍在跑：先隐藏窗口，线程结束后再 reject。

    关键点：绝不在 GUI 线程上 ``wait()``。旧实现最长等待 300 秒，
    表现为「一关下载弹窗，整个主窗口未响应」。

    返回 True 表示关闭已推迟（调用方应 ``event.ignore()`` 或直接 return）。
    """
    if not threads_still_running(*threads):
        return False

    try:
        dialog.hide()
    except RuntimeError:
        return False

    def _finish() -> None:
        try:
            dialog.reject()
        except RuntimeError:
            pass

    return defer_until_threads_done(dialog, *threads, on_done=_finish, poll_ms=poll_ms)
