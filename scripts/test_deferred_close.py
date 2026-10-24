#!/usr/bin/env python3
"""Offscreen regression checks for non-blocking dialog close (qthread_lifecycle)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QThread  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from chuni_eventer_desktop.ui.qthread_lifecycle import (  # noqa: E402
    defer_dialog_close,
    defer_until_threads_done,
)


class _SlowThread(QThread):
    def __init__(self, sleep_s: float, parent=None) -> None:
        super().__init__(parent)
        self._sleep_s = sleep_s

    def run(self) -> None:  # noqa: D102
        time.sleep(self._sleep_s)


class _DeferredDialog(QDialog):
    """与真实弹窗相同的关闭策略：线程在跑就隐藏并推迟 reject。"""

    def __init__(self, thread: QThread | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._thread = thread
        self.rejected_via_defer = False

    def closeEvent(self, event) -> None:  # noqa: N802
        if defer_dialog_close(self, self._thread):
            event.ignore()
            return
        super().closeEvent(event)

    def reject(self) -> None:  # noqa: N802
        if defer_dialog_close(self, self._thread):
            self.rejected_via_defer = True
            return
        super().reject()


def _pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.show()
    failures: list[str] = []

    # 1) 线程运行中关闭：必须立刻返回（不阻塞），窗口隐藏，线程结束后才真正 reject。
    slow = _SlowThread(0.4)
    dlg = _DeferredDialog(slow, parent)
    dlg.show()
    slow.start()
    started = time.monotonic()
    dlg.reject()
    elapsed = time.monotonic() - started
    if elapsed > 0.15:
        failures.append(f"reject() blocked the GUI thread for {elapsed:.2f}s")
    if not dlg.rejected_via_defer:
        failures.append("reject() did not take the deferred path")
    if dlg.isVisible():
        failures.append("dialog stayed visible while its worker was running")

    _pump(app, 1.2)
    if not slow.isFinished():
        failures.append("worker thread did not finish")
    if dlg.result() != QDialog.DialogCode.Rejected:
        failures.append("dialog was not rejected after its worker finished")
    if dlg.isVisible():
        failures.append("dialog still visible after deferred close completed")

    # 2) closeEvent 路径同理。
    slow2 = _SlowThread(0.3)
    dlg2 = _DeferredDialog(slow2, parent)
    dlg2.show()
    slow2.start()
    started = time.monotonic()
    dlg2.close()
    elapsed = time.monotonic() - started
    if elapsed > 0.15:
        failures.append(f"close() blocked the GUI thread for {elapsed:.2f}s")
    if dlg2.isVisible():
        failures.append("dialog stayed visible after close() with a running worker")
    _pump(app, 1.0)
    if dlg2.result() != QDialog.DialogCode.Rejected:
        failures.append("closeEvent path did not reject after worker finished")

    # 3) 没有后台线程时：立即关闭，不推迟。
    dlg3 = _DeferredDialog(None, parent)
    dlg3.show()
    started = time.monotonic()
    dlg3.reject()
    elapsed = time.monotonic() - started
    if elapsed > 0.15:
        failures.append(f"idle reject() blocked for {elapsed:.2f}s")
    if dlg3.rejected_via_defer:
        failures.append("idle dialog wrongly took the deferred path")

    # 4) defer_until_threads_done：回调只在线程结束后触发一次。
    calls: list[int] = []
    slow3 = _SlowThread(0.25)
    owner = QWidget()
    slow3.start()
    deferred = defer_until_threads_done(owner, slow3, on_done=lambda: calls.append(1))
    if not deferred:
        failures.append("defer_until_threads_done returned False while a thread was running")
    _pump(app, 0.9)
    if calls != [1]:
        failures.append(f"on_done fired {len(calls)} times, expected exactly 1")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: deferred close never blocks the GUI thread")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
