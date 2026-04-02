from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .acus_workspace import app_root_dir


def _candidate_bridge_paths() -> list[Path]:
    env = os.environ.get("CHUNI_PENGUIN_BRIDGE", "").strip()
    out: list[Path] = []
    if env:
        out.append(Path(env).expanduser().resolve())
    root = app_root_dir()
    out.extend(
        [
            (root / ".tools" / "PenguinBridge" / "PenguinBridge.exe").resolve(),
            (root / "tools" / "PenguinBridge" / "bin" / "Release" / "net8.0" / "PenguinBridge.exe").resolve(),
            (root / "PenguinBridge.exe").resolve(),
        ]
    )
    return out


def resolve_penguin_bridge() -> Path | None:
    for p in _candidate_bridge_paths():
        if p.exists() and p.is_file():
            return p
    return None


def convert_mgxc_with_penguin_bridge(*, input_mgxc: Path, output_c2s: Path) -> None:
    bridge = resolve_penguin_bridge()
    if bridge is None:
        raise FileNotFoundError(
            "未找到 PenguinBridge.exe。可设置环境变量 CHUNI_PENGUIN_BRIDGE 指向 bridge 可执行文件。"
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
        raise RuntimeError(
            "PenguinBridge 转换失败：\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{p.stdout or '(empty)'}\n"
            f"stderr:\n{p.stderr or '(empty)'}"
        )
    if not output_c2s.exists():
        raise RuntimeError("PenguinBridge 未生成输出 c2s 文件。")

