"""
外部可执行工具清单、路径解析与按需下载。

安装目录默认：``<应用根>/.tools/<工具 id>/``（不随 PyInstaller 单文件打包）。
配置覆盖：``ACUS/.config.json`` 中各工具路径字段。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import ssl
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .acus_workspace import AcusConfig, app_cache_dir, app_root_dir

_log = logging.getLogger("chuni.external_tools")

ArchiveKind = Literal["zip", "exe"]


@dataclass(frozen=True)
class ExternalToolSpec:
    id: str
    name: str
    description: str
    used_for: str
    optional: bool
    config_field: str
    default_rel: str
    exe_name: str
    download_url: str | None = None
    archive_kind: ArchiveKind = "zip"
    companion_download_url: str | None = None
    help_url: str | None = None


TOOL_FFMPEG = ExternalToolSpec(
    id="ffmpeg",
    name="FFmpeg",
    description="音频转码（系统语音、烤谱/PJSK 长音频等）。",
    used_for="系统语音包、PJSK 音频 → ACB",
    optional=False,
    config_field="ffmpeg_path",
    default_rel="ffmpeg/bin/ffmpeg.exe",
    exe_name="ffmpeg.exe",
    download_url="https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
    help_url="https://github.com/BtbN/FFmpeg-Builds/releases",
)

TOOL_COMPRESSONATOR = ExternalToolSpec(
    id="compressonator",
    name="Compressonator CLI",
    description="DDS BC3 备选转换器（未装 quicktex 或 quicktex 失败时使用）。",
    used_for="DDS 预览 / BC3 生成",
    optional=True,
    config_field="compressonatorcli_path",
    default_rel="CompressonatorCLI/compressonatorcli.exe",
    exe_name="compressonatorcli.exe",
    download_url="https://github.com/GPUOpen-Tools/compressonator/releases/download/V4.5.52/compressonatorcli-4.5.52-win64.zip",
    help_url="https://github.com/GPUOpen-Tools/compressonator",
)

TOOL_PENGUINTOOLS_CLI = ExternalToolSpec(
    id="penguin_tools_cli",
    name="PenguinTools.CLI",
    description="SUS / mgxc → c2s、PGKO 相关谱面转换。",
    used_for="谱面转换",
    optional=True,
    config_field="penguin_tools_cli_path",
    default_rel="PenguinToolsCLI/PenguinTools.CLI.exe",
    exe_name="PenguinTools.CLI.exe",
    download_url="https://github.com/Foahh/PenguinTools/releases/download/v1.8.4/PenguinTools.CLI.v1.8.4.exe",
    archive_kind="exe",
    companion_download_url=(
        "https://github.com/Foahh/PenguinTools/releases/download/v1.8.4/"
        "PenguinTools.CLI.v1.8.4.external-assets.zip"
    ),
    help_url="https://github.com/Foahh/PenguinTools/releases",
)

# mua 固定从 v0.7.1 Release 下载；二进制不随 Chuni-Eventer 版本更新而重新发布。
MUA_RELEASE_TAG = "v0.7.1"
MUA_DOWNLOAD_URL = (
    f"https://github.com/Swan416ya/Chuni-Eventer/releases/download/{MUA_RELEASE_TAG}/mua.exe"
)
MUA_HELP_URL = f"https://github.com/Swan416ya/Chuni-Eventer/releases/tag/{MUA_RELEASE_TAG}"

TOOL_MUA = ExternalToolSpec(
    id="mua",
    name="mua (muautils)",
    description="舞台背景 AFB 生成（图片 → nf/st.afb）。",
    used_for="Stage 背景 AFB",
    optional=True,
    config_field="mua_path",
    default_rel="PenguinTools/mua.exe",
    exe_name="mua.exe",
    download_url=MUA_DOWNLOAD_URL,
    archive_kind="exe",
    help_url=MUA_HELP_URL,
)

C2S_SANITIZE_DOWNLOAD_URL = (
    f"https://github.com/Swan416ya/Chuni-Eventer/releases/download/{MUA_RELEASE_TAG}/c2s-sanitize.exe"
)

TOOL_C2S_SANITIZE = ExternalToolSpec(
    id="c2s_sanitize",
    name="c2s-sanitize",
    description="PenguinTools 转出 c2s 后的谱面清理（边轨、滑条冲突等）。",
    used_for="烤谱（PJSK）SUS→c2s 后处理",
    optional=True,
    config_field="c2s_sanitize_path",
    default_rel="PenguinTools/c2s-sanitize.exe",
    exe_name="c2s-sanitize.exe",
    download_url=C2S_SANITIZE_DOWNLOAD_URL,
    archive_kind="exe",
    help_url=MUA_HELP_URL,
)

ALL_TOOLS: tuple[ExternalToolSpec, ...] = (
    TOOL_FFMPEG,
    TOOL_COMPRESSONATOR,
    TOOL_PENGUINTOOLS_CLI,
    TOOL_MUA,
    TOOL_C2S_SANITIZE,
)

_BUILTIN_PYTHON = (
    ("quicktex", "BC3 DDS 编码/解码（pip install quicktex）", True),
    ("py7zr", "7z 谱面压缩包解压（pip install py7zr）", True),
)


def tools_root_dir() -> Path:
    return app_root_dir() / ".tools"


def default_tool_path(spec: ExternalToolSpec) -> Path:
    return tools_root_dir() / spec.default_rel


def _config_path_raw(cfg: AcusConfig, spec: ExternalToolSpec) -> str:
    return str(getattr(cfg, spec.config_field, "") or "").strip()


def set_config_path(cfg: AcusConfig, spec: ExternalToolSpec, path: Path | None) -> None:
    value = str(path) if path is not None else ""
    setattr(cfg, spec.config_field, value)


def resolve_tool_path(spec: ExternalToolSpec, cfg: AcusConfig | None) -> Path | None:
    """用户配置 → .tools 默认安装 → 环境变量 / 旧版打包路径 → PATH。"""
    if cfg is not None:
        raw = _config_path_raw(cfg, spec)
        if raw:
            try:
                p = Path(raw).expanduser().resolve(strict=False)
            except OSError:
                p = Path(raw).expanduser()
            if p.is_file():
                return p

    cached = default_tool_path(spec)
    if cached.is_file():
        return cached

    if spec.id == "ffmpeg":
        w = shutil.which("ffmpeg")
        if w:
            return Path(w)
        return None

    if spec.id == "compressonator":
        legacy = _legacy_bundled_compressonator()
        if legacy is not None:
            return legacy
        return None

    if spec.id == "penguin_tools_cli":
        env = os.environ.get("CHUNI_PENGUINTOOLS_CLI", "").strip()
        if env:
            p = Path(env).expanduser()
            if p.is_file():
                return p
        from .penguin_tools_cli import _candidate_cli_paths

        for path in _candidate_cli_paths():
            if path.is_file():
                return path
        return None

    if spec.id == "mua":
        env = os.environ.get("CHUNI_MUA_PATH", "").strip()
        if env:
            p = Path(env).expanduser()
            if p.is_file():
                return p
        for rel in (
            "PenguinTools/mua.exe",
            "mua/mua.exe",
            "muautils/mua.exe",
        ):
            p = tools_root_dir() / rel
            if p.is_file():
                return p
        root = app_root_dir()
        for rel in ("tools/PenguinTools/mua.exe", "tools/mua/mua.exe"):
            p = root / rel
            if p.is_file():
                return p
        return None

    if spec.id == "c2s_sanitize":
        env = os.environ.get("CHUNI_C2S_SANITIZE_PATH", "").strip()
        if env:
            p = Path(env).expanduser()
            if p.is_file():
                return p
        for rel in (
            "PenguinTools/c2s-sanitize.exe",
            "c2s_sanitize/c2s-sanitize.exe",
        ):
            p = tools_root_dir() / rel
            if p.is_file():
                return p
        root = app_root_dir()
        for rel in ("tools/PenguinTools/c2s-sanitize.exe",):
            p = root / rel
            if p.is_file():
                return p
        return None

    return None


def _legacy_bundled_compressonator() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    cand = tools_root_dir() / "CompressonatorCLI" / "compressonatorcli.exe"
    if cand.is_file():
        return cand
    cand2 = app_root_dir() / ".tools" / "CompressonatorCLI" / "compressonatorcli.exe"
    return cand2 if cand2.is_file() else None


def tool_status(spec: ExternalToolSpec, cfg: AcusConfig) -> str:
    p = resolve_tool_path(spec, cfg)
    if p is not None:
        return f"已就绪：{p}"
    if spec.download_url:
        return "未安装（可一键下载）"
    return "未安装（需手动放置或浏览选择）"


def missing_required_tools(cfg: AcusConfig) -> list[ExternalToolSpec]:
    out: list[ExternalToolSpec] = []
    for spec in ALL_TOOLS:
        if spec.optional:
            continue
        if resolve_tool_path(spec, cfg) is None:
            out.append(spec)
    return out


def missing_auto_download_tools(cfg: AcusConfig) -> list[ExternalToolSpec]:
    """支持应用内 zip 下载、且当前未就绪的工具。"""
    return [
        spec
        for spec in ALL_TOOLS
        if spec.download_url and resolve_tool_path(spec, cfg) is None
    ]


def has_bundled_ffmpeg(cfg: AcusConfig | None = None) -> bool:
    """发布「懒人包」时 exe 同级 `.tools/ffmpeg/` 已打入 FFmpeg。"""
    p = resolve_tool_path(TOOL_FFMPEG, cfg)
    if p is None:
        return False
    try:
        return p.resolve(strict=False).is_file()
    except OSError:
        return p.is_file()


def tools_inventory_markdown() -> str:
    lines = [
        "# Chuni Eventer 外部依赖一览",
        "",
        "## 可执行文件（建议放入 `.tools/` 或在设置 → 外部工具 下载）",
        "",
    ]
    for spec in ALL_TOOLS:
        opt = "可选" if spec.optional else "推荐"
        dl = "支持应用内下载" if spec.download_url else "需手动安装"
        lines.append(f"### {spec.name}（{opt}）")
        lines.append(f"- **用途**：{spec.used_for}")
        lines.append(f"- **说明**：{spec.description}")
        lines.append(f"- **默认路径**：`.tools/{spec.default_rel.replace(chr(92), '/')}`")
        lines.append(f"- **配置项**：`{spec.config_field}`")
        lines.append(f"- **安装**：{dl}")
        if spec.help_url:
            lines.append(f"- **参考**：{spec.help_url}")
        lines.append("")
    lines.append("## Python 依赖（随 pip / 打包带入）")
    lines.append("")
    for name, desc, _bundled in _BUILTIN_PYTHON:
        lines.append(f"- **{name}**：{desc}")
    lines.append("")
    lines.append("## 环境变量（高级覆盖）")
    lines.append("")
    lines.append("- `CHUNI_PENGUINTOOLS_CLI` → PenguinTools.CLI.exe / .dll / .csproj")
    lines.append("- `CHUNI_MUA_PATH` → mua.exe")
    lines.append("- `CHUNI_C2S_SANITIZE_PATH` → c2s-sanitize.exe")
    return "\n".join(lines)


def _http_download(url: str, dest: Path, *, on_progress: Callable[[str], None] | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress(f"正在下载…\n{url}")

    req = urllib.request.Request(url, headers={"User-Agent": "Chuni-Eventer/1.0"}, method="GET")
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=600, context=ctx) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        read = 0
        chunk = 256 * 1024
        with dest.open("wb") as f:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                read += len(buf)
                if on_progress and total > 0:
                    pct = min(100, int(read * 100 / total))
                    on_progress(f"正在下载… {pct}%")


def _find_file_in_tree(root: Path, name: str) -> Path | None:
    if not root.is_dir():
        return None
    direct = root / name
    if direct.is_file():
        return direct
    for p in root.rglob(name):
        if p.is_file():
            return p
    return None


def _install_exe_from_zip(
    spec: ExternalToolSpec,
    zip_path: Path,
    *,
    dest_exe: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    if on_progress:
        on_progress("正在解压…")
    dest_exe.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"chuni_tool_{spec.id}_") as td:
        extract_root = Path(td)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_root)
        found = _find_file_in_tree(extract_root, spec.exe_name)
        if found is None:
            raise RuntimeError(f"压缩包内未找到 {spec.exe_name}")
        if dest_exe.exists():
            dest_exe.unlink()
        shutil.copy2(found, dest_exe)
        if spec.id == "compressonator":
            src_dir = found.parent
            for extra in src_dir.iterdir():
                if extra.name.lower() == spec.exe_name.lower():
                    continue
                target = dest_exe.parent / extra.name
                if extra.is_dir():
                    if target.exists():
                        shutil.rmtree(target)
                    shutil.copytree(extra, target)
                elif extra.is_file():
                    shutil.copy2(extra, target)


def _extract_zip_into_dir(
    zip_path: Path,
    dest_dir: Path,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    if on_progress:
        on_progress("正在解压…")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _install_direct_exe(
    spec: ExternalToolSpec,
    exe_cache: Path,
    *,
    dest_exe: Path,
    on_progress: Callable[[str], None] | None = None,
) -> None:
    if on_progress:
        on_progress("正在安装…")
    dest_exe.parent.mkdir(parents=True, exist_ok=True)
    if dest_exe.exists():
        dest_exe.unlink()
    shutil.copy2(exe_cache, dest_exe)


def install_tool(
    spec: ExternalToolSpec,
    cfg: AcusConfig,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    if not spec.download_url:
        raise RuntimeError(f"{spec.name} 暂无自动下载源，请手动安装后浏览选择路径。")

    dest = default_tool_path(spec)
    cache_dir = app_cache_dir() / "tool_downloads"
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]+", "_", spec.id)

    if spec.archive_kind == "exe":
        exe_cache = cache_dir / f"{safe_name}.exe"
        _http_download(spec.download_url, exe_cache, on_progress=on_progress)
        _install_direct_exe(spec, exe_cache, dest_exe=dest, on_progress=on_progress)
        if spec.companion_download_url:
            assets_zip = cache_dir / f"{safe_name}_assets.zip"
            _http_download(spec.companion_download_url, assets_zip, on_progress=on_progress)
            _extract_zip_into_dir(assets_zip, dest.parent, on_progress=on_progress)
    else:
        zip_path = cache_dir / f"{safe_name}.zip"
        _http_download(spec.download_url, zip_path, on_progress=on_progress)
        _install_exe_from_zip(spec, zip_path, dest_exe=dest, on_progress=on_progress)

    set_config_path(cfg, spec, dest)
    cfg.save()
    _log.info("tool_installed id=%s path=%s", spec.id, dest)
    if on_progress:
        on_progress("安装完成")
    return dest


def apply_resolved_paths_to_config(cfg: AcusConfig) -> bool:
    """将已存在于 .tools 下的工具写回配置（不覆盖用户已填的有效路径）。"""
    changed = False
    for spec in ALL_TOOLS:
        if _config_path_raw(cfg, spec):
            try:
                p = Path(_config_path_raw(cfg, spec)).expanduser()
                if p.is_file():
                    continue
            except OSError:
                pass
        cached = default_tool_path(spec)
        if cached.is_file():
            set_config_path(cfg, spec, cached)
            changed = True
    if changed:
        cfg.save()
    return changed


def write_inventory_file() -> Path:
    out = app_cache_dir() / "external_tools_inventory.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tools_inventory_markdown(), encoding="utf-8")
    return out
