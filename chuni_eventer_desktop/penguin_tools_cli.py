from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .acus_workspace import app_root_dir

# PenguinTools.CLI 发布目录名（位于 .../net10.0/publish/ 下；仅 Native AOT）。
_PUBLISH_PROFILES = (
    "WinX64-NativeAOT",
)


def _format_cli_message(message: Any) -> str:
    """将 CLI 的 message / 诊断 message（字符串或 MessageDescriptor）格式化为可读文本。"""
    if message is None:
        return ""
    if isinstance(message, str):
        return message.strip()
    if not isinstance(message, dict):
        return str(message).strip()

    key = str(message.get("key") or "").strip()
    args = message.get("args")
    if not isinstance(args, dict) or not args:
        return key

    numbered: list[str] = []
    for i in range(16):
        if f"arg{i}" not in args:
            if i == 0:
                break
            continue
        numbered.append(str(args[f"arg{i}"]))
    if numbered:
        detail = "; ".join(numbered)
        return f"{key}: {detail}" if key else detail

    # 常见命名占位符（例如 diag.error.unhandled → args.detail）。
    for named in ("detail", "path", "file", "value"):
        if named in args and args[named] is not None:
            detail = str(args[named])
            return f"{key}: {detail}" if key else detail

    extras = ", ".join(f"{k}={v}" for k, v in args.items())
    return f"{key} ({extras})" if key else extras


def _format_penguin_tools_cli_failure(
    *,
    cmd: list[str],
    payload: dict[str, Any],
    stdout: str,
    stderr: str,
) -> str:
    lines = ["PenguinTools.CLI 调用失败：", f"cmd: {' '.join(cmd)}"]
    message = _format_cli_message(payload.get("message"))
    if message:
        lines.append(f"message: {message}")

    diagnostics = payload.get("diagnostics") or []
    errors: list[str] = []
    warnings: list[str] = []
    if isinstance(diagnostics, list):
        for item in diagnostics:
            if not isinstance(item, dict):
                continue
            sev = str(item.get("severity") or "").strip().lower()
            text = _format_cli_message(item.get("message"))
            path = str(item.get("path") or "").strip()
            if path and text:
                text = f"{text} ({path})"
            elif path and not text:
                text = path
            if not text:
                continue
            if sev == "error":
                errors.append(text)
            elif sev == "warning":
                warnings.append(text)

    if errors:
        lines.append("错误：")
        lines.extend(f"- {msg}" for msg in errors[:20])
    if warnings:
        shown = warnings[:5]
        extra = len(warnings) - len(shown)
        suffix = f"（另有 {extra} 条未显示）" if extra > 0 else ""
        lines.append(f"警告{suffix}：")
        lines.extend(f"- {msg}" for msg in shown)

    lines.append("详情：")
    lines.append(json.dumps(payload, ensure_ascii=False, indent=2))
    if stderr.strip():
        lines.append(f"stderr:\n{stderr.strip()}")
    elif not stdout.strip():
        lines.append("stdout: (empty)")
    return "\n".join(lines)


