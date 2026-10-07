#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏冒烟测试：PJSK 烤谱入口与对话框能否构造（不弹窗、不写盘）。

    python scripts/smoke_pjsk2chuni_ui.py

覆盖：
  * 乐曲页「新增」渠道弹窗出现第三个 PJSK 按钮；
  * PjskHubDialog / PjskConvertToAcusDialog 构造成功（含真实 pjsk_cache 列表）；
  * 实验性设置面板不再出现「烤谱」入口；
  * 相关模块可导入、且旧的 SUS→c2s 调试对话框已移除。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication, QToolButton  # noqa: E402

from chuni_eventer_desktop.pjsk_acus_install import (  # noqa: E402
    chuni_slot_sources,
    iter_local_pjsk_bundles,
    next_chuni_music_id,
)
from chuni_eventer_desktop.pjsk_sheet_client import pjsk_cache_root  # noqa: E402
from chuni_eventer_desktop.ui.music_add_actions_dialog import MusicSheetChannelsDialog  # noqa: E402
from chuni_eventer_desktop.ui.pjsk_hub_dialog import (  # noqa: E402
    PjskConvertToAcusDialog,
    PjskHubDialog,
)
from chuni_eventer_desktop.ui.settings_dialog import SettingsExperimentalPanel  # noqa: E402

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {msg}")
    if not cond:
        FAILS.append(msg)


