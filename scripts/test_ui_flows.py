#!/usr/bin/env python3
"""动态验证两条历史高危交互链路（离屏）：

1. 嵌套 DDS 进度框：``run_bc3_jobs_with_progress`` 在已打开弹窗内再开进度框、
   跑嵌套事件循环，结束后不能残留模态、不能把父窗卡在 disabled。
2. 「新建角色 → 确定」：``CharaAddDialog._run`` 走真实的 DDS 编码 + XML 落盘，
   在临时 ACUS 目录里完成，结束后必须正常 accept，且没有残留模态。

运行::

    .venv-build\\Scripts\\python.exe scripts\\test_ui_flows.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QColor, QImage  # noqa: E402
from PyQt6.QtWidgets import QApplication, QDialog  # noqa: E402

from chuni_eventer_desktop.ui import chara_add_dialog as cad  # noqa: E402
from chuni_eventer_desktop.ui.dds_progress import run_bc3_jobs_with_progress  # noqa: E402
from chuni_eventer_desktop.ui.fluent_caption_dialog import FluentCaptionDialog  # noqa: E402


def _pump(app: QApplication, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _png(path: Path, color: str) -> Path:
    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    assert img.save(str(path), "PNG")
    return path


def test_nested_progress(app: QApplication, tmp: Path) -> list[str]:
    failures: list[str] = []
    host = FluentCaptionDialog()
    host.setWindowTitle("压测宿主弹窗")
    host.resize(520, 320)
    host.show()
    _pump(app, 0.2)

    src = _png(tmp / "dds_src.png", "#88ccff")
    for i in range(3):
        out = tmp / f"out_{i}.dds"
        t0 = time.monotonic()
        ok, err = run_bc3_jobs_with_progress(
            parent=host,
            tool_path=None,
            jobs=[(src, out)],
            title="压测 DDS",
            fmt="bc3",
        )
        dt = time.monotonic() - t0
        if not ok:
            failures.append(f"round{i}: DDS 编码失败 {err}")
        if dt > 20:
            failures.append(f"round{i}: 进度框耗时异常 {dt:.1f}s")
        _pump(app, 0.3)
        modal = QApplication.activeModalWidget()
        if modal is not None:
            failures.append(f"round{i}: 残留模态 {type(modal).__name__}")
        if not host.isEnabled():
            failures.append(f"round{i}: 宿主弹窗仍处于 disabled")
    host.close()
    _pump(app, 0.2)
    return failures


def test_chara_add_confirm(app: QApplication, tmp: Path) -> list[str]:
    failures: list[str] = []
    acus = tmp / "ACUS"
    acus.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    cad.fly_critical = lambda *a, **k: errors.append(str(a[1:3]))
    cad.user_accepts_vanilla_works_id_for_new_chara_works_folder = lambda *a, **k: True

    dlg = cad.CharaAddDialog(acus_root=acus, tool_path=None)
    dlg.show()
    _pump(app, 0.2)
    finished_codes: list[int] = []
    dlg.finished.connect(lambda code: finished_codes.append(int(code)))

    src = _png(tmp / "chara_src.png", "#ffaa88")
    dlg.base.setText("8123")
    dlg.variant.setText("0")
    dlg.name.setText("压测角色")
    for field in (dlg.head, dlg.half, dlg.full):
        field.setText(str(src))

    # 真实点击「生成并写入 ACUS」，而不是直接调私有方法
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QPushButton

    clicked = False
    for btn in dlg.findChildren(QPushButton):
        if "生成并写入" in btn.text():
            t0 = time.monotonic()
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton)
            dt = time.monotonic() - t0
            clicked = True
            break
    if not clicked:
        failures.append("找不到「生成并写入 ACUS」按钮")
        t0 = time.monotonic()
        dlg._run()
        dt = time.monotonic() - t0
    _pump(app, 0.4)

    if dt > 30:
        failures.append(f"_run() 耗时异常 {dt:.1f}s")
    if errors:
        failures.append("创建过程报错: " + "; ".join(errors[:3]))
    if finished_codes != [int(QDialog.DialogCode.Accepted)]:
        failures.append(f"未进入 Accepted（finished={finished_codes}）")
    modal = QApplication.activeModalWidget()
    if modal is not None:
        failures.append(f"确定后残留模态 {type(modal).__name__}")

    # 落盘检查：DDS + XML 至少要有产物
    dds_files = list((acus / "ddsImage").rglob("*.dds"))
    xml_files = list((acus / "chara").rglob("Chara.xml"))
    if not dds_files:
        failures.append("没有生成 DDS")
    if not xml_files:
        failures.append("没有生成 Chara.xml")

    if not sip.isdeleted(dlg):
        dlg.close()
    _pump(app, 0.2)
    return failures


def test_modal_stack(app: QApplication, _tmp: Path) -> list[str]:
    """三层模态窗嵌套 + 提示框排队，检查关闭顺序与残留。"""
    from chuni_eventer_desktop.ui import fluent_dialogs as fd

    failures: list[str] = []
    outer = FluentCaptionDialog()
    outer.resize(420, 300)
    outer.open()
    _pump(app, 0.15)
    mid = FluentCaptionDialog(parent=outer)
    mid.resize(380, 260)
    mid.open()
    _pump(app, 0.15)
    inner = FluentCaptionDialog(parent=mid)
    inner.resize(340, 220)
    inner.open()
    _pump(app, 0.15)

    if QApplication.activeModalWidget() is not inner:
        failures.append("三层嵌套时 activeModalWidget 不是最内层")

    inner.reject()
    _pump(app, 0.15)
    if QApplication.activeModalWidget() is not mid:
        failures.append("关闭最内层后未回到中层")
    mid.reject()
    _pump(app, 0.15)
    if QApplication.activeModalWidget() is not outer:
        failures.append("关闭中层后未回到外层")
    outer.reject()
    _pump(app, 0.2)
    if QApplication.activeModalWidget() is not None:
        failures.append("三层关闭后仍残留模态")

    # 提示框排队：连开两个，应该串行出现，最后都能关掉
    host = FluentCaptionDialog()
    host.resize(400, 280)
    host.open()
    _pump(app, 0.15)
    fd.fly_message(host, "甲", "第一条")
    fd.fly_message(host, "乙", "第二条")
    _pump(app, 0.6)
    seen = set()
    for _ in range(30):
        boxes = [w for w in app.topLevelWidgets() if type(w).__name__ == "QMessageBox" and w.isVisible()]
        for b in boxes:
            seen.add(b.windowTitle())
            b.reject()
        _pump(app, 0.15)
        if not boxes and QApplication.activeModalWidget() is None:
            # 队列排空后再多等一轮确认没有第三条
            _pump(app, 0.2)
            if not [w for w in app.topLevelWidgets() if type(w).__name__ == "QMessageBox" and w.isVisible()]:
                break
    if seen != {"甲", "乙"}:
        failures.append(f"提示框排队未按序展示: {sorted(seen)}")
    host.reject()
    _pump(app, 0.2)
    if QApplication.activeModalWidget() is not None:
        failures.append("提示框关闭后仍残留模态")
    return failures


def test_disabled_parent_messagebox(app: QApplication, _tmp: Path) -> list[str]:
    """复现历史场景：父窗被 setEnabled(False) 时再弹提示框，不能「看得见点不了」。"""
    import threading

    from PyQt6.QtCore import QTimer
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QMessageBox, QPushButton

    from chuni_eventer_desktop.ui import fluent_dialogs as fd

    failures: list[str] = []

    host = FluentCaptionDialog()
    host.resize(420, 300)
    host.show()
    _pump(app, 0.2)
    host.setEnabled(False)
    _pump(app, 0.1)

    fd.fly_message(host, "禁用父窗", "父窗禁用时的提示框")
    _pump(app, 0.7)
    boxes = [w for w in app.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]
    if not boxes:
        failures.append("父窗 disabled 时提示框没有出现")
    else:
        box = boxes[0]
        if not box.isEnabled():
            failures.append("提示框出现但处于 disabled（点不动）")
        btn = box.defaultButton()
        if btn is None:
            btns = [b for b in box.buttons() if isinstance(b, QPushButton)]
            btn = btns[0] if btns else None
        if btn is not None:
            QTest.mouseClick(btn, Qt.MouseButton.LeftButton)  # type: ignore[name-defined]
        else:
            box.reject()
        _pump(app, 0.3)

    if QApplication.activeModalWidget() is not None:
        failures.append("禁用父窗提示框关闭后残留模态")

    # 同步确认框：父窗 disabled 时 exec 不能卡住
    host.setEnabled(False)
    watchdog = threading.Timer(8.0, lambda: os._exit(2))
    watchdog.start()

    def _answer() -> None:
        for w in app.topLevelWidgets():
            if isinstance(w, QMessageBox) and w.isVisible():
                w.done(int(QMessageBox.StandardButton.Yes))
                return

    QTimer.singleShot(500, _answer)
    try:
        fd.fly_question(host, "确认", "父窗禁用时还能点吗")
    finally:
        watchdog.cancel()
    _pump(app, 0.3)
    if QApplication.activeModalWidget() is not None:
        failures.append("禁用父窗确认框关闭后残留模态")

    host.setEnabled(True)
    host.close()
    _pump(app, 0.2)
    return failures


def test_repeat_cycles(app: QApplication) -> list[str]:
    """反复构造/关闭 40 次，检查窗口对象是否回收。"""
    from chuni_eventer_desktop.ui.rich_hint import DetailDialog

    failures: list[str] = []
    baseline = len(app.topLevelWidgets())
    for _ in range(40):
        d = DetailDialog(text="循环测试")
        d.show()
        app.processEvents()
        d.reject()
    _pump(app, 0.8)
    leftover = len(app.topLevelWidgets())
    if leftover > baseline + 2:
        failures.append(f"40 次开关后顶层窗口从 {baseline} 增到 {leftover}")
    return failures


def main() -> int:
    app = QApplication.instance() or QApplication([])
    tmp = Path(tempfile.mkdtemp(prefix="ui_flows_"))
    failures: list[str] = []
    try:
        failures += test_nested_progress(app, tmp)
        failures += test_chara_add_confirm(app, tmp)
        failures += test_modal_stack(app, tmp)
        failures += test_disabled_parent_messagebox(app, tmp)
        failures += test_repeat_cycles(app)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print("OK: 嵌套进度框与「新建角色→确定」均正常收尾")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
