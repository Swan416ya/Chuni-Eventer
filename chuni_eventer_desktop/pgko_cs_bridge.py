from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .acus_workspace import app_root_dir


def _candidate_bridge_paths() -> list[Path]:
    env = os.environ.get("CHUNI_PENGUIN_BRIDGE", "").strip()
    out: list[Path] = []
    if env:
        out.append(Path(env).expanduser().resolve())
    root = app_root_dir()
    cwd = Path.cwd().resolve()
    exe_dir = Path(sys.executable).resolve().parent
    out.extend(
        [
            (root / ".tools" / "PenguinBridge" / "PenguinBridge.exe").resolve(),
            (root / "tools" / "PenguinBridge" / "bin" / "Release" / "net8.0" / "PenguinBridge.exe").resolve(),
            (root / "PenguinBridge.exe").resolve(),
            (exe_dir / ".tools" / "PenguinBridge" / "PenguinBridge.exe").resolve(),
            (exe_dir / "PenguinBridge.exe").resolve(),
            (cwd / ".tools" / "PenguinBridge" / "PenguinBridge.exe").resolve(),
            (cwd / "PenguinBridge.exe").resolve(),
        ]
    )
    # De-duplicate while preserving order.
    unique: list[Path] = []
    seen: set[str] = set()
    for p in out:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def resolve_penguin_bridge() -> Path | None:
    for p in _candidate_bridge_paths():
        if p.exists() and p.is_file():
            return p
    return None


def explain_penguin_bridge_lookup() -> str:
    env = os.environ.get("CHUNI_PENGUIN_BRIDGE", "").strip()
    lines = [f"- {p}" for p in _candidate_bridge_paths()]
    env_line = env if env else "(empty)"
    return (
        "CHUNI_PENGUIN_BRIDGE="
        + env_line
        + "\nTried paths:\n"
        + "\n".join(lines)
    )


def convert_mgxc_with_penguin_bridge(*, input_mgxc: Path, output_c2s: Path) -> None:
    bridge = resolve_penguin_bridge()
    if bridge is None:
        raise FileNotFoundError(
            "未找到 PenguinBridge.exe。可设置环境变量 CHUNI_PENGUIN_BRIDGE 指向 bridge 可执行文件。\n"
            + explain_penguin_bridge_lookup()
        )
    cmd = [
        str(bridge),
        "mgxc-to-c2s",
        "--in",
        str(input_mgxc),
        "--out",
        str(output_c2s),
    ]
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.returncode != 0:
        err_blob = f"{p.stdout or ''}\n{p.stderr or ''}"
        tip = ""
        if "PenguinTools.Core" in err_blob:
            tip = (
                "\n\n提示：PenguinBridge 需要 Foahh/PenguinTools 的 PenguinTools.Core。"
                "请先在本仓库根目录运行 scripts\\setup_penguin_tools.ps1 克隆依赖，"
                "再执行 dotnet build tools\\PenguinBridge\\PenguinBridge.csproj -c Release，"
                "或设置 CHUNI_PENGUIN_TOOLS_CORE_DLL 指向 PenguinTools.Core.dll。"
            )
        raise RuntimeError(
            "PenguinBridge 转换失败：\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{p.stdout or '(empty)'}\n"
            f"stderr:\n{p.stderr or '(empty)'}"
            f"{tip}"
        )
    if not output_c2s.exists():
        raise RuntimeError("PenguinBridge 未生成输出 c2s 文件。")

