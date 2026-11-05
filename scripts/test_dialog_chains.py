#!/usr/bin/env python3
"""多层级弹窗链动态压测：A 弹窗唤起 B、B 唤起 C…… 逐层关闭 / 逆序关闭。

真实代码里存在「设置页 → 游戏数据浏览 → 乐曲详情 → DDS 图片」、
「伴侣导入 → 新建角色 → 作品库 → 新建作品」这类多层嵌套。
本脚本按真实父子关系逐层构造并 ``open()``，再用三种顺序关闭，检查：
  * 每层 open 后 activeModalWidget 是否正确指向最内层
  * reject()/close() 是否都在 0.5s 内返回
  * 任意关闭顺序下是否残留模态 / 崩溃
  * 关闭外层时内层被连带销毁，不能抛未捕获异常

用法::

    python scripts/test_dialog_chains.py              # 全部链
    python scripts/test_dialog_chains.py --only psb   # 过滤
    python scripts/test_dialog_chains.py --one NAME   # 内部：子进程单跑
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

PER_CHAIN_TIMEOUT_S = 120

# 真实嵌套链（按「谁唤起谁」的父子关系，内层 parent=外层）
CHAINS: dict[str, list[str]] = {
    "settings-browse-detail-dds": [
        "GameDataBrowseDialog",
        "GameMusicDetailDialog",
        "GameDdsImageDialog",
    ],
    "map-add-bonus-rule": ["MapAddDialog", "MapBonusEditDialog", "_MapBonusRuleEditDialog"],
    "map-add-reward": ["MapAddDialog", "RewardCreateDialog"],
    "psb-chara-works": [
        "PsbActionDialog",
        "CharaAddDialog",
        "WorksLibraryManagerDialog",
        "WorkCreateDialog",
    ],
    "pjsk-hub-sus-vocal": ["PjskHubDialog", "PjskSusDownloadDialog", "PjskVocalPickDialog"],
    "map-icon-crop": ["MapIconAddEditDialog", "ImageCropEditorDialog"],
    "trophy-generator": ["TrophyAddDialog", "TrophyPjskGeneratorDialog"],
    "github-music-id": ["GithubSheetDialog", "MusicIdInputDialog"],
    "sysvoice-preview": ["SystemVoicePackDialog", "SysvoicePreviewDialog"],
    "synthetic-6": ["__synthetic__"] * 6,
}

# 通过真实按钮/方法触发的嵌套 exec（弹窗里再开弹窗）
TRIGGERS: dict[str, str] = {
    "trigger:psb-new-chara": "PsbActionDialog._new_chara",
    "trigger:chara-quick-compose": "CharaAddDialog._open_quick_compose_dialog",
}


def _pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _close_visible_dialogs(app) -> int:
    from PyQt6.QtWidgets import QDialog

    closed = 0
    for w in app.topLevelWidgets():
        if isinstance(w, QDialog) and w.isVisible():
            try:
                w.reject()
                closed += 1
            except RuntimeError:
                pass
    return closed


def _build(spec: str, parent, tmp_dir: Path):
    """spec 为类名，或 synthetic 的 __synthetic__。返回对话框实例。"""
    if spec == "__synthetic__":
        from chuni_eventer_desktop.ui.fluent_caption_dialog import FluentCaptionDialog

        dlg = FluentCaptionDialog(parent=parent)
        dlg.resize(360, 240)
        return dlg

    import stress_dialogs as sd

    for mod_name, cls_name, _sig in sd.discover():
        if cls_name == spec:
            return sd.build_dialog(mod_name, cls_name, parent, tmp_dir)
    raise RuntimeError(f"找不到弹窗类 {spec}")


def _run_chain(chain_name: str) -> dict[str, object]:
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication, QDialog

    import stress_dialogs as sd

    result: dict[str, object] = {
        "chain": chain_name,
        "status": "fail",
        "notes": [],
        "failures": [],
    }
    notes: list[str] = result["notes"]  # type: ignore[assignment]
    failures: list[str] = result["failures"]  # type: ignore[assignment]

    app = QApplication.instance() or QApplication([])
    sd._block_network()

    from PyQt6.QtWidgets import QWidget

    root_parent = QWidget()
    root_parent.resize(1200, 800)
    root_parent.show()
    tmp_dir = Path(tempfile.mkdtemp(prefix="chain_"))

    def open_chain(specs: list[str]) -> list:
        parent = root_parent
        opened = []
        for spec in specs:
            dlg = _build(spec, parent, tmp_dir)
            dlg.setModal(True)
            dlg.setWindowModality(__import__("PyQt6.QtCore", fromlist=["Qt"]).Qt.WindowModality.WindowModal)
            dlg.open()
            _pump(app, 0.25)
            opened.append(dlg)
            parent = dlg
        return opened

    def close_all(opened: list, order: str) -> None:
        seq = list(range(len(opened)))
        if order == "inner-first":
            seq = list(reversed(seq))
        elif order == "outer-first":
            seq = seq
        elif order == "middle-first" and len(seq) >= 3:
            mid = len(seq) // 2
            seq = [mid] + [i for i in range(len(seq)) if i != mid]
        for i in seq:
            dlg = opened[i]
            if sip.isdeleted(dlg):
                continue
            t0 = time.monotonic()
            try:
                dlg.reject()
            except RuntimeError:
                # 外层关闭时被连带销毁，属预期
                continue
            dt = time.monotonic() - t0
            if dt > 0.5:
                failures.append(f"{order}: 第 {i + 1} 层 reject() 阻塞 {dt:.2f}s")
            _pump(app, 0.2)

    specs = CHAINS.get(chain_name, [])
    for order in ("inner-first", "outer-first", "middle-first"):
        if not specs:
            break
        try:
            opened = open_chain(specs)
        except Exception:
            failures.append(f"{order}: 构造/打开链失败\n{traceback.format_exc(limit=5)}")
            break

        if len(opened) >= 2:
            modal = QApplication.activeModalWidget()
            if modal is not opened[-1]:
                failures.append(f"{order}: 全部打开后模态不是最内层（{type(modal).__name__ if modal else None}）")

        close_all(opened, order)
        _pump(app, 0.4)
        modal = QApplication.activeModalWidget()
        if modal is not None:
            failures.append(f"{order}: 关闭后残留模态 {type(modal).__name__}")
        visible = [d for d in opened if not sip.isdeleted(d) and d.isVisible()]
        if visible:
            failures.append(f"{order}: {len(visible)} 个弹窗仍可见")
        if not root_parent.isEnabled():
            failures.append(f"{order}: 根父窗口仍被禁用")
        # 兜底关闭，避免污染下一轮
        _close_visible_dialogs(app)
        _pump(app, 0.2)

    # 真实触发：通过弹窗自己的方法再开一层（内部 exec）
    trigger_method = TRIGGERS.get(chain_name)
    if trigger_method:
        cls_name, method_name = trigger_method.split(".")
        opened = []
        try:
            host = _build(cls_name, root_parent, tmp_dir)
            host.setModal(True)
            host.open()
            _pump(app, 0.3)
            opened.append(host)
            from PyQt6.QtCore import QTimer

            QTimer.singleShot(900, lambda: _close_visible_dialogs(app))
            t0 = time.monotonic()
            getattr(host, method_name)()
            dt = time.monotonic() - t0
            if dt > 8:
                failures.append(f"真实触发 {trigger_method} 耗时 {dt:.1f}s")
            _pump(app, 0.4)
            if QApplication.activeModalWidget() is not None:
                failures.append(f"真实触发 {trigger_method} 后残留模态")
        except Exception:
            failures.append(f"真实触发 {trigger_method} 异常\n{traceback.format_exc(limit=5)}")
        finally:
            _close_visible_dialogs(app)
            _pump(app, 0.2)

    result["status"] = "pass" if not failures else "fail"
    return result


def _run_all(only: str | None) -> int:
    names = list(CHAINS) + [n for n in TRIGGERS if n not in CHAINS]
    if only:
        names = [n for n in names if only.lower() in n.lower()]
    print(f"共 {len(names)} 条链路/触发\n")

    results = []
    for idx, name in enumerate(names, 1):
        cmd = [sys.executable, str(Path(__file__).resolve()), "--one", name]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=PER_CHAIN_TIMEOUT_S, cwd=ROOT,
            )
            lines = [ln for ln in (proc.stdout or "").splitlines() if ln.startswith("__RESULT__")]
            payload = (
                json.loads(lines[-1][len("__RESULT__"):])
                if lines
                else {"status": "fail", "failures": ["无结果输出（可能崩溃）", (proc.stderr or "")[-1200:]]}
            )
        except subprocess.TimeoutExpired:
            payload = {"status": "timeout", "failures": [f"超过 {PER_CHAIN_TIMEOUT_S}s"]}
        payload["elapsed"] = round(time.monotonic() - t0, 2)
        results.append(payload)
        mark = {"pass": "ok", "timeout": "HANG"}.get(str(payload.get("status")), "FAIL")
        print(f"[{idx:02d}/{len(names)}] {mark:4s} {name:32s} {payload['elapsed']:5.1f}s")
        for f in payload.get("failures", [])[:4]:
            print(f"    {str(f)[:600]}")

    bad = [r for r in results if r.get("status") != "pass"]
    print("\n===== 汇总 =====")
    print(f"pass: {len(results) - len(bad)}, fail/timeout: {len(bad)}")
    out = ROOT / "docs" / "Code Review" / "dialog_chain_results_2026-10-24.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细：{out}")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    ap.add_argument("--one", default=None)
    args = ap.parse_args()
    if args.one:
        payload = _run_chain(args.one)
        print("__RESULT__" + json.dumps(payload, ensure_ascii=False))
        return 0
    return _run_all(args.only)


if __name__ == "__main__":
    raise SystemExit(main())
