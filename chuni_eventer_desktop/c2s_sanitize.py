"""c2s-sanitize.exe：烤谱（PJSK）在 PenguinTools 转出 c2s 后的后处理（去边轨、滑条冲突等）。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .acus_workspace import app_root_dir


class C2sSanitizeError(RuntimeError):
    pass


def _candidate_c2s_sanitize_paths() -> list[Path]:
    root = app_root_dir()
    return [
        root / ".tools" / "PenguinTools" / "c2s-sanitize.exe",
        root / ".tools" / "c2s_sanitize" / "c2s-sanitize.exe",
        root / "tools" / "PenguinTools" / "c2s-sanitize.exe",
        root / "tools" / "c2s_sanitize" / "c2s-sanitize.exe",
    ]


def resolve_c2s_sanitize_path(cfg: object | None = None) -> Path | None:
    import os

    from .acus_workspace import AcusConfig
    from .external_tools import TOOL_C2S_SANITIZE, resolve_tool_path

    if cfg is None:
        cfg = AcusConfig.load()

    p = resolve_tool_path(TOOL_C2S_SANITIZE, cfg)  # type: ignore[arg-type]
    if p is not None:
        return p

    env = os.environ.get("CHUNI_C2S_SANITIZE_PATH", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p.resolve()

    for cand in _candidate_c2s_sanitize_paths():
        if cand.is_file():
            return cand.resolve()
    return None


def sanitize_c2s_file(
    c2s_path: Path,
    *,
    cfg: object | None = None,
    in_place: bool = True,
) -> tuple[Path, dict[str, Any] | None]:
    """
    对已有 c2s 执行 c2s-sanitize。

    默认原地覆盖（``--in-place``）。成功返回 (路径, JSON 统计或 None)。
    """
    path = Path(c2s_path).resolve()
    if not path.is_file():
        raise C2sSanitizeError(f"谱面文件不存在：{path}")

    if cfg is None:
        from .acus_workspace import AcusConfig

        cfg = AcusConfig.load()

    exe = resolve_c2s_sanitize_path(cfg)
    if exe is None:
        from .external_tools import TOOL_C2S_SANITIZE, _config_path_raw

        configured = _config_path_raw(cfg, TOOL_C2S_SANITIZE)  # type: ignore[arg-type]
        extra = ""
        if configured:
            extra = (
                f"\n\n当前配置路径无效或文件不存在：\n  {configured}\n"
                "请在外部工具页重新「浏览」选择 c2s-sanitize.exe 并保存设置。"
            )
        raise C2sSanitizeError(
            "未找到 c2s-sanitize.exe。"
            f"{extra}\n\n"
            "也可在「设置 → 外部工具」一键下载，或放到：\n"
            "  <应用根>/.tools/PenguinTools/c2s-sanitize.exe\n"
            "固定下载：\n"
            "  https://github.com/Swan416ya/Chuni-Eventer/releases/download/v0.7.1/c2s-sanitize.exe"
        )

    cmd = [str(exe), str(path)]
    if in_place:
        cmd.append("--in-place")
    cmd.extend(["--json", "--quiet"])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(exe.parent),
        )
    except OSError as e:
        raise C2sSanitizeError(f"启动 c2s-sanitize 失败：{e}") from e

    stats: dict[str, Any] | None = None
    line = (proc.stdout or "").strip().splitlines()
    if line:
        try:
            stats = json.loads(line[-1])
        except json.JSONDecodeError:
            stats = None

    if proc.returncode == 0:
        out_path = path
        if stats and str(stats.get("outputPath") or "").strip():
            cand = Path(str(stats["outputPath"])).resolve()
            if cand.is_file():
                out_path = cand
        return out_path, stats

    err = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode == 1:
        raise C2sSanitizeError(f"c2s-sanitize 参数或文件错误（退出码 1）：\n{err or '(无输出)'}")
    raise C2sSanitizeError(f"c2s-sanitize 处理失败（退出码 {proc.returncode}）：\n{err or '(无输出)'}")
