#!/usr/bin/env python3
"""验证 external_tools 可自动下载的工具 URL 与 install_tool 流程。"""
from __future__ import annotations

import shutil
import ssl
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _probe_url(url: str, *, timeout: float = 30.0) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Chuni-Eventer/1.0"}, method="HEAD")
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            code = getattr(resp, "status", 200)
            if code in (200, 302, 301):
                return True, f"HTTP {code}"
            return False, f"HTTP {code}"
    except Exception as e:
        # 部分 CDN 不支持 HEAD，改用 Range GET
        try:
            req2 = urllib.request.Request(
                url,
                headers={"User-Agent": "Chuni-Eventer/1.0", "Range": "bytes=0-0"},
                method="GET",
            )
            with urllib.request.urlopen(req2, timeout=timeout, context=ctx) as resp:
                return True, f"GET ok (status {getattr(resp, 'status', '?')})"
        except Exception as e2:
            return False, f"{e}; fallback: {e2}"


def main() -> int:
    from chuni_eventer_desktop.acus_workspace import AcusConfig
    from chuni_eventer_desktop.external_tools import (
        ALL_TOOLS,
        missing_auto_download_tools,
        install_tool,
        resolve_tool_path,
    )

    auto_tools = [t for t in ALL_TOOLS if t.download_url]
    manual_tools = [t for t in ALL_TOOLS if not t.download_url]

    print("=== 可应用内下载的工具 ===")
    for t in auto_tools:
        ok, msg = _probe_url(t.download_url or "")
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {t.name}: {msg}")
        print(f"         {t.download_url}")
    print()
    print("=== 需手动 / 懒人包自带的工具（无 download_url）===")
    for t in manual_tools:
        print(f"  - {t.name}（{t.help_url or '见文档'}）")
    print()

    if not all(_probe_url(t.download_url or "")[0] for t in auto_tools):
        print("URL 探测失败，跳过安装测试。")
        return 1

    tmp = Path(tempfile.mkdtemp(prefix="chuni_tool_install_test_"))
    print(f"=== install_tool 实测（隔离目录）===\n  {tmp}\n")
    try:
        with patch("chuni_eventer_desktop.acus_workspace.app_root_dir", return_value=tmp):
            cfg = AcusConfig()
            for spec in auto_tools:
                dest = tmp / ".tools" / spec.default_rel
                if dest.is_file():
                    dest.unlink()
                if spec.archive_kind == "exe" and dest.parent.is_dir():
                    shutil.rmtree(dest.parent, ignore_errors=True)
                print(f"  安装 {spec.name} …")
                try:
                    path = install_tool(
                        spec,
                        cfg,
                        on_progress=lambda m, pct, n=spec.name: print(
                            f"    [{n}] {m.split(chr(10))[0]}"
                            + (f" ({pct}%)" if pct is not None else "")
                        ),
                    )
                    if not path.is_file():
                        print(f"  [FAIL] {spec.name}: 返回路径不是文件 {path}")
                        return 1
                    print(f"  [OK] {spec.name} -> {path} ({path.stat().st_size} bytes)")
                except Exception as e:
                    print(f"  [FAIL] {spec.name}: {e}")
                    return 1

            missing = missing_auto_download_tools(cfg)
            if missing:
                print(f"  [FAIL] 安装后仍缺失: {[t.name for t in missing]}")
                return 1

            with patch("chuni_eventer_desktop.acus_workspace.app_root_dir", return_value=tmp):
                for spec in auto_tools:
                    p = resolve_tool_path(spec, cfg)
                    if p is None or not p.is_file():
                        print(f"  [FAIL] resolve {spec.name} -> {p}")
                        return 1
                    print(f"  [OK] resolve {spec.name} -> {p}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n全部可下载工具安装与解析测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
