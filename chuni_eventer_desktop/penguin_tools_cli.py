from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .acus_workspace import app_root_dir


def _candidate_cli_paths() -> list[Path]:
    env = os.environ.get("CHUNI_PENGUINTOOLS_CLI", "").strip()
    out: list[Path] = []
    if env:
        out.append(Path(env).expanduser().resolve())

    root = app_root_dir()
    cwd = Path.cwd().resolve()
    exe_dir = Path(sys.executable).resolve().parent
    sibling_penguin_tools = root.parent / "PenguinTools"
    bundled_publish_embedded = Path(
        "PenguinTools.CLI/bin/Release/net10.0/publish/WinX64-SelfContained-SingleFile-EmbeddedAssets"
    )
    bundled_publish_external = Path(
        "PenguinTools.CLI/bin/Release/net10.0/publish/WinX64-SelfContained-SingleFile-ExternalAssets"
    )

    out.extend(
        [
            (root / ".tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (root / "tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (root / "PenguinTools.CLI.exe").resolve(),
            (exe_dir / ".tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (exe_dir / "PenguinTools.CLI.exe").resolve(),
            (cwd / ".tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (cwd / "PenguinTools.CLI.exe").resolve(),
            (root / "PenguinTools" / bundled_publish_embedded / "PenguinTools.CLI.exe").resolve(),
            (sibling_penguin_tools / bundled_publish_embedded / "PenguinTools.CLI.exe").resolve(),
            (root / "PenguinTools" / bundled_publish_external / "PenguinTools.CLI.exe").resolve(),
            (sibling_penguin_tools / bundled_publish_external / "PenguinTools.CLI.exe").resolve(),
            (root / "PenguinTools" / "PenguinTools.CLI" / "bin" / "Release" / "net10.0" / "PenguinTools.CLI.dll")
            .resolve(),
            (sibling_penguin_tools / "PenguinTools.CLI" / "bin" / "Release" / "net10.0" / "PenguinTools.CLI.dll")
            .resolve(),
        ]
    )

    unique: list[Path] = []
    seen: set[str] = set()
    for path in out:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def resolve_penguin_tools_cli() -> Path | None:
    for path in _candidate_cli_paths():
        if path.exists() and path.is_file():
            return path
    return None


def explain_penguin_tools_cli_lookup() -> str:
    env = os.environ.get("CHUNI_PENGUINTOOLS_CLI", "").strip()
    lines = [f"- {path}" for path in _candidate_cli_paths()]
    env_line = env if env else "(empty)"
    return "CHUNI_PENGUINTOOLS_CLI=" + env_line + "\nTried paths:\n" + "\n".join(lines)


def _command_prefix(cli_path: Path) -> list[str]:
    suffix = cli_path.suffix.lower()
    if suffix == ".dll":
        return ["dotnet", str(cli_path)]
    if suffix == ".csproj":
        return ["dotnet", "run", "--project", str(cli_path), "--configuration", "Release", "--"]
    return [str(cli_path)]


def _run_penguin_tools_cli(args: list[str]) -> dict[str, Any]:
    cli_path = resolve_penguin_tools_cli()
    if cli_path is None:
        raise FileNotFoundError(
            "未找到 PenguinTools.CLI。可设置环境变量 CHUNI_PENGUINTOOLS_CLI 指向可执行文件、.dll 或 .csproj。\n"
            + explain_penguin_tools_cli_lookup()
        )

    cmd = [*_command_prefix(cli_path), "--no-pretty", *args]
    process = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=os.environ.copy(),
    )

    stdout = process.stdout.strip()
    stderr = process.stderr.strip()
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "PenguinTools.CLI 未返回可解析的 JSON。\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{stdout or '(empty)'}\n"
            f"stderr:\n{stderr or '(empty)'}"
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeError(
            "PenguinTools.CLI 返回了意外的响应格式。\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{stdout or '(empty)'}\n"
            f"stderr:\n{stderr or '(empty)'}"
        )

    if process.returncode != 0 or not payload.get("success", False):
        message = str(payload.get("message") or "").strip()
        raise RuntimeError(
            "PenguinTools.CLI 调用失败：\n"
            f"cmd: {' '.join(cmd)}\n"
            f"message: {message or '(empty)'}\n"
            f"stdout:\n{stdout or '(empty)'}\n"
            f"stderr:\n{stderr or '(empty)'}"
        )

    return payload


def convert_chart_with_penguin_tools_cli(*, input_path: Path, output_path: Path) -> Path:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _run_penguin_tools_cli(["chart", "convert", str(input_path), str(output_path)])
    data = payload.get("data") or {}
    resolved_output = Path(str(data.get("outputPath") or output_path)).resolve()
    if not resolved_output.is_file():
        raise RuntimeError(
            "PenguinTools.CLI 报告成功，但未生成输出 c2s 文件。\n"
            f"input: {input_path}\n"
            f"expected output: {resolved_output}"
        )
    return resolved_output


def convert_chart_text_with_penguin_tools_cli(*, text: str, suffix: str) -> str:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    with tempfile.TemporaryDirectory(prefix="chuni-eventer-penguin-cli-") as tmp_dir:
        temp_root = Path(tmp_dir)
        input_path = temp_root / f"input{suffix}"
        output_path = temp_root / "output.c2s"
        input_path.write_text(text, encoding="utf-8")
        converted = convert_chart_with_penguin_tools_cli(input_path=input_path, output_path=output_path)
        return converted.read_text(encoding="utf-8")
