#!/usr/bin/env python3
"""动态压测：逐个构造 / 显示 / 关闭 UI 里的每个弹窗，检测卡死与残留模态。

用法::

    python scripts/stress_dialogs.py --list           # 列出全部弹窗与构造签名
    python scripts/stress_dialogs.py                  # 全部跑一遍（每个弹窗独立子进程 + 超时）
    python scripts/stress_dialogs.py --only Chara     # 只跑类名含 Chara 的
    python scripts/stress_dialogs.py --one mod:Class  # 内部使用：在子进程里跑单个弹窗

判定「卡死」的口径：
  * 构造/显示/关闭过程中进程超时（子进程被 kill）
  * ``reject()``/``close()`` 调用超过 0.5 秒没返回
  * 关闭后仍有 ``activeModalWidget`` 残留，或父窗口仍处于 disabled
  * 关闭后弹窗仍然可见

所有网络访问都被替换成立即失败的 OSError，保证测试不会真的等网络超时。
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path
from types import ModuleType

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ACUS_ROOT = ROOT / "ACUS"
FREEMOTE_DIR = ROOT / "tools" / "FreeMote"
GAME_ROOT = ROOT / "_tmp_stress_no_game"

UI_PKG = ROOT / "chuni_eventer_desktop" / "ui"

PER_DIALOG_TIMEOUT_S = 60


# ---------------------------------------------------------------------------
# 发现：ui/ 下所有 QDialog 子类
# ---------------------------------------------------------------------------


def discover() -> list[tuple[str, str, str]]:
    """返回 [(module_name, class_name, signature)]。"""
    from PyQt6.QtWidgets import QDialog

    out: list[tuple[str, str, str]] = []
    for py in sorted(UI_PKG.glob("*.py")):
        if py.name.startswith("_"):
            continue
        mod_name = f"chuni_eventer_desktop.ui.{py.stem}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue
        for name, obj in vars(mod).items():
            if not inspect.isclass(obj) or obj.__module__ != mod_name:
                continue
            if name == "FluentCaptionDialog":
                continue
            try:
                if not issubclass(obj, QDialog):
                    continue
            except TypeError:
                continue
            sig = str(inspect.signature(obj.__init__)).replace("self, ", "")
            out.append((mod_name, name, sig))
    return out


def _inventory() -> None:
    for mod, name, sig in discover():
        print(f"{name:34s} {mod.split('.')[-1]:32s} {sig}")


# ---------------------------------------------------------------------------
# 构造参数兜底
# ---------------------------------------------------------------------------


class Skip(Exception):
    pass


def _make_parent():
    from PyQt6.QtWidgets import QWidget

    w = QWidget()
    w.resize(1200, 800)
    w.show()
    return w


def _callbacks():
    return lambda *a, **k: None


def _make_png(tmp_dir: Path) -> Path:
    from PyQt6.QtGui import QColor, QImage

    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    img.fill(QColor("#7aa2f7"))
    out = tmp_dir / "stress_source.png"
    img.save(str(out), "PNG")
    return out


def _pgko_pick(tmp_dir: Path):
    from chuni_eventer_desktop.pgko_to_c2s import PgkoChartPick

    p = tmp_dir / "stress.mgxc"
    if not p.exists():
        p.write_bytes(b"\x00" * 64)
    return PgkoChartPick(p, "mgxc")


def _find_works_xml() -> Path:
    for p in (ACUS_ROOT / "charaWorks").rglob("*.xml"):
        return p
    raise Skip("ACUS 里没有 charaWorks XML")


def _recipes(cls_name: str, parent, tmp_dir: Path):
    from chuni_eventer_desktop.pjsk_acus_install import PjskLocalBundle
    from chuni_eventer_desktop.ui.map_add_dialog import CellData, MapAreaExtras, MapInfoMeta

    table = {
        "GameDataBrowseDialog": lambda: dict(
            kind="music",
            game_root=GAME_ROOT,
            acus_root=ACUS_ROOT,
            get_index=lambda: None,
            get_tool_path=lambda: None,
            parent=parent,
        ),
        "ImageCropEditorDialog": lambda: dict(
            source_path=_make_png(tmp_dir),
            target_size=(512, 512),
            parent=parent,
        ),
        "AreaExtrasDialog": lambda: dict(
            acus_root=ACUS_ROOT,
            game_index=None,
            extras=MapAreaExtras(-1, "Invalid", (0,) * 8),
            parent=parent,
        ),
        "AreaPageMetaDialog": lambda: dict(meta=MapInfoMeta(), dds_refs=[], parent=parent),
        "MapAreaProgressDialog": lambda: dict(area_id=0, cells=[], grid_indices=[], parent=parent),
        "CellEditDialog": lambda: dict(
            acus_root=ACUS_ROOT,
            reward_refs=[],
            chara_refs=[],
            trophy_refs=[],
            nameplate_refs=[],
            stage_refs=[],
            sysvoice_refs=[],
            mapicon_refs=[],
            music_refs=[],
            data=CellData(),
            game_index=None,
            parent=parent,
        ),
        "PjskConvertToAcusDialog": lambda: dict(
            acus_root=ACUS_ROOT,
            bundle=PjskLocalBundle(1, tmp_dir, {}),
            default_chuni_id=1,
            parent=parent,
        ),
        "CharaEditWorksDialog": lambda: dict(xml_path=_find_works_xml(), parent=parent),
        "_CharaQuickComposeDialog": lambda: dict(
            static_chara_dir=ACUS_ROOT / "chara",
            out_dir=tmp_dir,
            parent=parent,
        ),
        "GameDdsImageDialog": lambda: dict(
            title="压测",
            subtitle="压测",
            dds_paths=[],
            acus_root=ACUS_ROOT,
            get_tool_path=lambda: None,
            parent=parent,
        ),
        "MapIconAddEditDialog": lambda: dict(
            acus_root=ACUS_ROOT,
            tool_path=None,
            game_index=None,
            parent=parent,
        ),
        "_MapBonusRuleEditDialog": lambda: dict(
            parent=parent,
            initial=None,
            music_pairs=[],
            chara_pairs=[],
            genre_pairs=[],
            release_tag_pairs=[],
        ),
        "_PgkoInstallConfigDialog": lambda: dict(
            pick=_pgko_pick(tmp_dir),
            meta={},
            acus_root=ACUS_ROOT,
            tool_path=None,
            parent=parent,
        ),
    }
    factory = table.get(cls_name)
    return factory() if factory else None


def _arg_value(name: str, ann: object, parent, tmp_dir: Path):
    lname = name.lower()
    if lname == "parent":
        return parent
    if lname in ("acus_root", "out_dir"):
        return ACUS_ROOT
    if lname in ("game_root", "game_dir"):
        return GAME_ROOT
    if lname in ("freemote_dir", "freemote_path"):
        return FREEMOTE_DIR
    if lname in ("tool_path", "dds_tool", "compressonator", "compressonatorcli_path"):
        return None
    if lname == "cfg":
        from chuni_eventer_desktop.acus_workspace import AcusConfig

        return AcusConfig.load()
    if lname.startswith("get_") or lname.startswith("on_") or lname.endswith("_cb"):
        return _callbacks()
    if lname in ("title", "text", "body", "label", "message", "name"):
        return "压测"
    if lname in ("items", "rows", "musics", "bundles", "entries", "paths", "jobs"):
        return []
    if lname in ("kind", "category", "scene", "mode"):
        return ""
    if lname.endswith("_id") or lname in ("id", "index", "count", "page"):
        return 0
    if isinstance(ann, str):
        ann_text = ann
    else:
        ann_text = getattr(ann, "__name__", "")
    if ann_text in ("str",):
        return ""
    if ann_text in ("int", "float"):
        return 0
    if ann_text in ("bool",):
        return False
    if ann_text in ("Path", "PosixPath", "WindowsPath"):
        return tmp_dir
    if ann_text.startswith("list") or ann_text.startswith("List"):
        return []
    if ann_text.startswith("dict") or ann_text.startswith("Dict"):
        return {}
    if ann_text.startswith("tuple") or ann_text.startswith("Tuple"):
        return ()
    if ann_text.startswith("Callable"):
        return _callbacks()
    if inspect.isclass(ann):
        try:
            return ann()
        except Exception:
            raise Skip(f"无法构造参数 {name}: {ann_text}") from None
    raise Skip(f"无法推断参数 {name}: {ann_text or '无注解'}")


def build_dialog(mod_name: str, cls_name: str, parent, tmp_dir: Path):
    mod: ModuleType = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name)
    recipe = _recipes(cls_name, parent, tmp_dir)
    if recipe is not None:
        return cls(**recipe)
    sig = inspect.signature(cls.__init__)
    kwargs: dict[str, object] = {}
    for pname, param in sig.parameters.items():
        if pname == "self" or param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if param.default is not param.empty:
            continue
        kwargs[pname] = _arg_value(pname, param.annotation, parent, tmp_dir)
    return cls(**kwargs)


# ---------------------------------------------------------------------------
# 子进程：单个弹窗的动态测试
# ---------------------------------------------------------------------------


def _block_network() -> None:
    def _blocked(*_a, **_k):
        raise OSError("network disabled by stress test")

    urllib.request.urlopen = _blocked  # type: ignore[assignment]


def _pump(app, seconds: float) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def _close_message_boxes(app) -> int:
    from PyQt6.QtWidgets import QMessageBox

    closed = 0
    for w in app.topLevelWidgets():
        if isinstance(w, QMessageBox) and w.isVisible():
            try:
                w.reject()
                closed += 1
            except RuntimeError:
                pass
    return closed


class _FakeRunningThread:
    """只实现 defer 逻辑需要的接口。"""

    def __init__(self) -> None:
        self.running = True

    def isRunning(self) -> bool:  # noqa: N802
        return self.running


def _run_one(mod_name: str, cls_name: str) -> dict[str, object]:
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication, QMessageBox

    from chuni_eventer_desktop.ui import fluent_dialogs as fd

    result: dict[str, object] = {
        "module": mod_name,
        "class": cls_name,
        "status": "fail",
        "notes": [],
        "failures": [],
    }
    app = QApplication.instance() or QApplication([])
    _block_network()
    parent = _make_parent()
    tmp_dir = Path(tempfile.mkdtemp(prefix="stress_dlg_"))

    notes: list[str] = result["notes"]  # type: ignore[assignment]
    failures: list[str] = result["failures"]  # type: ignore[assignment]

    try:
        first = build_dialog(mod_name, cls_name, parent, tmp_dir)
    except Skip as exc:
        result["status"] = "skip"
        notes.append(str(exc))
        return result
    except Exception:
        result["status"] = "construct_error"
        failures.append(traceback.format_exc(limit=4))
        return result

    # ---- 轮次 1/2：显示 → 弹提示框 → 关闭 ----
    for round_no in (1, 2):
        try:
            dlg = first if round_no == 1 else build_dialog(mod_name, cls_name, parent, tmp_dir)
        except Exception:
            failures.append(f"round{round_no} 构造失败:\n{traceback.format_exc(limit=4)}")
            break

        dlg.show()
        _pump(app, 0.5)
        if not dlg.isVisible():
            notes.append(f"round{round_no}: show() 后不可见（可能自行关闭）")

        # 在弹窗上再叠一层提示框，模拟「操作失败/成功」提示
        try:
            fd.fly_message(dlg, "压测", "模态层叠测试")
            _pump(app, 0.35)
            boxes = [w for w in app.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]
            notes.append(f"round{round_no}: 提示框 {len(boxes)} 个")
            _close_message_boxes(app)
            _pump(app, 0.2)
        except Exception:
            failures.append(f"round{round_no} 提示框层叠失败:\n{traceback.format_exc(limit=3)}")

        # 关闭：必须快速返回
        t0 = time.monotonic()
        dlg.reject()
        dt = time.monotonic() - t0
        if dt > 0.5:
            failures.append(f"round{round_no}: reject() 阻塞 {dt:.2f}s")
        _pump(app, 0.4)

        if not sip.isdeleted(dlg) and dlg.isVisible():
            # 有些弹窗（如 PsbActionDialog）故意拒绝在忙碌时关闭；这里再试 close()
            dlg.close()
            _pump(app, 0.3)

        if not sip.isdeleted(dlg) and dlg.isVisible() and cls_name == "ToolInstallProgressDialog":
            # 进度条运行中拒绝 Esc/关闭是设计如此（见 test_fluent_modal_safety.py），
            # 用官方 dismiss 入口收尾，验证其可被正常关闭。
            from chuni_eventer_desktop.ui.tool_install_progress import (
                dismiss_tool_install_progress,
            )

            dismiss_tool_install_progress(dlg)
            _pump(app, 0.3)
            notes.append(f"round{round_no}: 运行中拒绝 Esc（设计如此），改用 dismiss 关闭")

        if not sip.isdeleted(dlg) and dlg.isVisible():
            failures.append(f"round{round_no}: 关闭后仍可见")

        modal = QApplication.activeModalWidget()
        if modal is not None:
            failures.append(f"round{round_no}: 关闭后残留模态 {type(modal).__name__}")
        if not parent.isEnabled():
            failures.append(f"round{round_no}: 父窗口仍被禁用")
        if sip.isdeleted(dlg) and round_no == 1:
            first = None  # 已删除，round2 会重新构造

    # ---- 轮次 3：后台线程运行中关闭（检测是否回退成阻塞 wait） ----
    try:
        dlg3 = build_dialog(mod_name, cls_name, parent, tmp_dir)
    except Exception:
        dlg3 = None

    if dlg3 is not None:
        thread_attrs = [
            name
            for name in vars(dlg3)
            if name.endswith("_thread") or name == "_thread"
        ]
        if thread_attrs:
            fakes = {}
            for name in thread_attrs:
                if getattr(dlg3, name) is None:
                    fake = _FakeRunningThread()
                    setattr(dlg3, name, fake)
                    fakes[name] = fake
            if fakes:
                dlg3.show()
                _pump(app, 0.3)
                t0 = time.monotonic()
                dlg3.reject()
                dt = time.monotonic() - t0
                if dt > 0.5:
                    failures.append(f"线程运行中 reject() 阻塞 {dt:.2f}s")
                if dlg3.isVisible():
                    notes.append("线程运行中关闭：已隐藏并等待线程（预期行为）")
                for fake in fakes.values():
                    fake.running = False
                _pump(app, 0.4)
                # 兼容两种策略：延迟关闭（自动 reject）与忙碌时拒绝关闭（再点一次即可）
                if not sip.isdeleted(dlg3) and dlg3.isVisible():
                    dlg3.reject()
                    _pump(app, 0.5)
                if not sip.isdeleted(dlg3) and dlg3.isVisible():
                    failures.append("线程结束后弹窗仍未关闭")
                modal = QApplication.activeModalWidget()
                if modal is not None:
                    failures.append(f"线程结束后残留模态 {type(modal).__name__}")
            else:
                notes.append("无正在运行的后台线程属性可注入")
        else:
            notes.append("无后台线程属性")

    _close_message_boxes(app)
    _pump(app, 0.2)
    result["status"] = "pass" if not failures else "fail"
    return result


# ---------------------------------------------------------------------------
# 驱动：每个弹窗独立子进程
# ---------------------------------------------------------------------------


def _run_all(only: str | None) -> int:
    items = discover()
    if only:
        needle = only.lower()
        items = [it for it in items if needle in it[1].lower() or needle in it[0].lower()]
    print(f"共 {len(items)} 个弹窗待测\n")

    summary = {"pass": [], "fail": [], "skip": [], "construct_error": [], "timeout": []}
    results: list[dict[str, object]] = []

    for idx, (mod_name, cls_name, _sig) in enumerate(items, 1):
        cmd = [sys.executable, str(Path(__file__).resolve()), "--one", f"{mod_name}:{cls_name}"]
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=PER_DIALOG_TIMEOUT_S,
                cwd=ROOT,
            )
            raw = (proc.stdout or "").strip().splitlines()
            marked = [ln for ln in raw if ln.startswith("__RESULT__")]
            payload = (
                json.loads(marked[-1][len("__RESULT__") :])
                if marked
                else {"status": "fail", "failures": ["子进程无结果输出（可能崩溃）", (proc.stderr or "")[-1500:]]}
            )
            suspicious = [
                ln
                for ln in (proc.stderr or "").splitlines()
                if any(
                    key in ln
                    for key in (
                        "Destroyed while thread",
                        "wrapped C/C++ object",
                        "QThread: Destroyed",
                        "Segmentation",
                        "Aborted",
                    )
                )
            ]
            if suspicious:
                payload["stderr_flags"] = suspicious[:5]
        except subprocess.TimeoutExpired:
            payload = {
                "status": "timeout",
                "failures": [f"超过 {PER_DIALOG_TIMEOUT_S}s 未结束"],
                "notes": [],
            }
        elapsed = time.monotonic() - t0
        payload["elapsed"] = round(elapsed, 2)
        payload.setdefault("class", cls_name)
        payload.setdefault("module", mod_name)
        results.append(payload)
        status = str(payload.get("status"))
        summary.setdefault(status, []).append(cls_name)
        mark = {"pass": "ok", "skip": "--", "timeout": "HANG"}.get(status, "FAIL")
        print(f"[{idx:02d}/{len(items)}] {mark:4s} {cls_name:32s} {elapsed:5.1f}s")

    print("\n===== 汇总 =====")
    for key in ("pass", "fail", "construct_error", "skip", "timeout"):
        bucket = summary.get(key, [])
        if bucket:
            print(f"{key}: {len(bucket)}")

    flagged = [r for r in results if r.get("stderr_flags")]
    if flagged:
        print(f"stderr 异常告警: {len(flagged)}")
        for r in flagged:
            print(f"  {r.get('class')}: {r.get('stderr_flags')[:2]}")

    problems = [r for r in results if r.get("status") in ("fail", "timeout", "construct_error")]
    for r in problems:
        print(f"\n--- {r.get('class')} ({r.get('status')}) ---")
        for f in r.get("failures", [])[:6]:
            print(str(f)[:1200])
        for n in r.get("notes", [])[:6]:
            print(f"note: {n}")

    out = ROOT / "docs" / "Code Review" / "dialog_stress_results_2026-10-24.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {out}")
    return 0 if not summary.get("timeout") and not summary.get("fail") else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--one", default=None, help="module:Class，在子进程内单跑")
    args = ap.parse_args()

    if args.list:
        _inventory()
        return 0
    if args.one:
        mod_name, cls_name = args.one.split(":", 1)
        payload = _run_one(mod_name, cls_name)
        print("__RESULT__" + json.dumps(payload, ensure_ascii=False))
        return 0
    return _run_all(args.only)


if __name__ == "__main__":
    raise SystemExit(main())