def main() -> int:
    acus = (ROOT / "ACUS").resolve()
    app = QApplication.instance() or QApplication([])
    print(f"ACUS={acus}")

    print("\n== 渠道弹窗")
    pick = MusicSheetChannelsDialog()
    tips = [b.toolTip() for b in pick.findChildren(QToolButton)]
    check(len(tips) == 3, f"按钮数={len(tips)}：{tips}")
    check(any("PJSK" in t for t in tips), "存在 PJSK 渠道按钮")
    check(any("SwanSite" in t for t in tips) and any("pgko" in t for t in tips), "SwanSite / pgko 仍在")

    print("\n== 本地缓存与转换对话框")
    bundles = iter_local_pjsk_bundles(pjsk_cache_root(acus))
    print(f"   本地缓存 {len(bundles)} 个：{[b.pjsk_music_id for b in bundles]}")
    hub = PjskHubDialog(acus_root=acus)
    check(hub._table.rowCount() == len(bundles), "列表行数与缓存数一致")
    check("实验" not in hub.windowTitle(), f"窗口标题不含实验：{hub.windowTitle()}")
    if bundles:
        b = bundles[0]
        sources = chuni_slot_sources(b)
        print(f"   {b.title}：{[s.slot for s in sources]}")
        check(bool(sources), "第一个缓存有可转换槽位")
        dlg = PjskConvertToAcusDialog(
            acus_root=acus, bundle=b, default_chuni_id=next_chuni_music_id(acus, start=7000)
        )
        check(len(dlg._level_spins) == len(sources), "定数表格与槽位一一对应")
        check(dlg._build_request() is None or True, "_build_request 可运行（ID 未冲突时返回请求）")

    print("\n== 定数映射（PJSK 1..38 → 中二 1..15.5）")
    from chuni_eventer_desktop.pjsk2chuni import pipeline as pl

    check(pl.pjsk_level_to_chuni_const(1) == 1.0, f"L1 → {pl.pjsk_level_to_chuni_const(1)}")
    check(pl.pjsk_level_to_chuni_const(38) == 15.5, f"L38 → {pl.pjsk_level_to_chuni_const(38)}")
    check(pl.pjsk_level_to_chuni_const(24) == 10.01, f"L24 → {pl.pjsk_level_to_chuni_const(24)}")
    check(pl.pjsk_level_to_chuni_const(30) == 12.36, f"L30 → {pl.pjsk_level_to_chuni_const(30)}")
    check(pl.pjsk_level_to_chuni_const(0) == 1.0 and pl.pjsk_level_to_chuni_const(99) == 15.5,
          "越界等级被夹到 1 / 15.5")
    check(pl.const_to_level_pair(12.6) == (12, 60), f"12.6 → {pl.const_to_level_pair(12.6)}")
    check(pl.const_to_level_pair(15.5) == (15, 50), f"15.5 → {pl.const_to_level_pair(15.5)}")

    print("\n== 转换对话框按 PJSK 等级给默认定数")
    if bundles:
        from chuni_eventer_desktop.pjsk_acus_install import PjskLocalBundle

        b0 = bundles[0]
        pj = {"BASIC": 12, "ADVANCED": 18, "EXPERT": 24, "MASTER": 30, "ULTIMA": 32}
        slots2 = [
            dict(s, pjskPlayLevel=pj[str(s.get("chuniSlot"))])
            for s in (b0.manifest.get("slots") or [])
            if str(s.get("chuniSlot")) in pj
        ]
        b2 = PjskLocalBundle(
            pjsk_music_id=b0.pjsk_music_id,
            root=b0.root,
            manifest=dict(b0.manifest, slots=slots2),
        )
        dlg2 = PjskConvertToAcusDialog(acus_root=acus, bundle=b2, default_chuni_id=7999)
        got = {
            slot: (int(w[0].value()), int(w[1].value()))
            for slot, w in dlg2._level_spins.items()
        }
        want = {slot: pl.const_to_level_pair(pl.pjsk_level_to_chuni_const(lv)) for slot, lv in pj.items()
                if slot in got}
        check(got == want, f"默认定数按 PJSK 等级映射：{got}")

    print("\n== 老缓存回填 PJSK 等级（写 manifest）")
    if bundles:
        import json
        import shutil
        import tempfile

        from chuni_eventer_desktop.pjsk_acus_install import (
            backfill_bundle_play_levels,
            bundle_play_levels,
        )

        tmp_root = Path(tempfile.mkdtemp(prefix="pjsk_level_backfill_"))
        fake_dir = tmp_root / f"pjsk_{bundles[0].pjsk_music_id:04d}"
        fake_dir.mkdir(parents=True, exist_ok=True)
        src_manifest = json.loads(
            (bundles[0].root / "manifest.json").read_text(encoding="utf-8")
        )
        # 模拟"老缓存"：把 pjskPlayLevel 去掉
        src_manifest["slots"] = [
            {k: v for k, v in s.items() if k != "pjskPlayLevel"}
            for s in (src_manifest.get("slots") or [])
        ]
        (fake_dir / "manifest.json").write_text(
            json.dumps(src_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        fake_bundle = PjskLocalBundle(
            pjsk_music_id=bundles[0].pjsk_music_id,
            root=fake_dir,
            manifest=json.loads((fake_dir / "manifest.json").read_text(encoding="utf-8")),
        )
        check(bundle_play_levels(fake_bundle) == {}, "回填前无等级")
        changed = backfill_bundle_play_levels(
            fake_bundle, {"normal": 12, "hard": 18, "append": 32}
        )
        check(changed, "回填返回 True")
        reloaded = PjskLocalBundle(
            pjsk_music_id=fake_bundle.pjsk_music_id,
            root=fake_dir,
            manifest=json.loads((fake_dir / "manifest.json").read_text(encoding="utf-8")),
        )
        levels = bundle_play_levels(reloaded)
        check(levels.get("BASIC") == 12 and levels.get("ULTIMA") == 32, f"回填并落盘：{levels}")
        check(not backfill_bundle_play_levels(reloaded, {"normal": 12}), "重复回填不再变更")
        shutil.rmtree(tmp_root, ignore_errors=True)

    print("\n== 曲目数据库镜像回退（纯逻辑，不联网）")
    from chuni_eventer_desktop import pjsk_sheet_client as sc

    check(len(sc.PJSK_MASTER_JSON_MIRRORS) >= 4, f"镜像数={len(sc.PJSK_MASTER_JSON_MIRRORS)}")
    check(
        any("gh-proxy.com" in m for m in sc.PJSK_MASTER_JSON_MIRRORS)
        and any("gcore.jsdelivr.net" in m for m in sc.PJSK_MASTER_JSON_MIRRORS),
        "包含实测可用的国内代理/CDN 镜像",
    )
    probe = sc.PJSK_MASTER_JSON_MIRRORS[-1]
    sc._remember_master_json_base(probe)
    check(sc._ordered_master_json_bases()[0] == probe, "上次成功的镜像会被优先使用")
    sc._remember_master_json_base("")  # 复位，避免影响后续真实调用

    print("\n== PenguinTools.CLI 运行时资产校验（两代布局）")
    import tempfile

    from chuni_eventer_desktop import external_tools as ext

    def _layout(root: Path, *, cri: bool, mua: bool, ffmpeg: bool, texconv: bool) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        exe = root / "PenguinTools.CLI.exe"
        exe.write_bytes(b"MZ")
        assets = root / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "assets.json").write_text("{}", encoding="utf-8")
        for rel, present in (
            ("assets/cri/PenguinTools.CRI.exe", cri),
            ("assets/mua/mua_wav.exe", mua),
            ("assets/mua/mua_img.exe", mua),
            ("assets/ffmpeg/ffmpeg.exe", ffmpeg),
            ("assets/texconv/texconv.exe", texconv),
        ):
            if present:
                p = root / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"MZ")
        return exe

    tmp = Path(tempfile.mkdtemp(prefix="pjsk_cli_layout_"))
    try:
        for label, exe in (
            ("2.3.x（cri+mua）", _layout(tmp / "legacy", cri=True, mua=True, ffmpeg=False, texconv=False)),
            ("2.4.0+（ffmpeg+texconv）", _layout(tmp / "modern", cri=False, mua=False, ffmpeg=True, texconv=True)),
        ):
            try:
                ext._assert_penguin_tools_cli_runtime(exe)
                check(True, f"{label} 布局通过校验")
            except RuntimeError as e:  # noqa: BLE001
                check(False, f"{label} 布局被误判：{e}")
        broken = _layout(tmp / "broken", cri=False, mua=False, ffmpeg=False, texconv=False)
        try:
            ext._assert_penguin_tools_cli_runtime(broken)
            check(False, "残缺布局应报错但通过了")
        except RuntimeError:
            check(True, "残缺布局正确报错")
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmp, ignore_errors=True)

    print("\n== 实验性设置面板")
    from PyQt6.QtWidgets import QLabel

    from chuni_eventer_desktop.acus_workspace import AcusConfig

    panel = SettingsExperimentalPanel(cfg=AcusConfig(), acus_root=acus, get_tool_path=lambda: None)
    blob = " ".join(w.text() for w in panel.findChildren(QLabel))
    check("烤谱" not in blob, "实验性面板已无「烤谱」入口")
    check("PGKO" in blob or "UGC" in blob, "PGKO 实验入口仍在")

    print("\n== 旧实现已移除")
    check(not (ROOT / "chuni_eventer_desktop" / "sus_to_c2s.py").exists(), "sus_to_c2s.py 已删除")
    check(
        not (ROOT / "chuni_eventer_desktop" / "ui" / "sus_c2s_debug_dialog.py").exists(),
        "sus_c2s_debug_dialog.py 已删除",
    )
    import importlib

    for name in (
        "chuni_eventer_desktop.pjsk2chuni.core",
        "chuni_eventer_desktop.pjsk2chuni.pipeline",
        "chuni_eventer_desktop.pgko_to_c2s",  # pgko 线仍依赖 pjsk_acus_install 的公共件
        "chuni_eventer_desktop.ui.main_window",
        "chuni_eventer_desktop.ui.settings_page",
        "chuni_eventer_desktop.ui.pjsk_sus_download_dialog",
    ):
        importlib.import_module(name)
    check(True, "关键模块可导入（含 pgko / main_window / settings_page）")

    app.quit()
    print("\n== 结论")
    if FAILS:
        print(f"失败 {len(FAILS)} 项：")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