def _candidate_cli_paths() -> list[Path]:
    env = os.environ.get("CHUNI_PENGUINTOOLS_CLI", "").strip()
    out: list[Path] = []
    if env:
        out.append(Path(env).expanduser().resolve())

    root = app_root_dir()
    cwd = Path.cwd().resolve()
    exe_dir = Path(sys.executable).resolve().parent
    sibling_penguin_tools = root.parent / "PenguinTools"
    butler_penguin_tools = root.parent / "penguin-butler" / "external" / "PenguinTools"

    out.extend(
        [
            (root / ".tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (root / "tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (root / "PenguinTools.CLI.exe").resolve(),
            (exe_dir / ".tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (exe_dir / "PenguinTools.CLI.exe").resolve(),
            (cwd / ".tools" / "PenguinToolsCLI" / "PenguinTools.CLI.exe").resolve(),
            (cwd / "PenguinTools.CLI.exe").resolve(),
        ]
    )

    for penguin_root in (root / "PenguinTools", sibling_penguin_tools, butler_penguin_tools):
        for profile in _PUBLISH_PROFILES:
            out.append(
                (penguin_root / "PenguinTools.CLI" / "bin" / "Release" / "net10.0" / "publish" / profile / "PenguinTools.CLI.exe").resolve()
            )
        out.append(
            (penguin_root / "PenguinTools.CLI" / "bin" / "Release" / "net10.0" / "PenguinTools.CLI.dll").resolve()
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


def resolve_penguin_tools_cli(cfg: object | None = None) -> Path | None:
    if cfg is None:
        from .acus_workspace import AcusConfig

        cfg = AcusConfig.load()
    from .external_tools import TOOL_PENGUINTOOLS_CLI, resolve_tool_path

    p = resolve_tool_path(TOOL_PENGUINTOOLS_CLI, cfg)  # type: ignore[arg-type]
    if p is not None:
        return p
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


def _parse_cli_result_payload(stdout: str) -> dict[str, Any] | None:
    """
    解析 PenguinTools.CLI 标准输出。

    输出为 NDJSON：可选的 ``type=progress`` 行，最后一行 ``type=result``（schemaVersion 4）。
    """
    text = (stdout or "").strip()
    if not text:
        return None

    # 整段 stdout 恰好是一个 JSON 对象时走快路径。
    try:
        payload = json.loads(text)
        if isinstance(payload, dict) and str(payload.get("type") or "").lower() == "result":
            return payload
    except json.JSONDecodeError:
        pass

    result: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if str(obj.get("type") or "").strip().lower() == "result":
            result = obj
    return result


def _run_penguin_tools_cli(args: list[str], *, cfg: object | None = None) -> dict[str, Any]:
    cli_path = resolve_penguin_tools_cli(cfg)
    if cli_path is None:
        raise FileNotFoundError(
            "未找到 PenguinTools.CLI。可设置环境变量 CHUNI_PENGUINTOOLS_CLI 指向可执行文件、.dll 或 .csproj。\n"
            + explain_penguin_tools_cli_lookup()
        )

    # ``--no-progress`` 挂在子命令上；未声明该选项的命令（如 jacket/audio convert）不能传。
    cmd_args = list(args)
    if _supports_no_progress(cmd_args) and "--no-progress" not in cmd_args:
        cmd_args.append("--no-progress")

    cmd = [*_command_prefix(cli_path), *cmd_args]
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
    payload = _parse_cli_result_payload(stdout)

    if payload is None:
        raise RuntimeError(
            "PenguinTools.CLI 未返回可解析的 JSON。\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{stdout or '(empty)'}\n"
            f"stderr:\n{stderr or '(empty)'}"
        )

    if process.returncode != 0 or not payload.get("success", False):
        raise RuntimeError(
            _format_penguin_tools_cli_failure(
                cmd=cmd,
                payload=payload,
                stdout=stdout,
                stderr=stderr,
            )
        )

    return payload


def _supports_no_progress(args: list[str]) -> bool:
    """当前调用链里需要抑制进度输出的子命令。"""
    if len(args) < 2:
        return False
    return (args[0], args[1]) == ("chart", "convert")


def convert_chart_with_penguin_tools_cli(
    *, input_path: Path, output_path: Path, cfg: object | None = None
) -> Path:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _run_penguin_tools_cli(
        ["chart", "convert", str(input_path), str(output_path)],
        cfg=cfg,
    )
    data = payload.get("data") or {}
    resolved_output = Path(str(data.get("outputPath") or output_path)).resolve()
    if not resolved_output.is_file():
        raise RuntimeError(
            "PenguinTools.CLI 报告成功，但未生成输出 c2s 文件。\n"
            f"input: {input_path}\n"
            f"expected output: {resolved_output}"
        )
    return resolved_output


def convert_chart_text_with_penguin_tools_cli(
    *, text: str, suffix: str, cfg: object | None = None
) -> str:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    with tempfile.TemporaryDirectory(prefix="chuni-eventer-penguin-cli-") as tmp_dir:
        temp_root = Path(tmp_dir)
        input_path = temp_root / f"input{suffix}"
        output_path = temp_root / "output.c2s"
        input_path.write_text(text, encoding="utf-8")
        converted = convert_chart_with_penguin_tools_cli(
            input_path=input_path,
            output_path=output_path,
            cfg=cfg,
        )
        return converted.read_text(encoding="utf-8")


def _artifact_path(payload: dict[str, Any], kind: str) -> Path | None:
    data = payload.get("data") or {}
    for item in data.get("artifacts") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("kind") or "") != kind:
            continue
        raw = str(item.get("path") or "").strip()
        if raw:
            return Path(raw).resolve()
    return None


def cli_song_id_from_payload(payload: dict[str, Any]) -> int | None:
    chart = (payload.get("data") or {}).get("chart") or {}
    sid = chart.get("songId")
    if sid is None:
        return None
    try:
        return int(sid)
    except (TypeError, ValueError):
        return None


def cue_bundle_dir_from_audio_payload(payload: dict[str, Any]) -> Path:
    acb = _artifact_path(payload, "audio.acb")
    if acb is not None and acb.is_file():
        return acb.parent

    data = payload.get("data") or {}
    out_dir = str(data.get("outputDirectory") or "").strip()
    if out_dir:
        root = Path(out_dir).resolve()
        for cand in sorted(root.glob("cueFile*")):
            if cand.is_dir() and (cand / "CueFile.xml").is_file():
                return cand

    raise RuntimeError(
        "PenguinTools.CLI 音频导出成功，但未找到 cueFile 目录。\n"
        f"payload data: {json.dumps(data, ensure_ascii=False)}"
    )


def _patch_acb_cue_names(acb_path: Path, *, music_id: int) -> None:
    try:
        from PyCriCodecsEx.acb import ACB
        from PyCriCodecsEx.chunk import UTFTypeValues
        from PyCriCodecsEx.utf import UTFBuilder
    except ImportError as e:
        raise RuntimeError(
            "需要 PyCriCodecsEx 才能将 PenguinTools 导出的 ACB 重命名为目标 music ID。"
        ) from e

    mid = int(music_id)
    cue_name = f"cueFile{mid:06d}"
    acb = ACB(str(acb_path))
    acb.view.Name = cue_name
    hash_rows = acb.payload.get("StreamAwbHash")
    if hash_rows and len(hash_rows) > 1 and hash_rows[1]:
        hash_rows[1][0]["Name"] = (UTFTypeValues.string, cue_name)
    acb_path.write_bytes(
        UTFBuilder(acb.dictarray, encoding=acb.encoding, table_name=acb.table_name).bytes()
    )


def relocate_cue_bundle_for_music_id(cue_dir: Path, *, music_id: int) -> Path:
    """
    将 PenguinTools 导出的 cueFile 目录对齐到目标 music ID（含 ACB 内 cue 名与 CueFile.xml）。
    """
    from .pjsk_audio_chuni import _write_cue_file_xml

    cue_dir = cue_dir.resolve()
    mid = int(music_id)
    target = cue_dir.parent / f"cueFile{mid:06d}"
    music_tag = f"music{mid:04d}"
    target_acb = target / f"{music_tag}.acb"
    target_awb = target / f"{music_tag}.awb"

    if (
        cue_dir == target
        and target_acb.is_file()
        and target_awb.is_file()
        and (target / "CueFile.xml").is_file()
    ):
        _patch_acb_cue_names(target_acb, music_id=mid)
        _write_cue_file_xml(target, music_id=mid)
        return target

    acb_src = next(iter(sorted(cue_dir.glob("music*.acb"))), None)
    awb_src = next(iter(sorted(cue_dir.glob("music*.awb"))), None)
    if acb_src is None or awb_src is None:
        raise RuntimeError(f"未在 {cue_dir} 找到 music*.acb / music*.awb")

    if target.exists() and target != cue_dir:
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(awb_src, target_awb)
    shutil.copy2(acb_src, target_acb)
    _patch_acb_cue_names(target_acb, music_id=mid)
    _write_cue_file_xml(target, music_id=mid)

    if cue_dir != target and cue_dir.is_dir():
        shutil.rmtree(cue_dir, ignore_errors=True)
    return target


def convert_jacket_with_penguin_tools_cli(
    *,
    input_path: Path,
    output_path: Path,
    jacket_input: Path | None = None,
) -> Path:
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = ["jacket", "convert", str(input_path), str(output_path)]
    if jacket_input is not None:
        args.extend(["--jacket-input", str(Path(jacket_input).resolve())])
    payload = _run_penguin_tools_cli(args)
    data = payload.get("data") or {}
    resolved_output = Path(str(data.get("outputPath") or output_path)).resolve()
    if not resolved_output.is_file():
        raise RuntimeError(
            "PenguinTools.CLI 报告成功，但未生成封面 DDS。\n"
            f"input: {input_path}\n"
            f"expected output: {resolved_output}"
        )
    return resolved_output


def convert_audio_with_penguin_tools_cli(
    *,
    input_path: Path,
    output_dir: Path,
    working_audio: Path | None = None,
    cfg: object | None = None,
) -> dict[str, Any]:
    """``audio convert``：输入可为 .mgxc / .ugc / .sus；PJSK 用 SUS 的 BPM/片头空白对齐音频。"""
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    args = ["audio", "convert", str(input_path), str(output_dir)]
    if working_audio is not None:
        wa = Path(working_audio).resolve()
        if wa.is_file():
            args.extend(["--working-audio", str(wa)])
    return _run_penguin_tools_cli(args, cfg=cfg)
