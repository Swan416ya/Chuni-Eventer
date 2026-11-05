#!/usr/bin/env python3
"""动态压测主窗口页面切换与「新增」弹窗（离屏）。

覆盖：
  * 每个导航项 / 其他分段 / 装扮分段 / 设置页 反复切换，测量耗时并检查残留模态
  * 「新增 → 角色」「新增 → 伙伴」端到端打开再关闭（回归 _game_root 修复）

运行::

    .venv-build\\Scripts\\python.exe scripts\\test_page_switch.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

SWITCH_BUDGET_S = 8.0


def _pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _close_open_dialogs(app: QApplication) -> int:
    closed = 0
    for w in app.topLevelWidgets():
        if isinstance(w, QDialog) and w.isVisible():
            try:
                w.reject()
                closed += 1
            except RuntimeError:
                pass
    return closed


def main() -> int:
    app = QApplication.instance() or QApplication([])

    from chuni_eventer_desktop.ui.main_window import MainWindow

    failures: list[str] = []
    timings: list[tuple[str, float]] = []

    win = MainWindow()
    win.show()
    _pump(app, 0.3)
    win.deferred_build_ui()
    _pump(app, 0.6)

    def switch(label: str, fn) -> None:
        t0 = time.monotonic()
        fn()
        dt = time.monotonic() - t0
        timings.append((label, dt))
        _pump(app, 0.15)
        if dt > SWITCH_BUDGET_S:
            failures.append(f"{label}: 切换耗时 {dt:.1f}s")
        modal = QApplication.activeModalWidget()
        if modal is not None:
            failures.append(f"{label}: 切换后残留模态 {type(modal).__name__}")
        if not win.isEnabled():
            failures.append(f"{label}: 主窗口被禁用")

    for round_no in (1, 2, 3):
        for route_key, _icon, text, kind, title in win._nav_specs:
            label = f"r{round_no}:{text}"
            if kind == "__Others__":
                switch(label, lambda rk=route_key: win._enter_others_mode(rk))
            elif kind == "__Avatar__":
                switch(label, lambda rk=route_key: win._enter_avatar_mode(rk))
            else:
                switch(label, lambda rk=route_key, k=kind, t=title: win._select_category(rk, k, t))

        # 其他分段逐个点一遍
        for rk in ("mapicon", "sysvoice", "mate", "rankcourse", "event", "quest", "reward", "mapbonus"):
            def _pick(r=rk):
                win._others_seg.setCurrentItem(r)
            switch(f"r{round_no}:others/{rk}", _pick)

        # 装扮分段
        for rk in ("acc_wear", "acc_head", "acc_face", "acc_hand", "acc_back"):
            def _pick(r=rk):
                win._avatar_seg.setCurrentItem(r)
            switch(f"r{round_no}:avatar/{rk}", _pick)

        switch(f"r{round_no}:settings", win._enter_settings_mode)

    # 端到端「新增 → 伙伴」：弹窗由定时器关掉，_on_add 必须能正常返回
    win._enter_others_mode("nav_others")
    win._others_seg.setCurrentItem("mate")
    _pump(app, 0.2)
    QTimer.singleShot(1200, lambda: _close_open_dialogs(app))
    t0 = time.monotonic()
    try:
        win._on_add()
    except Exception as exc:  # AttributeError 等
        failures.append(f"新增→伙伴 抛异常: {type(exc).__name__}: {exc}")
    dt = time.monotonic() - t0
    timings.append(("add/mate", dt))
    _pump(app, 0.3)
    if QApplication.activeModalWidget() is not None:
        failures.append("新增→伙伴 关闭后残留模态")

    # 端到端「新增 → 角色」
    win._select_category("nav_chara", "Chara", "角色")
    _pump(app, 0.2)
    QTimer.singleShot(1200, lambda: _close_open_dialogs(app))
    t0 = time.monotonic()
    try:
        win._on_add()
    except Exception as exc:
        failures.append(f"新增→角色 抛异常: {type(exc).__name__}: {exc}")
    dt = time.monotonic() - t0
    timings.append(("add/chara", dt))
    _pump(app, 0.3)
    if QApplication.activeModalWidget() is not None:
        failures.append("新增→角色 关闭后残留模态")

    win.close()
    _pump(app, 0.4)

    slowest = sorted(timings, key=lambda x: x[1], reverse=True)[:8]
    print("最慢的 8 次切换：")
    for label, dt in slowest:
        print(f"  {label:28s} {dt:6.2f}s")

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print(f"OK: {len(timings)} 次页面切换/新增均正常返回")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
