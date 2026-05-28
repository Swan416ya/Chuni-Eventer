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


def _format_penguin_tools_cli_failure(
    *,
    cmd: list[str],
    payload: dict[str, Any],
    stdout: str,
    stderr: str,
) -> str:
    lines = ["PenguinTools.CLI 调用失败：", f"cmd: {' '.join(cmd)}"]
    message = str(payload.get("message") or "").strip()
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
            text = str(item.get("message") or "").strip()
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


def _run_penguin_tools_cli(args: list[str], *, cfg: object | None = None) -> dict[str, Any]:
    cli_path = resolve_penguin_tools_cli(cfg)
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
        raise RuntimeError(
            _format_penguin_tools_cli_failure(
                cmd=cmd,
                payload=payload,
                stdout=stdout,
                stderr=stderr,
            )
        )

    return payload


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
    args = ["media", "jacket", str(input_path), str(output_path)]
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
    """``media audio``：input 可为 .mgxc / .ugc / .sus；PJSK 用 SUS 的 BPM/片头空白对齐音频。"""
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    args = ["media", "audio", str(input_path), str(output_dir)]
    if working_audio is not None:
        wa = Path(working_audio).resolve()
        if wa.is_file():
            args.extend(["--working-audio", str(wa)])
    return _run_penguin_tools_cli(args, cfg=cfg)


def export_music_with_penguin_tools_cli(
    *,
    input_path: Path,
    output_dir: Path,
    jacket_input: Path | None = None,
    stage_id: int | None = None,
    working_audio: Path | None = None,
    cfg: object | None = None,
) -> dict[str, Any]:
    """
    ``music export``：一次性导出 music/cueFile（以及可选 stage/event）。
    """
    input_path = Path(input_path).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    args = ["music", "export", str(input_path), str(output_dir)]
    if jacket_input is not None:
        ji = Path(jacket_input).resolve()
        if ji.is_file():
            args.extend(["--jacket-input", str(ji)])
    if stage_id is not None:
        args.extend(["--stage-id", str(int(stage_id))])
    if working_audio is not None:
        wa = Path(working_audio).resolve()
        if wa.is_file():
            args.extend(["--working-audio", str(wa)])
    return _run_penguin_tools_cli(args, cfg=cfg)
