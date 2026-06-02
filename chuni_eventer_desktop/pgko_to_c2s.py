from __future__ import annotations

import struct
import shutil
import zlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import BinaryIO

from .penguin_tools_cli import (
    cli_song_id_from_payload,
    convert_audio_with_penguin_tools_cli,
    convert_chart_with_penguin_tools_cli,
    convert_jacket_with_penguin_tools_cli,
    cue_bundle_dir_from_audio_payload,
    relocate_cue_bundle_for_music_id,
)
from .pjsk_acus_install import (
    append_music_sort,
    build_music_xml,
    next_chuni_music_id,
    next_custom_event_id,
    write_ultima_unlock_event,
)
PGKO_RELEASE_TAG_ID = -1
PGKO_RELEASE_TAG_STR = "Invalid"
# 导入管线标识（UI/日志）；含 ``music export`` 的旧版为 split-v1 之前。
PGKO_INSTALL_PIPELINE_ID = "split-v2"
MGXC_TICKS_PER_BAR_4_4 = 1920

from ._suspect.c2s_emit import (
    AldNote,
    AirHold,
    AirNote,
    AscNote,
    AsdNote,
    BpmSetting,
    ChargeNote,
    DcmSetting,
    FlickNote,
    HoldNote,
    HxdNote,
    MeterSetting,
    MineNote,
    SlideNote,
    SxcNote,
    SxdNote,
    SlaNote,
    TimelineSpeedSetting,
    TapNote,
    create_file,
)


@dataclass(frozen=True)
class PgkoChartPick:
    path: Path
    ext: str  # mgxc | ugc


def _is_generated_pgko_artifact_path(p: Path) -> bool:
    parts = {x.lower() for x in p.parts}
    if ".penguin_mgxc_patch" in parts:
        return True
    if "chuni_music_export" in parts:
        return True
    if "chuni_cue" in parts:
        return True
    return False


def pick_pgko_chart_for_convert(download_output: Path) -> PgkoChartPick | None:
    """
    从下载产物中挑选用于转码的谱面文件：
    优先级：mgxc > ugc。
    """
    files: list[Path] = []
    if download_output.is_file():
        if not _is_generated_pgko_artifact_path(download_output):
            files.append(download_output)
    elif download_output.is_dir():
        for p in download_output.glob("**/*"):
            if p.is_file() and not _is_generated_pgko_artifact_path(p):
                files.append(p)
    if not files:
        return None

    by_ext: dict[str, list[Path]] = {"mgxc": [], "ugc": []}
    for p in files:
        ext = p.suffix.lower().lstrip(".")
        if ext in by_ext:
            by_ext[ext].append(p)

    for ext in ("mgxc", "ugc"):
        arr = sorted(by_ext[ext])
        if arr:
            return PgkoChartPick(path=arr[0], ext=ext)
    return None


@dataclass(frozen=True)
class _MgxcEvent:
    kind: str
    tick: int
    value: float
    value2: int = 0


@dataclass(frozen=True)
class _MgxcNote:
    typ: int
    long_attr: int
    direction: int
    ex_attr: int
    x: int
    width: int
    height: int
    tick: int
    timeline: int
    seq: int
    chain_id: int = 0


@dataclass(frozen=True)
class _GroundAnchor:
    tick: int
    lane: int
    width: int
    linkage: str  # TAP/HLD/SLD


@dataclass(frozen=True)
class _MgxcMeta:
    designer: str = ""
    artist: str = ""
    title: str = ""
    song_id: str = ""
    bgm_file: str = ""
    preview_start_sec: float = 0.0
    preview_stop_sec: float = 30.0
    has_preview_start: bool = False
    has_preview_stop: bool = False
    difficulty: int = 3
    level_const: float | None = None
    soffset: bool = False


def _read_exact(f: BinaryIO, size: int) -> bytes:
    b = f.read(size)
    if len(b) != size:
        raise ValueError("unexpected EOF while reading mgxc")
    return b


def _i16(b: bytes) -> int:
    return struct.unpack("<h", b)[0]


def _i32(b: bytes) -> int:
    return struct.unpack("<i", b)[0]


def _f64(b: bytes) -> float:
    return struct.unpack("<d", b)[0]


def _decode_mgxc_text(raw: bytes) -> str:
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="ignore")


def _read_field(buf: BinaryIO) -> str | int | float:
    typ = _i16(_read_exact(buf, 2))
    attr = _i16(_read_exact(buf, 2))
    if typ == 4:
        return _decode_mgxc_text(_read_exact(buf, attr))
    if typ == 3:
        return _f64(_read_exact(buf, 8))
    if typ == 2:
        return _i32(_read_exact(buf, 4))
    if typ in (0, 1):
        return int(attr)
    raise ValueError(f"unknown mgxc field type: {typ}")


def _read_wide_field(buf: BinaryIO) -> str:
    typ = _i32(_read_exact(buf, 4))
    attr = _i32(_read_exact(buf, 4))
    if typ != 4:
        raise ValueError(f"unsupported mgxc wide field type: {typ}")
    return _decode_mgxc_text(_read_exact(buf, attr))


def _parse_mgxc_meta_from_block(block: bytes, meta: _MgxcMeta) -> _MgxcMeta:
    import io

    br = io.BytesIO(block)
    designer = meta.designer
    artist = meta.artist
    title = meta.title
    song_id = meta.song_id
    bgm_file = meta.bgm_file
    preview_start_sec = meta.preview_start_sec
    preview_stop_sec = meta.preview_stop_sec
    has_preview_start = meta.has_preview_start
    has_preview_stop = meta.has_preview_stop
    difficulty = meta.difficulty
    level_const = meta.level_const
    while br.tell() < len(block):
        name = _read_exact(br, 4).decode("utf-8", errors="ignore")
        data = _read_field(br)
        if name == "dsgn" and isinstance(data, str):
            designer = data.strip()
        elif name == "arts" and isinstance(data, str):
            artist = data.strip()
        elif name == "titl" and isinstance(data, str):
            title = data.strip()
        elif name == "sgid" and isinstance(data, str):
            song_id = data.strip()
        elif name == "wvfn" and isinstance(data, str):
            bgm_file = data.strip()
        elif name == "wvp0":
            try:
                preview_start_sec = float(data)
                has_preview_start = True
            except Exception:
                preview_start_sec = 0.0
        elif name == "wvp1":
            try:
                preview_stop_sec = float(data)
                has_preview_stop = True
            except Exception:
                preview_stop_sec = 30.0
        elif name == "diff":
            try:
                difficulty = int(data)
            except Exception:
                difficulty = 3
        elif name == "cnst":
            try:
                level_const = float(data)
            except Exception:
                level_const = None
    return _MgxcMeta(
        designer=designer,
        artist=artist,
        title=title,
        song_id=song_id,
        bgm_file=bgm_file,
        preview_start_sec=preview_start_sec,
        preview_stop_sec=preview_stop_sec,
        has_preview_start=has_preview_start,
        has_preview_stop=has_preview_stop,
        difficulty=int(difficulty),
        level_const=level_const,
    )


def _parse_mgxc_meta(path: Path) -> _MgxcMeta:
    """仅解析 mgxc 的 meta 块（供标题/难度等元数据读取，不解析 evnt/dat2）。"""
    meta = _MgxcMeta()
    with path.open("rb") as f:
        if _read_exact(f, 4) != b"MGXC":
            raise ValueError("invalid mgxc header")
        _read_exact(f, 8)  # block size + version
        while True:
            hdr = f.read(4)
            if not hdr:
                break
            if len(hdr) != 4:
                raise ValueError("broken mgxc block header")
            size = _i32(_read_exact(f, 4))
            if hdr == b"meta":
                meta = _parse_mgxc_meta_from_block(_read_exact(f, size), meta)
            else:
                _read_exact(f, size)
    return meta


def _meta_encode_string(name: str, value: str) -> bytes:
    key = name.encode("ascii")
    if len(key) != 4:
        raise ValueError(f"invalid mgxc meta key: {name!r}")
    raw = value.encode("utf-8")
    return key + struct.pack("<hh", 4, len(raw)) + raw


def _meta_encode_i32(name: str, value: int) -> bytes:
    key = name.encode("ascii")
    if len(key) != 4:
        raise ValueError(f"invalid mgxc meta key: {name!r}")
    return key + struct.pack("<hh", 2, 4) + struct.pack("<i", int(value))


def _meta_encode_f64(name: str, value: float) -> bytes:
    key = name.encode("ascii")
    if len(key) != 4:
        raise ValueError(f"invalid mgxc meta key: {name!r}")
    return key + struct.pack("<hh", 3, 8) + struct.pack("<d", float(value))


def _build_mgxc_meta_block(meta: _MgxcMeta) -> bytes:
    parts: list[bytes] = []
    if meta.designer:
        parts.append(_meta_encode_string("dsgn", meta.designer))
    if meta.artist:
        parts.append(_meta_encode_string("arts", meta.artist))
    if meta.title:
        parts.append(_meta_encode_string("titl", meta.title))
    if meta.song_id:
        parts.append(_meta_encode_string("sgid", meta.song_id))
    if meta.bgm_file:
        parts.append(_meta_encode_string("wvfn", meta.bgm_file))
    if meta.has_preview_start:
        parts.append(_meta_encode_f64("wvp0", meta.preview_start_sec))
    if meta.has_preview_stop:
        parts.append(_meta_encode_f64("wvp1", meta.preview_stop_sec))
    parts.append(_meta_encode_i32("diff", int(meta.difficulty)))
    if meta.level_const is not None:
        parts.append(_meta_encode_f64("cnst", float(meta.level_const)))
    return b"".join(parts)


def _rewrite_mgxc_with_meta(source_path: Path, output_path: Path, meta: _MgxcMeta) -> None:
    new_meta = _build_mgxc_meta_block(meta)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with source_path.open("rb") as src, output_path.open("wb") as out:
        header = _read_exact(src, 12)
        if header[:4] != b"MGXC":
            raise ValueError("invalid mgxc header")
        out.write(header)
        while True:
            hdr = src.read(4)
            if not hdr:
                break
            if len(hdr) != 4:
                raise ValueError("broken mgxc block header")
            size = _i32(_read_exact(src, 4))
            block = _read_exact(src, size)
            if hdr == b"meta":
                out.write(b"meta")
                out.write(struct.pack("<i", len(new_meta)))
                out.write(new_meta)
            else:
                out.write(hdr)
                out.write(struct.pack("<i", size))
                out.write(block)


def _mgxc_sgid_digits(meta: _MgxcMeta) -> str:
    return "".join(ch for ch in (meta.song_id or "") if ch.isdigit())


def _need_mgxc_song_id_patch(meta: _MgxcMeta, music_id: int) -> bool:
    digits = _mgxc_sgid_digits(meta)
    if not digits:
        return True
    try:
        return int(digits) % 10000 != int(music_id) % 10000
    except ValueError:
        return True


_MGXC_AUDIO_SUFFIXES = (".ogg", ".wav", ".flac", ".mp3", ".opus", ".m4a", ".aac")


def _mgxc_bgm_relpath_for_cli(audio: Path, mgxc_cli_path: Path) -> str:
    """``wvfn`` 相对路径：以即将交给 CLI 的 mgxc 所在目录为基准。"""
    import os

    audio = audio.resolve()
    base = mgxc_cli_path.parent.resolve()
    try:
        return audio.relative_to(base).as_posix()
    except ValueError:
        return Path(os.path.relpath(audio, base)).as_posix()


class MgxcPenguinPreflightError(RuntimeError):
    """Margrete 导出 mgxc 缺字段 / 无法定位音频等，在调用 PenguinTools 前抛出。"""

    def __init__(self, message: str, *, issues: list[str] | None = None) -> None:
        super().__init__(message)
        self.issues = list(issues or [])


@dataclass(frozen=True)
class MgxcPenguinPreflight:
    """只读预检结果（不写 patch 文件）。"""

    filled_fields: tuple[str, ...]
    resolved_audio: Path


@dataclass(frozen=True)
class MgxcPenguinPrep:
    """交给 PenguinTools 的 mgxc 与隔离后的 BGM WAV（不修改用户包内原始音频）。"""

    cli_mgxc: Path
    safe_bgm_wav: Path
    filled_fields: tuple[str, ...]
    source_mgxc: Path


def resolve_pgko_mgxc_path(pick: PgkoChartPick) -> Path:
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise MgxcPenguinPreflightError(
                "未找到 mgxc。请按「UGC → mgxc 说明」用 Margrete 另存 mgxc 到与 ugc 同目录。"
            )
        return fb.resolve()
    return source_path.resolve()


def _enrich_mgxc_meta_from_bundle(mgxc_path: Path, meta: _MgxcMeta) -> tuple[_MgxcMeta, list[str]]:
    """
    手工 UGC→mgxc 后常见缺 ``wvfn`` / ``wvp*`` / ``titl`` 等；从同目录 ugc 与同 stem 补全。
    """
    filled: list[str] = []
    ugc_meta: _MgxcMeta | None = None
    for p in _iter_ugc_paths_near_mgxc(mgxc_path):
        try:
            ugc_meta, _, _ = _parse_ugc(p)
            break
        except Exception:
            continue

    def _pick(mgxc_val: str, ugc_val: str, label: str) -> str:
        v = (mgxc_val or "").strip()
        if v:
            return v
        u = (ugc_val or "").strip() if ugc_meta else ""
        if u:
            filled.append(label)
            return u
        return ""

    designer = _pick(meta.designer, ugc_meta.designer if ugc_meta else "", "dsgn")
    artist = _pick(meta.artist, ugc_meta.artist if ugc_meta else "", "arts")
    title = _pick(meta.title, ugc_meta.title if ugc_meta else "", "titl")
    if not title.strip():
        title = mgxc_path.stem
        filled.append("titl(stem)")
    song_id = _pick(meta.song_id, ugc_meta.song_id if ugc_meta else "", "sgid")
    bgm_file = _pick(meta.bgm_file, ugc_meta.bgm_file if ugc_meta else "", "wvfn")
    if not bgm_file.strip():
        near = _try_read_ugc_bgm_filename_near(mgxc_path)
        if near.strip():
            bgm_file = near.strip()
            filled.append("wvfn(ugc)")

    difficulty = meta.difficulty
    if ugc_meta is not None and not (meta.title or meta.artist or meta.bgm_file):
        difficulty = ugc_meta.difficulty
    level_const = meta.level_const if meta.level_const is not None else (
        ugc_meta.level_const if ugc_meta else None
    )

    has_preview_start = meta.has_preview_start
    has_preview_stop = meta.has_preview_stop
    preview_start_sec = meta.preview_start_sec
    preview_stop_sec = meta.preview_stop_sec
    if not has_preview_start:
        has_preview_start = True
        preview_start_sec = 0.0
        filled.append("wvp0")
    if not has_preview_stop:
        has_preview_stop = True
        preview_stop_sec = 30.0
        filled.append("wvp1")

    if not artist.strip():
        artist = designer or "PGKO"
        if "arts" not in filled:
            filled.append("arts(fallback)")

    return (
        _MgxcMeta(
            designer=designer,
            artist=artist,
            title=title,
            song_id=song_id,
            bgm_file=bgm_file,
            preview_start_sec=preview_start_sec,
            preview_stop_sec=preview_stop_sec,
            has_preview_start=has_preview_start,
            has_preview_stop=has_preview_stop,
            difficulty=int(difficulty),
            level_const=level_const,
            soffset=meta.soffset,
        ),
        filled,
    )


def _is_valid_riff_wav(path: Path, *, min_data_bytes: int = 256) -> bool:
    """PenguinTools ``--working-audio`` 需要带 ``data`` 子块的 RIFF WAV。"""
    try:
        p = path.resolve()
        if not p.is_file() or p.stat().st_size < 44:
            return False
        with p.open("rb") as f:
            if _read_exact(f, 4) != b"RIFF":
                return False
            _read_exact(f, 4)  # riff size
            if _read_exact(f, 4) != b"WAVE":
                return False
            while True:
                hdr = f.read(8)
                if len(hdr) < 8:
                    return False
                cid = hdr[:4]
                (size,) = struct.unpack("<I", hdr[4:8])
                if cid == b"data":
                    return int(size) >= int(min_data_bytes)
                skip = int(size) + (int(size) & 1)
                if skip <= 0:
                    return False
                f.seek(skip, 1)
    except Exception:
        return False


def _iter_bundle_audio_candidates(meta: _MgxcMeta, mgxc_path: Path) -> list[Path]:
    """按优先级列出包内可用音频（跳过明显损坏的 .wav）。"""
    base = mgxc_path.parent.resolve()
    ordered: list[Path] = []
    seen: set[str] = set()

    def add(p: Path | None) -> None:
        if p is None or not p.is_file():
            return
        key = str(p.resolve()).lower()
        if key in seen:
            return
        seen.add(key)
        ordered.append(p.resolve())

    if meta.bgm_file:
        add(_resolve_audio_path_in_dir(base, meta.bgm_file))
    ugc_bgm = _try_read_ugc_bgm_filename_near(mgxc_path)
    if ugc_bgm:
        add(_resolve_audio_path_in_dir(base, ugc_bgm))
    add(mgxc_path.with_suffix(".wav"))
    for search_dir in (base, base.parent):
        if not search_dir.is_dir():
            continue
        for p in sorted(search_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in _MGXC_AUDIO_SUFFIXES:
                add(p)
        for p in sorted(search_dir.glob("*/*")):
            if p.is_file() and p.suffix.lower() in _MGXC_AUDIO_SUFFIXES:
                add(p)

    valid: list[Path] = []
    invalid_wav: list[Path] = []
    for p in ordered:
        if p.suffix.lower() == ".wav" and not _is_valid_riff_wav(p):
            invalid_wav.append(p)
            continue
        valid.append(p)
    if valid:
        return valid
    return invalid_wav


def _materialize_safe_bgm_wav(src: Path, patch_dir: Path) -> Path:
    """
    将 BGM 落到 ``.penguin_mgxc_patch`` 下的 48k WAV。
    始终经 ffmpeg 重编码（不直接 copy），避免损坏/非标准 WAV 触发 CLI 的 data chunk 错误。
    """
    from .pjsk_audio_chuni import ffmpeg_trim_to_chuni_wav, find_ffmpeg

    patch_dir.mkdir(parents=True, exist_ok=True)
    out = patch_dir / "_penguin_bgm_source.wav"
    src = src.resolve()
    if out.is_file():
        try:
            out.unlink()
        except OSError:
            pass

    ff = find_ffmpeg()
    if ff is None:
        if src.suffix.lower() == ".wav" and _is_valid_riff_wav(src):
            shutil.copy2(src, out)
        else:
            raise RuntimeError(
                "未找到 ffmpeg，无法将 BGM 转为 PenguinTools 可用的 48k WAV。\n"
                f"源文件: {src}\n"
                "请在【设置】中配置 ffmpeg，或把损坏的 divide.wav 从 PGKO 包重新下载。"
            )
    else:
        try:
            ffmpeg_trim_to_chuni_wav(src, out, trim_leading_sec=0.0)
        except Exception as e:
            raise RuntimeError(
                "ffmpeg 无法解码 BGM（文件可能已损坏，例如此前导入失败留下的 1KB wav）。\n"
                f"源文件: {src} ({src.stat().st_size if src.is_file() else 0} bytes)\n"
                f"detail: {e}\n"
                "请从 PGKO 重新下载该曲，或改用同目录下完好的 ogg/flac。"
            ) from e

    if not out.is_file() or not _is_valid_riff_wav(out):
        raise RuntimeError(
            "音频准备失败：生成的 WAV 无效或过小。\n"
            f"输出: {out}\n"
            f"源文件: {src} ({src.stat().st_size if src.is_file() else 0} bytes)"
        )
    return out


def prepare_mgxc_for_penguin_tools(
    source_path: Path,
    meta: _MgxcMeta,
    music_id: int,
    *,
    resolved_audio: Path | None = None,
) -> MgxcPenguinPrep:
    """
    调用 PenguinTools 前：补全 meta、写入 patch mgxc、隔离 BGM 为 patch 内 WAV。
    """
    source_path = source_path.resolve()
    enriched, filled = _enrich_mgxc_meta_from_bundle(source_path, meta)

    audio = resolved_audio
    if audio is None or not Path(audio).is_file():
        candidates = _iter_bundle_audio_candidates(enriched, source_path)
        audio = candidates[0] if candidates else None
    if audio is None:
        listed = sorted(
            p.name
            for search_dir in (source_path.parent, source_path.parent.parent)
            if search_dir.is_dir()
            for p in search_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _MGXC_AUDIO_SUFFIXES
        )
        hint = ", ".join(listed) if listed else "（同目录未见 .ogg/.wav/.mp3 等）"
        raise FileNotFoundError(
            "未找到可用音频文件。\n"
            f"谱面包目录: {source_path.parent}\n"
            f"mgxc wvfn: {enriched.bgm_file or '(空)'}\n"
            f"可见音频: {hint}\n"
            "请确认包内含有音频，且 ugc 的 @BGM 或 mgxc 的 wvfn 指向正确文件名。"
        )
    audio = Path(audio).resolve()

    patch_dir = source_path.parent / ".penguin_mgxc_patch"
    safe_wav = _materialize_safe_bgm_wav(audio, patch_dir)
    out = patch_dir / f"{source_path.stem}_id{int(music_id):04d}.mgxc"

    patched = enriched
    if _need_mgxc_song_id_patch(enriched, music_id):
        patched = replace(patched, song_id=str(int(music_id)))
        if "sgid" not in filled:
            filled.append("sgid")
    rel = _mgxc_bgm_relpath_for_cli(safe_wav, out)
    if patched.bgm_file != rel:
        patched = replace(patched, bgm_file=rel)
        if "wvfn" not in filled:
            filled.append("wvfn")

    patch_dir.mkdir(parents=True, exist_ok=True)
    _rewrite_mgxc_with_meta(source_path, out, patched)
    return MgxcPenguinPrep(
        cli_mgxc=out,
        safe_bgm_wav=safe_wav,
        filled_fields=tuple(filled),
        source_mgxc=source_path,
    )


def preflight_pgko_mgxc_for_penguin(mgxc_path: Path, *, music_id: int) -> MgxcPenguinPreflight:
    """安装/转码前只读预检；失败时抛出 ``MgxcPenguinPreflightError``。"""
    mgxc_path = Path(mgxc_path).resolve()
    try:
        meta = _parse_mgxc_meta(mgxc_path)
    except ValueError as e:
        raise MgxcPenguinPreflightError(f"mgxc 文件无效：{e}") from e
    enriched, filled = _enrich_mgxc_meta_from_bundle(mgxc_path, meta)
    candidates = _iter_bundle_audio_candidates(enriched, mgxc_path)
    audio = candidates[0] if candidates else None
    if audio is None:
        listed = sorted(
            p.name
            for search_dir in (mgxc_path.parent, mgxc_path.parent.parent)
            if search_dir.is_dir()
            for p in search_dir.iterdir()
            if p.is_file() and p.suffix.lower() in _MGXC_AUDIO_SUFFIXES
        )
        hint = ", ".join(listed) if listed else "（同目录未见 .ogg/.wav/.mp3 等）"
        corrupt = [
            p.name
            for p in sorted(mgxc_path.parent.iterdir())
            if p.is_file()
            and p.suffix.lower() == ".wav"
            and not _is_valid_riff_wav(p)
        ]
        corrupt_tip = (
            f"\n下列 WAV 已损坏或非标准（PenguinTools 无法读取）：{', '.join(corrupt)}"
            if corrupt
            else ""
        )
        raise MgxcPenguinPreflightError(
            "未找到可用音频文件。\n"
            f"谱面包目录: {mgxc_path.parent}\n"
            f"补全后 wvfn: {enriched.bgm_file or '(空)'}\n"
            f"可见音频: {hint}"
            f"{corrupt_tip}\n"
            "请从 PGKO 重新下载该曲，或确认 ugc 的 @BGM 与同目录 ogg/flac 完好。"
        )
    if _need_mgxc_song_id_patch(enriched, int(music_id)) and "sgid" not in filled:
        filled = [*filled, "sgid"]
    return MgxcPenguinPreflight(
        filled_fields=tuple(filled),
        resolved_audio=audio.resolve(),
    )


def preflight_pgko_pick_for_penguin(pick: PgkoChartPick, *, music_id: int) -> MgxcPenguinPreflight:
    return preflight_pgko_mgxc_for_penguin(resolve_pgko_mgxc_path(pick), music_id=int(music_id))


def _prepare_mgxc_for_penguin_media(
    source_path: Path,
    meta: _MgxcMeta,
    music_id: int,
    *,
    resolved_audio: Path | None = None,
) -> Path:
    """兼容旧调用：返回 patch 后的 mgxc 路径。"""
    return prepare_mgxc_for_penguin_tools(
        source_path, meta, music_id, resolved_audio=resolved_audio
    ).cli_mgxc


def _parse_mgxc(path: Path) -> tuple[_MgxcMeta, list[_MgxcEvent], list[_MgxcNote]]:
    meta = _MgxcMeta()
    events: list[_MgxcEvent] = []
    notes: list[_MgxcNote] = []
    with path.open("rb") as f:
        if _read_exact(f, 4) != b"MGXC":
            raise ValueError("invalid mgxc header")
        _read_exact(f, 8)  # block size + version
        while True:
            hdr = f.read(4)
            if not hdr:
                break
            if len(hdr) != 4:
                raise ValueError("broken mgxc block header")
            size = _i32(_read_exact(f, 4))
            block = _read_exact(f, size)
            if hdr == b"evnt":
                import io

                br = io.BytesIO(block)
                seq = 0
                while br.tell() < len(block):
                    name = _read_exact(br, 4).decode("utf-8", errors="ignore")
                    if name == "bpm ":
                        tick = int(_read_field(br))
                        bpm = float(_read_field(br))
                        events.append(_MgxcEvent(kind="bpm", tick=tick, value=bpm))
                    elif name == "beat":
                        bar = int(_read_field(br))
                        num = int(_read_field(br))
                        den = int(_read_field(br))
                        events.append(
                            _MgxcEvent(kind="beat", tick=bar, value=float(num), value2=den)
                        )
                    elif name == "til ":
                        timeline = int(_read_field(br))
                        tick = int(_read_field(br))
                        speed = float(_read_field(br))
                        events.append(
                            _MgxcEvent(kind="til", tick=tick, value=speed, value2=timeline)
                        )
                    elif name == "smod":
                        tick = int(_read_field(br))
                        speed = float(_read_field(br))
                        events.append(_MgxcEvent(kind="smod", tick=tick, value=speed))
                    elif name == "mbkm":
                        _read_field(br)
                    elif name == "bmrk":
                        _read_wide_field(br)  # hash
                        _read_field(br)  # tick
                        _read_wide_field(br)  # tag
                        _read_wide_field(br)  # rgb
                    elif name == "rimg":
                        _read_field(br)
                        _read_field(br)
                        _read_wide_field(br)
                        _read_exact(br, 4)
                        continue
                    else:
                        raise ValueError(f"unknown mgxc event tag: {name!r}")
                    _read_exact(br, 4)  # trailing zero
            elif hdr == b"meta":
                meta = _parse_mgxc_meta_from_block(block, meta)
            elif hdr == b"dat2":
                import io

                br = io.BytesIO(block)
                while br.tell() < len(block):
                    typ = struct.unpack("<b", _read_exact(br, 1))[0]
                    long_attr = struct.unpack("<b", _read_exact(br, 1))[0]
                    direction = struct.unpack("<b", _read_exact(br, 1))[0]
                    ex_attr = struct.unpack("<b", _read_exact(br, 1))[0]
                    _read_exact(br, 1)  # variationId
                    x = struct.unpack("<b", _read_exact(br, 1))[0]
                    width = _i16(_read_exact(br, 2))
                    height = _i32(_read_exact(br, 4))
                    tick = _i32(_read_exact(br, 4))
                    timeline = _i32(_read_exact(br, 4))
                    if typ == 0x0A and long_attr == 0x01:
                        _read_exact(br, 4)
                    notes.append(
                        _MgxcNote(
                            typ=typ,
                            long_attr=long_attr,
                            direction=direction,
                            ex_attr=ex_attr,
                            x=x,
                            width=width,
                            height=height,
                            tick=tick,
                            timeline=timeline,
                            seq=seq,
                            chain_id=0,
                        )
                    )
                    seq += 1
    return meta, events, notes


def _find_fallback_mgxc(source: Path) -> Path | None:
    """
    为 ugc 提供回退：
    1) 同名同目录 *.mgxc
    2) 同目录任意 *.mgxc
    3) 上一级目录递归同 stem *.mgxc
    """
    direct = source.with_suffix(".mgxc")
    if direct.exists() and direct.is_file() and not _is_generated_pgko_artifact_path(direct):
        return direct

    parent = source.parent
    siblings = sorted(
        p for p in parent.glob("*.mgxc") if p.is_file() and not _is_generated_pgko_artifact_path(p)
    )
    if siblings:
        return siblings[0]

    root = parent.parent if parent.parent != parent else parent
    same_stem = sorted(
        p
        for p in root.glob("**/*.mgxc")
        if p.is_file()
        and p.stem == source.stem
        and not _is_generated_pgko_artifact_path(p)
    )
    if same_stem:
        return same_stem[0]
    return None


def _patch_music_xml_stage_name(root, *, stage_id: int, stage_str: str) -> None:
    import xml.etree.ElementTree as ET

    st = root.find("stageName")
    if st is None:
        st = ET.SubElement(root, "stageName")
    id_el = st.find("id")
    if id_el is None:
        id_el = ET.SubElement(st, "id")
    id_el.text = str(int(stage_id))
    str_el = st.find("str")
    if str_el is None:
        str_el = ET.SubElement(st, "str")
    str_el.text = str(stage_str or f"Stage{int(stage_id)}")
    data_el = st.find("data")
    if data_el is None:
        data_el = ET.SubElement(st, "data")
    if data_el.text is None:
        data_el.text = ""


def _enabled_fumen_types_from_music_xml(music_xml: Path) -> set[str]:
    import xml.etree.ElementTree as ET

    root = ET.parse(music_xml).getroot()
    enabled: set[str] = set()
    fumens = root.find("fumens")
    if fumens is None:
        return enabled
    for fd in fumens.findall("MusicFumenData"):
        enable_el = fd.find("enable")
        if enable_el is None or enable_el.text != "true":
            continue
        type_el = fd.find("type/str")
        if type_el is not None and (type_el.text or "").strip():
            enabled.add(type_el.text.strip())
    return enabled


def _iter_ugc_paths_near_mgxc(mgxc_path: Path) -> list[Path]:
    """与 mgxc 同目录的 ugc：优先同名，再按名排序的其余 *.ugc。"""
    candidates: list[Path] = []
    same = mgxc_path.with_suffix(".ugc")
    if same.exists() and same.is_file():
        candidates.append(same)
    candidates.extend(sorted(p for p in mgxc_path.parent.glob("*.ugc") if p.is_file()))
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _read_ugc_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="cp932", errors="ignore")
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")


def _b36_int(s: str) -> int:
    return int((s or "0").strip().upper(), 36)


def _parse_bar_tick(text: str) -> tuple[int, int]:
    s = text.strip()
    if "'" not in s:
        raise ValueError(f"invalid BarTick: {text!r}")
    a, b = s.split("'", 1)
    return int(a), int(b)


def _build_bar_to_tick(beat_events: list[_MgxcEvent]) -> callable:
    arr = sorted(beat_events, key=lambda x: x.tick)
    if not arr or arr[0].tick != 0:
        arr.insert(0, _MgxcEvent(kind="beat", tick=0, value=4.0, value2=4))
    bar_starts: list[tuple[int, int, int, int]] = []
    acc = 0
    for i, b in enumerate(arr):
        num = max(1, int(round(b.value)))
        den = max(1, int(b.value2))
        if i > 0:
            prev_bar = arr[i - 1].tick
            prev_num = max(1, int(round(arr[i - 1].value)))
            prev_den = max(1, int(arr[i - 1].value2))
            acc += int(round(MGXC_TICKS_PER_BAR_4_4 * prev_num / prev_den * max(0, b.tick - prev_bar)))
        bar_starts.append((b.tick, acc, num, den))

    beat_by_bar = [(b.tick, max(1, int(round(b.value))), max(1, int(b.value2))) for b in arr]

    def _bar_len_at(bar_idx: int) -> int:
        chosen = beat_by_bar[0]
        for bb, num, den in beat_by_bar:
            if bb <= bar_idx:
                chosen = (bb, num, den)
            else:
                break
        _bb, num, den = chosen
        return int(round(MGXC_TICKS_PER_BAR_4_4 * num / den))

    def to_abs(bar: int, tick_in_bar: int) -> int:
        # BarTick offset may exceed current bar length and cross later bars with different signatures.
        chosen = bar_starts[0]
        for item in bar_starts:
            if item[0] <= bar:
                chosen = item
            else:
                break
        start_bar, start_tick, _num, _den = chosen
        abs_tick = int(start_tick)
        # advance full bars from beat-anchor to target bar
        for b in range(start_bar, bar):
            abs_tick += _bar_len_at(b)
        # advance tick within bar, spilling across later bars if needed
        rem = int(tick_in_bar)
        cur_bar = int(bar)
        while rem > 0:
            bl = _bar_len_at(cur_bar)
            take = min(rem, bl)
            abs_tick += take
            rem -= take
            if rem > 0:
                cur_bar += 1
        return abs_tick

    return to_abs


def _parse_ugc(path: Path) -> tuple[_MgxcMeta, list[_MgxcEvent], list[_MgxcNote]]:
    txt = _read_ugc_text(path)
    lines = txt.splitlines()
    meta = _MgxcMeta()
    events: list[_MgxcEvent] = []
    notes: list[_MgxcNote] = []
    in_body = False
    current_timeline = 0
    seq = 0

    bpm_raw: list[tuple[int, int, float]] = []
    smod_raw: list[tuple[int, int, float]] = []
    til_raw: list[tuple[int, int, int, float]] = []

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("'"):
            continue
        if ln.startswith("@ENDHEAD"):
            in_body = True
            continue
        if ln.startswith("@"):
            parts = ln.split("\t")
            cmd = parts[0][1:].upper()
            args = [p for p in parts[1:] if p != ""]
            if cmd == "TITLE" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "title": args[0].strip()})
            elif cmd == "ARTIST" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "artist": args[0].strip()})
            elif cmd == "DESIGN" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "designer": args[0].strip()})
            elif cmd == "SONGID" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "song_id": args[0].strip()})
            elif cmd == "BGM" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "bgm_file": args[0].strip()})
            elif cmd == "DIFF" and args:
                try:
                    meta = _MgxcMeta(**{**meta.__dict__, "difficulty": int(args[0])})
                except Exception:
                    pass
            elif cmd == "CONST" and args:
                try:
                    meta = _MgxcMeta(**{**meta.__dict__, "level_const": float(args[0])})
                except Exception:
                    pass
            elif cmd == "FLAG" and len(args) >= 2:
                try:
                    k = args[0].strip().upper()
                    v = args[1].strip().upper()
                    if k == "SOFFSET":
                        meta = _MgxcMeta(**{**meta.__dict__, "soffset": v in ("TRUE", "1", "YES")})
                except Exception:
                    pass
            elif cmd == "BPM" and len(args) >= 2:
                try:
                    b, t = _parse_bar_tick(args[0])
                    bpm_raw.append((b, t, float(args[1])))
                except Exception:
                    pass
            elif cmd == "BEAT" and len(args) >= 3:
                try:
                    events.append(
                        _MgxcEvent(kind="beat", tick=int(args[0]), value=float(int(args[1])), value2=int(args[2]))
                    )
                except Exception:
                    pass
            elif cmd == "SPDMOD" and len(args) >= 2:
                try:
                    b, t = _parse_bar_tick(args[0])
                    smod_raw.append((b, t, float(args[1])))
                except Exception:
                    pass
            elif cmd == "TIL" and len(args) >= 3:
                try:
                    tid = int(args[0])
                    b, t = _parse_bar_tick(args[1])
                    til_raw.append((tid, b, t, float(args[2])))
                except Exception:
                    pass
            elif cmd == "USETIL" and args:
                try:
                    current_timeline = int(args[0])
                except Exception:
                    current_timeline = 0
            continue
        if not in_body or not ln.startswith("#"):
            continue

    beats = [e for e in events if e.kind == "beat"]
    to_abs = _build_bar_to_tick(beats)
    for b, t, v in bpm_raw:
        events.append(_MgxcEvent(kind="bpm", tick=to_abs(b, t), value=v))
    for b, t, v in smod_raw:
        events.append(_MgxcEvent(kind="smod", tick=to_abs(b, t), value=v))
    for tid, b, t, v in til_raw:
        events.append(_MgxcEvent(kind="til", tick=to_abs(b, t), value=v, value2=tid))

    parent_re = re.compile(r"^#([^:>]+):([^,]+)(?:,(.*))?$")
    child_re = re.compile(r"^#([0-9]+)>(.+)$")
    parent: dict[str, object] | None = None
    c_chain_id = 1

    def add_note(
        typ: int,
        long_attr: int,
        direction: int,
        x: int,
        width: int,
        tick: int,
        height: int = 0,
        ex_attr: int = 0,
        chain_id: int = 0,
    ) -> None:
        nonlocal seq
        notes.append(
            _MgxcNote(
                typ=typ,
                long_attr=long_attr,
                direction=direction,
                ex_attr=int(ex_attr),
                x=max(0, int(x)),
                width=max(1, int(width)),
                height=int(height),
                tick=max(0, int(tick)),
                timeline=int(current_timeline),
                seq=seq,
                chain_id=int(chain_id),
            )
        )
        seq += 1

    def parse_parent_payload(payload: str, suffix: str | None = None) -> dict[str, object]:
        p = payload.strip()
        t = p[:1]
        d: dict[str, object] = {"t": t, "raw": p}
        if t in ("t", "d", "h", "s"):
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3])
        elif t in ("x", "f"):
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3]); d["dir"] = p[3:4]
        elif t == "a":
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3]); d["dd"] = p[3:5]
        elif t == "H":
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3])
        elif t in ("S", "C"):
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3]); d["hh"] = _b36_int(p[3:5])
            if t == "C":
                d["clr"] = p[5:6] if len(p) >= 6 else "0"
                try:
                    d["interval"] = int((suffix or "").strip()) if suffix not in (None, "", "$") else 0
                    if suffix == "$":
                        d["interval"] = -1
                except Exception:
                    d["interval"] = 0
        return d

    def parse_child_payload(payload: str) -> dict[str, object]:
        p = payload.strip()
        t = p[:1]
        d: dict[str, object] = {"t": t, "raw": p}
        if len(p) >= 3:
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3])
        if len(p) >= 5:
            d["hh"] = _b36_int(p[3:5])
        return d

    def map_extap_dir(ch: str) -> int:
        return {"U": 2, "D": 3, "C": 4, "L": 6, "R": 5, "A": 11, "W": 12, "I": 13}.get(ch.upper(), 2)

    def map_flick_dir(ch: str) -> int:
        return {"L": 6, "R": 5, "A": 0}.get(ch.upper(), 0)

    def map_air_dir(code: str) -> int:
        u = code.upper()
        # UGC code uses player-perspective labels; align with observed official c2s direction.
        return {"UC": 0, "UL": 7, "UR": 8, "DC": 3, "DL": 10, "DR": 9}.get(u, 0)

    def flush_parent() -> None:
        nonlocal parent, c_chain_id
        if not parent:
            return
        p = parent
        t = str(p["t"])
        st = int(p["tick"])
        x = int(p.get("x", 0))
        w = int(p.get("w", 1))
        children = list(p.get("children", []))
        if t == "t":
            add_note(0x01, 0x00, 0, x, w, st)
        elif t == "x":
            add_note(0x02, 0x00, map_extap_dir(str(p.get("dir", "U"))), x, w, st)
        elif t == "f":
            add_note(0x03, 0x00, map_flick_dir(str(p.get("dir", "A"))), x, w, st)
        elif t == "d":
            add_note(0x04, 0x00, 0, x, w, st)
        elif t == "a":
            add_note(0x07, 0x00, map_air_dir(str(p.get("dd", "UC"))), x, w, st)
        elif t == "h":
            add_note(0x05, 0x01, 0, x, w, st)
            if children:
                off, ch = children[-1]
                cx = int(ch.get("x", x)); cw = int(ch.get("w", w))
                add_note(0x05, 0x05, 0, cx, cw, st + int(off))
        elif t == "s":
            add_note(0x06, 0x01, 0, x, w, st)
            for i, (off, ch) in enumerate(children):
                cx = int(ch.get("x", x)); cw = int(ch.get("w", w))
                is_last = i == len(children) - 1
                la = 0x03 if str(ch.get("t", "s")) == "c" else (0x05 if is_last else 0x02)
                add_note(0x06, la, 0, cx, cw, st + int(off))
        elif t == "H":
            add_note(0x08, 0x01, 0, x, w, st)
            for i, (off, ch) in enumerate(children):
                is_last = i == len(children) - 1
                la = 0x05 if is_last else 0x02
                add_note(0x08, la, 0, int(ch.get("x", x)), int(ch.get("w", w)), st + int(off))
        elif t == "S":
            add_note(0x09, 0x01, 0, x, w, st, height=int(p.get("hh", 0)))
            for i, (off, ch) in enumerate(children):
                is_last = i == len(children) - 1
                la = 0x03 if str(ch.get("t", "s")) == "c" else (0x05 if is_last else 0x02)
                add_note(
                    0x09, la, 0, int(ch.get("x", x)), int(ch.get("w", w)), st + int(off), height=int(ch.get("hh", p.get("hh", 0)))
                )
        elif t == "C":
            interval = int(p.get("interval", 0))
            clr = str(p.get("clr", "0") or "0")[:1].upper()
            dir_code = ord(clr) if clr else ord("0")
            # '$' (encoded as -1) is treated as trace-like chain; interval==0 still keeps crash semantics.
            typ = 0x09 if interval < 0 else 0x0A
            cid = c_chain_id
            c_chain_id += 1
            add_note(typ, 0x01, dir_code, x, w, st, height=int(p.get("hh", 0)), ex_attr=interval, chain_id=cid)
            for i, (off, ch) in enumerate(children):
                is_last = i == len(children) - 1
                ch_t = str(ch.get("t", "c"))
                la = 0x03 if ch_t == "c" else (0x05 if is_last else 0x02)
                add_note(
                    typ,
                    la,
                    dir_code,
                    int(ch.get("x", x)),
                    int(ch.get("w", w)),
                    st + int(off),
                    height=int(ch.get("hh", p.get("hh", 0))),
                    ex_attr=interval,
                    chain_id=cid,
                )
        parent = None

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("@USETIL"):
            parts = ln.split("\t")
            if len(parts) >= 2:
                try:
                    current_timeline = int(parts[1].strip())
                except Exception:
                    current_timeline = 0
            continue
        if not ln.startswith("#"):
            continue
        m_child = child_re.match(ln)
        if m_child:
            if parent is None:
                continue
            off = int(m_child.group(1))
            ch = parse_child_payload(m_child.group(2))
            parent.setdefault("children", []).append((off, ch))
            continue
        m_parent = parent_re.match(ln)
        if not m_parent:
            continue
        flush_parent()
        bar, inbar = _parse_bar_tick(m_parent.group(1))
        abs_tick = to_abs(bar, inbar)
        info = parse_parent_payload(m_parent.group(2), m_parent.group(3))
        info["tick"] = abs_tick
        info["children"] = []
        parent = info
    flush_parent()
    return meta, events, notes


def _try_read_ugc_designer_near(mgxc_path: Path) -> str:
    for p in _iter_ugc_paths_near_mgxc(mgxc_path):
        try:
            text = _read_ugc_text(p)
        except Exception:
            continue
        for ln in text.splitlines():
            if ln.startswith("@DESIGN\t"):
                v = ln.split("\t", 1)[1].strip()
                if v:
                    return v
    return ""


def _try_read_ugc_tag_filename_near(mgxc_path: Path, tag_name: str) -> str:
    """UGC 头部 ``@TAG<TAB>filename``（大小写不敏感）。"""
    tag = f"@{tag_name.lstrip('@').lower()}"
    for p in _iter_ugc_paths_near_mgxc(mgxc_path):
        try:
            text = _read_ugc_text(p)
        except Exception:
            continue
        for raw in text.splitlines():
            ln = raw.strip()
            if len(ln) <= len(tag) or not ln.lower().startswith(tag):
                continue
            # 必须匹配完整 tag，避免 @bg 误匹配 @bgm。
            if not ln[len(tag)].isspace():
                continue
            rest = ln[len(tag) :].lstrip()
            if not rest:
                continue
            fn = rest.strip()
            if fn:
                return fn
    return ""


def _try_read_ugc_jacket_filename_near(mgxc_path: Path) -> str:
    """例如：@JACKET<TAB>arghena.jpg"""
    return _try_read_ugc_tag_filename_near(mgxc_path, "jacket")


def _try_read_ugc_bgm_filename_near(mgxc_path: Path) -> str:
    """例如：@BGM / @WAVE 后的音频文件名。"""
    for tag in ("bgm", "wave"):
        fn = _try_read_ugc_tag_filename_near(mgxc_path, tag)
        if fn:
            return fn
    return ""


def _resolve_jacket_path_from_ugc_near(mgxc_path: Path) -> Path | None:
    """按 ugc 中 @JACKET 指向路径查找封面图（同目录/上级目录相对路径均可）。"""
    fn = _try_read_ugc_jacket_filename_near(mgxc_path)
    if not fn:
        return None
    return _resolve_audio_path_in_dir(mgxc_path.parent.resolve(), fn)


def _derive_music_id(meta: _MgxcMeta, mgxc_path: Path) -> int:
    s = (meta.song_id or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits:
        try:
            return max(1, int(digits) % 10000)
        except Exception:
            pass
    return (zlib.crc32(mgxc_path.as_posix().encode("utf-8")) % 9999) + 1


def _resolve_audio_path_in_dir(base: Path, filename: str) -> Path | None:
    safe = Path(filename.replace("\\", "/")).name
    if not safe or safe in (".", ".."):
        return None
    base = base.resolve()
    for candidate in (
        base / filename,
        base / safe,
        base.parent / filename,
        base.parent / safe,
    ):
        try:
            p = candidate.resolve()
        except OSError:
            continue
        if p.is_file():
            try:
                p.relative_to(base)
            except ValueError:
                try:
                    p.relative_to(base.parent)
                except ValueError:
                    continue
            return p
    return None


def _resolve_mgxc_audio_file(meta: _MgxcMeta, mgxc_path: Path) -> Path | None:
    candidates = _iter_bundle_audio_candidates(meta, mgxc_path)
    return candidates[0] if candidates else None


def _iter_mgxc_evnt_blocks(path: Path):
    with path.open("rb") as f:
        if _read_exact(f, 4) != b"MGXC":
            return
        _read_exact(f, 8)
        while True:
            hdr = f.read(4)
            if not hdr or len(hdr) != 4:
                break
            size = _i32(_read_exact(f, 4))
            block = _read_exact(f, size)
            if hdr == b"evnt":
                yield block


def _read_rimg_refs_from_mgxc(path: Path) -> list[str]:
    import io

    out: list[str] = []
    for block in _iter_mgxc_evnt_blocks(path):
        br = io.BytesIO(block)
        while br.tell() < len(block):
            if br.tell() + 4 > len(block):
                break
            name = _read_exact(br, 4).decode("utf-8", errors="ignore")
            try:
                if name == "bpm ":
                    _read_field(br)
                    _read_field(br)
                elif name == "beat":
                    _read_field(br)
                    _read_field(br)
                    _read_field(br)
                elif name == "til ":
                    _read_field(br)
                    _read_field(br)
                    _read_field(br)
                elif name == "smod":
                    _read_field(br)
                    _read_field(br)
                elif name == "mbkm":
                    _read_field(br)
                elif name == "bmrk":
                    _read_wide_field(br)
                    _read_field(br)
                    _read_wide_field(br)
                    _read_wide_field(br)
                elif name == "rimg":
                    _read_field(br)
                    _read_field(br)
                    ref = str(_read_wide_field(br) or "").strip()
                    _read_exact(br, 4)
                    if ref:
                        out.append(ref)
                    continue
                else:
                    break
                _read_exact(br, 4)
            except Exception:
                break
    return out


def _is_missing_stage_ref(s: str) -> bool:
    t = str(s or "").strip().strip('"').strip("'")
    if not t:
        return True
    return t.lower() in {"0", "none", "null", "invalid", "false"}


def _resolve_image_path_in_dir(base: Path, filename: str) -> Path | None:
    safe = Path(filename.replace("\\", "/")).name
    if not safe or safe in (".", ".."):
        return None
    base = base.resolve()
    for candidate in (
        base / filename,
        base / safe,
        base.parent / filename,
        base.parent / safe,
    ):
        try:
            p = candidate.resolve()
        except OSError:
            continue
        if p.is_file():
            try:
                p.relative_to(base)
            except ValueError:
                try:
                    p.relative_to(base.parent)
                except ValueError:
                    continue
            return p
    return None


def _try_read_ugc_background_filename_near(mgxc_path: Path) -> str:
    for tag in ("background", "bg", "stage", "rimg", "bgimg", "bgimage", "fldimg", "scene"):
        fn = _try_read_ugc_tag_filename_near(mgxc_path, tag)
        if fn and not _is_missing_stage_ref(fn):
            return fn
    return ""


def _resolve_pgko_stage_background_path(mgxc_path: Path) -> Path | None:
    for ref in _read_rimg_refs_from_mgxc(mgxc_path):
        if _is_missing_stage_ref(ref):
            continue
        p = _resolve_image_path_in_dir(mgxc_path.parent.resolve(), ref)
        if p is not None:
            return p
    ugc_ref = _try_read_ugc_background_filename_near(mgxc_path)
    if ugc_ref:
        return _resolve_image_path_in_dir(mgxc_path.parent.resolve(), ugc_ref)
    return None


def detect_pgko_stage_background_for_pick(pick: PgkoChartPick) -> Path | None:
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            return None
        source_path = fb
    return _resolve_pgko_stage_background_path(source_path)


def _working_audio_for_penguin_cli(audio_path: Path | None) -> Path | None:
    """
    PenguinTools ``--working-audio`` 当前按 WAV 读取（需存在 RIFF data chunk）。
    非 WAV（如 mp3/flac）不要透传，避免触发 "File must have a valid data chunk"。
    """
    if audio_path is None:
        return None
    p = Path(audio_path).resolve()
    if not p.is_file():
        return None
    return p if p.suffix.lower() == ".wav" else None


def _emit_c2s_from_semantic(
    *,
    out: Path,
    meta: _MgxcMeta,
    events: list[_MgxcEvent],
    raw_notes: list[_MgxcNote],
    source_path: Path,
    creator_fallback: str,
) -> tuple[Path, str]:
    min_note_tick = min((n.tick for n in raw_notes), default=0)
    base_shift = max(0, MGXC_TICKS_PER_BAR_4_4 - int(min_note_tick))
    if base_shift > 0:
        raw_notes = [
            _MgxcNote(
                typ=n.typ,
                long_attr=n.long_attr,
                direction=n.direction,
                ex_attr=n.ex_attr,
                x=n.x,
                width=n.width,
                height=n.height,
                tick=n.tick + base_shift,
                timeline=n.timeline,
                seq=n.seq,
                chain_id=n.chain_id,
            )
            for n in raw_notes
        ]

    if meta.soffset:
        shift = MGXC_TICKS_PER_BAR_4_4
        events = [
            _MgxcEvent(kind=e.kind, tick=(e.tick + shift) if e.tick > 0 and e.kind != "beat" else e.tick, value=e.value, value2=e.value2)
            for e in events
        ]
        raw_notes = [
            _MgxcNote(
                typ=n.typ,
                long_attr=n.long_attr,
                direction=n.direction,
                ex_attr=n.ex_attr,
                x=n.x,
                width=n.width,
                height=n.height,
                tick=n.tick + shift,
                timeline=n.timeline,
                seq=n.seq,
                chain_id=n.chain_id,
            )
            for n in raw_notes
        ]

    if not events:
        events = [_MgxcEvent(kind="bpm", tick=0, value=120.0)]

    bpm_def = sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick)[0].value
    scale = 384.0 / float(MGXC_TICKS_PER_BAR_4_4)

    defs: list[BpmSetting | MeterSetting | DcmSetting | TimelineSpeedSetting] = []
    bpm_events = sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick)
    for e in bpm_events:
        obj = BpmSetting()
        t = max(0, int(round(e.tick * scale)))
        obj.measure = t // 384
        obj.tick = t % 384
        obj.bpm = float(e.value)
        defs.append(obj)

    beat_events = sorted((e for e in events if e.kind == "beat"), key=lambda x: x.tick)
    if not beat_events or beat_events[0].tick != 0:
        beat_events.insert(0, _MgxcEvent(kind="beat", tick=0, value=4.0, value2=4))

    beat_ticks: list[tuple[int, int, int]] = []
    acc = 0
    for i, b in enumerate(beat_events):
        num = max(1, int(round(b.value)))
        den = max(1, int(b.value2))
        if i > 0:
            prev_bar = beat_events[i - 1].tick
            prev_num = max(1, int(round(beat_events[i - 1].value)))
            prev_den = max(1, int(beat_events[i - 1].value2))
            bars = max(0, b.tick - prev_bar)
            acc += int(round(MGXC_TICKS_PER_BAR_4_4 * prev_num / prev_den * bars))
        beat_ticks.append((acc, num, den))

    for bt, num, den in beat_ticks:
        m = MeterSetting()
        t = max(0, int(round(bt * scale)))
        m.measure = t // 384
        m.tick = t % 384
        m.signature = (num, den)
        defs.append(m)

    smod_events = sorted((e for e in events if e.kind == "smod"), key=lambda x: x.tick)
    if smod_events:
        last_note_tick_480 = max((n.tick for n in raw_notes), default=0)
        for i, s in enumerate(smod_events):
            start = max(0, int(round(s.tick * scale)))
            if i + 1 < len(smod_events):
                end = max(0, int(round(smod_events[i + 1].tick * scale)))
            else:
                end = max(start + 1, int(round(last_note_tick_480 * scale)))
            if end <= start or abs(float(s.value) - 1.0) < 1e-6:
                continue
            sp = DcmSetting()
            sp.measure = start // 384
            sp.tick = start % 384
            sp.length = end - start
            sp.speed = float(s.value)
            defs.append(sp)

    til_events = sorted((e for e in events if e.kind == "til"), key=lambda x: (x.value2, x.tick))
    if til_events:
        by_timeline: dict[int, list[_MgxcEvent]] = {}
        for e in til_events:
            by_timeline.setdefault(int(e.value2), []).append(e)
        for tid, arr in by_timeline.items():
            arr = sorted(arr, key=lambda x: x.tick)
            last_timeline_tick_480 = max(
                (n.tick for n in raw_notes if int(n.timeline) == int(tid)),
                default=max((n.tick for n in raw_notes), default=0),
            )
            for i, e in enumerate(arr):
                start = max(0, int(round(e.tick * scale)))
                if i + 1 < len(arr):
                    end = max(0, int(round(arr[i + 1].tick * scale)))
                else:
                    end = max(start + 1, int(round(last_timeline_tick_480 * scale)))
                if end <= start or abs(float(e.value) - 1.0) < 1e-6:
                    continue
                sp = TimelineSpeedSetting()
                sp.measure = start // 384
                sp.tick = start % 384
                sp.length = end - start
                sp.speed = float(e.value)
                sp.timeline = int(tid)
                defs.append(sp)

    converted_notes = sorted(raw_notes, key=lambda x: (x.tick, x.seq))
    ground_anchors: list[_GroundAnchor] = []

    hold_begins: list[_MgxcNote] = []
    slide_chain: list[_MgxcNote] = []
    slide_started = False
    for n in converted_notes:
        t = max(0, int(round(n.tick * scale)))
        lane = int(n.x)
        width = max(1, int(n.width))
        if n.typ in (0x01, 0x02, 0x03):
            ground_anchors.append(_GroundAnchor(tick=t, lane=lane, width=width, linkage="TAP"))
        elif n.typ == 0x05:
            if n.long_attr == 0x01:
                hold_begins.append(n)
            elif n.long_attr == 0x05 and hold_begins:
                st = hold_begins.pop(0)
                st_t = max(0, int(round(st.tick * scale)))
                ground_anchors.append(_GroundAnchor(tick=st_t, lane=int(st.x), width=max(1, int(st.width)), linkage="HLD"))
        elif n.typ == 0x06:
            if n.long_attr == 0x01:
                if slide_started and len(slide_chain) >= 2:
                    for p in slide_chain[:-1]:
                        p_t = max(0, int(round(p.tick * scale)))
                        ground_anchors.append(
                            _GroundAnchor(tick=p_t, lane=int(p.x), width=max(1, int(p.width)), linkage="SLD")
                        )
                slide_chain = [n]
                slide_started = True
            elif slide_started and n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06):
                slide_chain.append(n)
                if n.long_attr in (0x05, 0x06):
                    for p in slide_chain[:-1]:
                        p_t = max(0, int(round(p.tick * scale)))
                        ground_anchors.append(
                            _GroundAnchor(tick=p_t, lane=int(p.x), width=max(1, int(p.width)), linkage="SLD")
                        )
                    slide_started = False
                    slide_chain = []
    if slide_started and len(slide_chain) >= 2:
        for p in slide_chain[:-1]:
            p_t = max(0, int(round(p.tick * scale)))
            ground_anchors.append(
                _GroundAnchor(tick=p_t, lane=int(p.x), width=max(1, int(p.width)), linkage="SLD")
            )

    def _resolve_air_linkage(tick: int, lane: int, width: int, fallback: str = "TAP") -> str:
        same_cover: list[tuple[int, _GroundAnchor]] = []
        prev_cover: list[tuple[int, _GroundAnchor]] = []
        prev_any: list[tuple[int, _GroundAnchor]] = []
        for a in ground_anchors:
            a_l = a.lane
            a_r = a.lane + a.width
            n_l = lane
            n_r = lane + width
            cover = (a_l <= n_l) and (a_r >= n_r)
            dt = tick - a.tick
            if dt == 0 and cover:
                same_cover.append((abs(a.lane - lane), a))
            elif dt >= 0 and cover:
                prev_cover.append((dt * 100 + abs(a.lane - lane), a))
            elif dt >= 0:
                prev_any.append((dt * 100 + abs(a.lane - lane), a))
        if same_cover:
            same_cover.sort(key=lambda x: x[0])
            return same_cover[0][1].linkage
        if prev_cover:
            prev_cover.sort(key=lambda x: x[0])
            return prev_cover[0][1].linkage
        if prev_any:
            prev_any.sort(key=lambda x: x[0])
            return prev_any[0][1].linkage
        return fallback

    def _map_extap_effect(direction: int) -> str:
        return {2: "UP", 3: "DW", 4: "CE", 5: "LS", 6: "RS", 11: "LC", 12: "RC", 13: "BS", 14: "CE"}.get(direction, "UP")

    def _map_flick_dir(direction: int) -> str:
        return "R" if direction in (6, 8, 10, 12) else "L"

    notes_out: list[
        TapNote
        | ChargeNote
        | FlickNote
        | MineNote
        | HoldNote
        | SlideNote
        | AirNote
        | AirHold
        | HxdNote
        | AscNote
        | AsdNote
        | AldNote
        | SxcNote
        | SxdNote
    ] = []
    active_holds: list[_MgxcNote] = []
    active_air_holds: list[_MgxcNote] = []
    active_air_crash: list[_MgxcNote] = []
    active_slides: list[_MgxcNote] = []
    slide_start: _MgxcNote | None = None

    def _emit_ald_segment(st: _MgxcNote, ed: _MgxcNote) -> None:
        st_t = max(0, int(round(st.tick * scale)))
        end_t = max(0, int(round(ed.tick * scale)))
        if end_t <= st_t:
            # UGC chains can contain very short spans that collapse after tick-scale rounding.
            # Keep them as 1-tick ALD segments when source ordering is valid.
            if int(ed.tick) > int(st.tick):
                end_t = st_t + 1
            else:
                return
        x = AldNote()
        x.measure = st_t // 384
        x.tick = st_t % 384
        x.lane = int(st.x)
        x.width = max(1, int(st.width))
        x.mode = 0
        x.start_height = max(1.0, float(int(st.height) / 10.0 if int(st.height) else 1.0))
        x.length = end_t - st_t
        x.end_lane = int(ed.x)
        x.end_width = max(1, int(ed.width))
        x.end_height = max(1.0, float(int(ed.height) / 10.0 if int(ed.height) else 1.0))
        clr = chr(int(st.direction)) if int(st.direction) > 0 else "0"
        x.color = {
            "0": "DEF",
            "1": "RED",
            "2": "ORN",
            "3": "YEL",
            "4": "GRN",
            "5": "CYN",
            "6": "AQA",
            "7": "BLU",
            "8": "VLT",
            "9": "PPL",
            "A": "GRY",
            "Y": "PPL",
            "B": "AQA",
            "C": "NON",
            "D": "BLK",
            "Z": "NON",
        }.get(clr.upper(), "DEF")
        notes_out.append(x)
        interval = int(st.ex_attr)
        if interval > 0:
            for tt in range(st_t + interval, end_t, interval):
                s = SlaNote()
                s.measure = tt // 384
                s.tick = tt % 384
                s.lane = int(st.x)
                s.width = max(1, int(st.width))
                s.a = max(1, int(st.width))
                s.b = 1
                s.c = 1
                notes_out.append(s)
    for n in converted_notes:
        t = max(0, int(round(n.tick * scale)))
        lane = int(n.x)
        width = max(1, int(n.width))
        if n.typ == 0x01:
            x = TapNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; notes_out.append(x)
        elif n.typ == 0x02:
            x = ChargeNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; x.effect = _map_extap_effect(int(n.direction)); notes_out.append(x)
        elif n.typ == 0x03:
            x = FlickNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; x.direction_tag = _map_flick_dir(int(n.direction)); notes_out.append(x)
        elif n.typ == 0x04:
            x = MineNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; notes_out.append(x)
        elif n.typ == 0x07:
            x = AirNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width
            if n.direction in (7,): x.direction = -1; x.isUp = True
            elif n.direction in (8,): x.direction = 1; x.isUp = True
            elif n.direction in (9,): x.direction = -1; x.isUp = False
            elif n.direction in (10,): x.direction = 1; x.isUp = False
            elif n.direction in (3,): x.direction = 0; x.isUp = False
            else: x.direction = 0; x.isUp = True
            x.linkage = _resolve_air_linkage(t, lane, width, fallback="TAP")
            notes_out.append(x)
        elif n.typ == 0x05:
            if n.long_attr == 0x01:
                active_holds.append(n)
            elif n.long_attr == 0x05 and active_holds:
                st = active_holds.pop(0)
                st_t = max(0, int(round(st.tick * scale))); end_t = t
                if end_t <= st_t: continue
                x = HoldNote(); x.measure = st_t // 384; x.tick = st_t % 384; x.lane = int(st.x); x.width = max(1, int(st.width)); x.length = end_t - st_t; notes_out.append(x)
        elif n.typ == 0x08:
            if n.long_attr == 0x01:
                active_air_holds.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_holds:
                st = active_air_holds[-1]
                st_t = max(0, int(round(st.tick * scale))); end_t = max(0, int(round(n.tick * scale)))
                if end_t <= st_t: continue
                x = HxdNote()
                x.measure = st_t // 384
                x.tick = st_t % 384
                x.lane = int(st.x)
                x.width = max(1, int(st.width))
                x.length = end_t - st_t
                x.direction_tag = "UP"
                notes_out.append(x)
                active_air_holds[-1] = n
                if n.long_attr in (0x05, 0x06): active_air_holds.pop()
        elif n.typ == 0x09:
            if n.long_attr == 0x01:
                active_air_holds.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_holds:
                st = active_air_holds[-1]
                st_t = max(0, int(round(st.tick * scale)))
                end_t = max(0, int(round(n.tick * scale)))
                if end_t <= st_t:
                    continue
                linkage = _resolve_air_linkage(st_t, int(st.x), max(1, int(st.width)), fallback="TAP")
                # UGC compact encoding commonly maps to PenguinTools default air height 5.0 for ASC/ASD chains.
                h0 = 5.0
                h1 = 5.0
                is_final = n.long_attr in (0x05, 0x06)
                prev_is_start = st.long_attr == 0x01
                is_c_trace_chain = int(st.ex_attr) < 0 or int(n.ex_attr) < 0
                if is_c_trace_chain and n.long_attr in (0x03, 0x04) and st.long_attr in (0x03, 0x04):
                    x = SxcNote()
                    x.measure = st_t // 384
                    x.tick = st_t % 384
                    x.lane = int(st.x)
                    x.width = max(1, int(st.width))
                    x.length = end_t - st_t
                    x.end_lane = int(n.x)
                    x.end_width = max(1, int(n.width))
                    x.slide_tag = "SLD"
                    x.direction_tag = "UP"
                    notes_out.append(x)
                elif is_c_trace_chain and n.long_attr == 0x06:
                    x = SxdNote()
                    x.measure = st_t // 384
                    x.tick = st_t % 384
                    x.lane = int(st.x)
                    x.width = max(1, int(st.width))
                    x.length = end_t - st_t
                    x.end_lane = int(n.x)
                    x.end_width = max(1, int(n.width))
                    x.slide_tag = "SLD"
                    x.direction_tag = "UP"
                    notes_out.append(x)
                else:
                    x = AsdNote() if is_final else AscNote()
                    x.measure = st_t // 384
                    x.tick = st_t % 384
                    x.lane = int(st.x)
                    x.width = max(1, int(st.width))
                    x.linkage = linkage if prev_is_start else "ASC"
                    x.start_height = h0
                    x.length = end_t - st_t
                    x.end_lane = int(n.x)
                    x.end_width = max(1, int(n.width))
                    x.end_height = h1
                    x.color = "DEF"
                    notes_out.append(x)
                active_air_holds[-1] = n
                if n.long_attr in (0x05, 0x06):
                    active_air_holds.pop()
        elif n.typ == 0x0A:
            if n.long_attr == 0x01:
                if active_air_crash:
                    prev = active_air_crash[-1]
                    prev_t = max(0, int(round(prev.tick * scale)))
                    cur_t = max(0, int(round(n.tick * scale)))
                    if (
                        int(prev.x) == int(n.x)
                        and max(1, int(prev.width)) == max(1, int(n.width))
                        and 0 < (cur_t - prev_t) <= 384
                        and int(prev.ex_attr) > 0
                    ):
                        _emit_ald_segment(prev, n)
                active_air_crash.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_crash:
                st = active_air_crash[-1]
                _emit_ald_segment(st, n)
                active_air_crash[-1] = n
                if n.long_attr in (0x05, 0x06): active_air_crash.pop()
        elif n.typ == 0x06:
            if n.long_attr == 0x01:
                if slide_start is not None and len(active_slides) >= 2:
                    for i in range(len(active_slides) - 1):
                        a = active_slides[i]; b = active_slides[i + 1]
                        at = max(0, int(round(a.tick * scale))); bt = max(0, int(round(b.tick * scale)))
                        if bt <= at: continue
                        x = SlideNote(); x.measure = at // 384; x.tick = at % 384; x.lane = int(a.x); x.width = max(1, int(a.width)); x.length = bt - at; x.end_lane = int(b.x); x.end_width = max(1, int(b.width)); x.is_curve = b.long_attr in (0x03, 0x04, 0x06); notes_out.append(x)
                slide_start = n
                active_slides = [n]
            elif slide_start is not None and n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06):
                active_slides.append(n)
                if n.long_attr in (0x05, 0x06):
                    for i in range(len(active_slides) - 1):
                        a = active_slides[i]; b = active_slides[i + 1]
                        at = max(0, int(round(a.tick * scale))); bt = max(0, int(round(b.tick * scale)))
                        if bt <= at: continue
                        x = SlideNote(); x.measure = at // 384; x.tick = at % 384; x.lane = int(a.x); x.width = max(1, int(a.width)); x.length = bt - at; x.end_lane = int(b.x); x.end_width = max(1, int(b.width)); x.is_curve = b.long_attr in (0x03, 0x04, 0x06); notes_out.append(x)
                    slide_start = None
                    active_slides = []
    if slide_start is not None and len(active_slides) >= 2:
        for i in range(len(active_slides) - 1):
            a = active_slides[i]; b = active_slides[i + 1]
            at = max(0, int(round(a.tick * scale))); bt = max(0, int(round(b.tick * scale)))
            if bt <= at:
                continue
            x = SlideNote(); x.measure = at // 384; x.tick = at % 384; x.lane = int(a.x); x.width = max(1, int(a.width)); x.length = bt - at; x.end_lane = int(b.x); x.end_width = max(1, int(b.width)); x.is_curve = b.long_attr in (0x03, 0x04, 0x06); notes_out.append(x)

    def _note_order_key(obj: object) -> int:
        if isinstance(obj, (TapNote, ChargeNote, FlickNote, MineNote)):
            return 10
        if isinstance(obj, (AscNote, AsdNote)):
            return 11
        if isinstance(obj, (SxcNote, SxdNote)):
            return 12
        if isinstance(obj, HoldNote):
            return 20
        if isinstance(obj, SlideNote):
            return 30
        if isinstance(obj, AirNote):
            return 50
        if isinstance(obj, HxdNote):
            return 60
        if isinstance(obj, AldNote):
            return 70
        if isinstance(obj, SlaNote):
            return 75
        if isinstance(obj, AirHold):
            return 80
        return 999

    notes_out.sort(
        key=lambda o: (
            int(getattr(o, "measure", 0)),
            int(getattr(o, "tick", 0)),
            _note_order_key(o),
            int(getattr(o, "lane", 0)),
            int(getattr(o, "width", 0)),
            str(o),
        )
    )

    creator_name = (meta.designer or "").strip() or (meta.artist or "").strip() or creator_fallback
    b0 = beat_events[0]
    met_def_hdr = (max(1, int(b0.value2)), max(1, int(round(b0.value))))
    text = create_file(defs, notes_out, creator=creator_name, bpm_def=float(bpm_def), met_def=met_def_hdr, include_footer=False)
    out.write_text(text, encoding="utf-8")
    return out, "python"


def convert_pgko_chart_pick_to_c2s(pick: PgkoChartPick) -> Path:
    out, _backend = convert_pgko_chart_pick_to_c2s_with_backend(pick)
    return out


def convert_pgko_chart_pick_to_c2s_with_backend(
    pick: PgkoChartPick, *, allow_ugc_experimental: bool = False
) -> tuple[Path, str]:
    """
    统一委托 PenguinTools.CLI：
    - 支持 mgxc -> c2s
    - 支持实验性 ugc -> c2s（沿用现有开关）
    """
    source_path = pick.path
    source_ext = pick.ext.lower().strip(".")

    if source_ext == "ugc":
        if not allow_ugc_experimental:
            raise NotImplementedError(
                "主流程已禁用 UGC 直转。\n"
                "请先转为 mgxc；若要使用实验性 UGC 直转，请在“设置”中开启对应实验项。"
            )
        out = source_path.with_suffix(".c2s")
        convert_chart_with_penguin_tools_cli(input_path=source_path, output_path=out)
        return out, "cli"

    if source_ext != "mgxc":
        nearby = sorted(
            p.name
            for p in source_path.parent.glob("*")
            if p.is_file() and p.suffix.lower() in (".mgxc", ".ugc")
        )
        nearby_tip = ", ".join(nearby) if nearby else "（同目录未找到 mgxc/ugc）"
        raise NotImplementedError(
            f"暂不支持 {pick.ext} 直转，且未找到可处理的输入。\n"
            f"源文件：{source_path}\n"
            f"同目录可见谱面文件：{nearby_tip}"
        )

    out = source_path.with_suffix(".c2s")
    convert_chart_with_penguin_tools_cli(input_path=source_path, output_path=out)
    return out, "cli"


def convert_pgko_audio_to_chuni_from_pick(
    pick: PgkoChartPick, *, music_id_override: int | None = None
) -> dict[str, object]:
    """
    通过 PenguinTools.CLI ``media audio`` 生成中二 cueFile（含 SOFFSET / wvof 等元数据对齐）。
    """
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise RuntimeError("音频转码需要 mgxc（或可回退到同目录 mgxc）")
        source_path = fb

    meta = _parse_mgxc_meta(source_path)
    music_id = (
        int(music_id_override)
        if music_id_override is not None
        else _derive_music_id(meta, source_path)
    )

    cache_root = source_path.parent.resolve()
    export_root = cache_root / "chuni_cue" / f"_penguin_export_{music_id:04d}"
    if export_root.exists():
        shutil.rmtree(export_root, ignore_errors=True)
    export_root.mkdir(parents=True, exist_ok=True)

    prep = prepare_mgxc_for_penguin_tools(source_path, meta, music_id)
    payload = convert_audio_with_penguin_tools_cli(
        input_path=prep.cli_mgxc,
        output_dir=export_root,
        working_audio=prep.safe_bgm_wav,
    )
    cue_dir = cue_bundle_dir_from_audio_payload(payload)
    cli_sid = cli_song_id_from_payload(payload)
    if cli_sid is None or cli_sid != music_id or cue_dir.name != f"cueFile{music_id:06d}":
        cue_dir = relocate_cue_bundle_for_music_id(cue_dir, music_id=music_id)

    acb_p = cue_dir / f"music{music_id:04d}.acb"
    awb_p = cue_dir / f"music{music_id:04d}.awb"
    cue_xml = cue_dir / "CueFile.xml"
    if not acb_p.is_file() or not awb_p.is_file():
        raise RuntimeError(f"PenguinTools 音频导出不完整：{cue_dir}")

    def _rel(p: Path) -> str:
        return p.resolve().relative_to(cache_root).as_posix()

    return {
        "musicId": music_id,
        "audioSource": str(src_audio),
        "cueDirectory": _rel(cue_dir),
        "cueFileXml": _rel(cue_xml),
        "acbFile": _rel(acb_p),
        "awbFile": _rel(awb_p),
        "backend": "cli",
        "cliSongId": cli_sid,
    }


@dataclass(frozen=True)
class PgkoInstallOptions:
    music_id: int
    stage_id: int
    stage_str: str
    create_unlock_event: bool = True


def suggest_next_pgko_music_id(acus_root: Path, *, start: int = 6000) -> int:
    return next_chuni_music_id(acus_root, start=start)


def read_pgko_meta_for_pick(pick: PgkoChartPick) -> dict[str, object]:
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise RuntimeError("读取元数据需要 mgxc（或可回退到同目录 mgxc）")
        source_path = fb
    meta = _parse_mgxc_meta(source_path)
    return {
        "sourcePath": str(source_path),
        "title": meta.title,
        "artist": meta.artist,
        "designer": meta.designer,
        "difficulty": int(meta.difficulty),
        "levelConst": meta.level_const,
    }


def _slot_from_difficulty(diff: int) -> str:
    return {
        0: "BASIC",
        1: "ADVANCED",
        2: "EXPERT",
        3: "MASTER",
        4: "ULTIMA",
        5: "WORLD'S END",
    }.get(int(diff), "MASTER")


def _slot_file_index(slot: str) -> int:
    mapping = {
        "BASIC": 0,
        "ADVANCED": 1,
        "EXPERT": 2,
        "MASTER": 3,
        "ULTIMA": 4,
        "WORLD'S END": 5,
    }
    return mapping.get(slot, 3)


def _const_to_level_pair(v: float | None) -> tuple[int, int]:
    if v is None:
        return (13, 0)
    lv = int(max(1, min(15, int(v))))
    dec = int(max(0, min(99, round((float(v) - int(v)) * 100))))
    return lv, dec


def _collect_bundle_mgxc_files(primary_mgxc: Path) -> list[Path]:
    root = primary_mgxc.parent
    files = sorted(
        p.resolve()
        for p in root.glob("**/*.mgxc")
        if p.is_file() and not _is_generated_pgko_artifact_path(p)
    )
    if not files:
        return [primary_mgxc.resolve()]
    return files


def _build_pgko_bundle_slot_map(
    primary_mgxc: Path,
    *,
    work_dir: Path,
    prefer_mgxc: Path | None = None,
) -> tuple[dict[str, Path], dict[str, tuple[int, int]]]:
    """
    同一 PGKO 包内全部 mgxc → 各难度 c2s（chart convert）及定数。
    同槽位冲突时优先保留 ``prefer_mgxc``（通常为 UI 所选谱面）。
    """
    prefer = (prefer_mgxc or primary_mgxc).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    slot_map: dict[str, Path] = {}
    levels_by_type: dict[str, tuple[int, int]] = {}
    slot_source: dict[str, Path] = {}

    for mgxc in _collect_bundle_mgxc_files(primary_mgxc):
        meta = _parse_mgxc_meta(mgxc)
        slot = _slot_from_difficulty(meta.difficulty)
        mgxc_r = mgxc.resolve()
        if slot in slot_map:
            if mgxc_r == prefer:
                pass
            elif slot_source.get(slot) == prefer:
                continue
            else:
                continue
        idx = _slot_file_index(slot)
        out = work_dir / f"{idx:02d}_{slot}.c2s"
        try:
            convert_chart_with_penguin_tools_cli(input_path=mgxc, output_path=out)
        except Exception as e:
            raise RuntimeError(
                f"多难度谱面转换失败：{slot} ← {mgxc.name}\n"
                f"路径: {mgxc}\n"
                f"detail: {e}"
            ) from e
        slot_map[slot] = out
        slot_source[slot] = mgxc_r
        levels_by_type[slot] = _const_to_level_pair(meta.level_const)

    return slot_map, levels_by_type


def _jacket_rel_from_music_dir(mdir: Path, *, music_id: int) -> str:
    import xml.etree.ElementTree as ET

    music_xml = mdir / "Music.xml"
    if music_xml.is_file():
        try:
            root = ET.parse(music_xml).getroot()
            p = root.find("./jaketFile/path")
            if p is not None and (p.text or "").strip():
                return (p.text or "").strip()
        except Exception:
            pass
    for hit in sorted(mdir.glob("CHU_UI_Jacket_*.dds")):
        return hit.name
    return f"CHU_UI_Jacket_{int(music_id):04d}.dds"


def _write_worlds_end_unlock_event(acus_root: Path, *, event_id: int, music_id: int, music_title: str) -> None:
    # Reuse existing writer, then patch musicType/name to WORLD'S END flavor.
    p = write_ultima_unlock_event(
        acus_root,
        event_id=int(event_id),
        music_id=int(music_id),
        music_title=music_title,
    )
    import xml.etree.ElementTree as ET

    root = ET.parse(p).getroot()
    n = root.find("./name/str")
    if n is not None:
        n.text = "WE解禁"
    mt = root.find("./substances/music/musicType")
    if mt is not None:
        mt.text = "3"
    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)


def _write_pgko_jacket_dds(
    *,
    out_dds: Path,
    prep: MgxcPenguinPrep,
    jacket_raw: Path | None,
    tool_path: Path | None,
) -> bool:
    """写入乐曲封面 DDS；成功返回 True。"""
    from .dds_convert import DdsToolError, convert_to_bc3_dds

    out_dds.parent.mkdir(parents=True, exist_ok=True)
    if jacket_raw is not None and jacket_raw.is_file():
        try:
            convert_jacket_with_penguin_tools_cli(
                input_path=prep.cli_mgxc,
                output_path=out_dds,
                jacket_input=jacket_raw,
            )
            return out_dds.is_file()
        except Exception:
            try:
                convert_to_bc3_dds(
                    tool_path=tool_path,
                    input_image=jacket_raw,
                    output_dds=out_dds,
                )
                return out_dds.is_file()
            except DdsToolError:
                raise
            except Exception:
                pass
    try:
        convert_jacket_with_penguin_tools_cli(
            input_path=prep.cli_mgxc,
            output_path=out_dds,
        )
        return out_dds.is_file()
    except Exception:
        return False


def _export_pgko_cue_for_acus(
    *,
    prep: MgxcPenguinPrep,
    cli_meta: _MgxcMeta,
    mid: int,
    export_root: Path,
    acus_root: Path,
) -> tuple[Path, str]:
    """
    生成 cueFile：PGKO 默认用 PyCriCodecsEx 写 ACB/AWB（绕开 PenguinTools 的 WAV data chunk 问题）。
    仅当本地编码失败时才尝试 ``media audio``。
    """
    from .pjsk_audio_chuni import build_chuni_music_acb_awb, patch_cue_preview_window

    cue_dst = acus_root / "cueFile" / f"cueFile{mid:06d}"
    if cue_dst.exists():
        shutil.rmtree(cue_dst, ignore_errors=True)

    pstart = float(cli_meta.preview_start_sec) if cli_meta.has_preview_start else 0.0
    pstop = float(cli_meta.preview_stop_sec) if cli_meta.has_preview_stop else 30.0

    cue_dst.mkdir(parents=True, exist_ok=True)
    pycri_err: Exception | None = None
    try:
        build_chuni_music_acb_awb(
            wav_48k_stereo_s16_path=prep.safe_bgm_wav,
            music_id=mid,
            out_dir=cue_dst,
            preview_start_sec=pstart,
            preview_stop_sec=pstop,
        )
        return cue_dst, "pycri-codecs"
    except Exception as e:
        pycri_err = e

    audio_scratch = export_root / "media_audio"
    if audio_scratch.exists():
        shutil.rmtree(audio_scratch, ignore_errors=True)
    audio_scratch.mkdir(parents=True, exist_ok=True)
    if cue_dst.exists():
        shutil.rmtree(cue_dst, ignore_errors=True)

    try:
        payload = convert_audio_with_penguin_tools_cli(
            input_path=prep.cli_mgxc,
            output_dir=audio_scratch,
            working_audio=prep.safe_bgm_wav,
        )
        cue_dir = cue_bundle_dir_from_audio_payload(payload)
        cue_dir = relocate_cue_bundle_for_music_id(cue_dir, music_id=mid)
        cue_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(cue_dir, cue_dst, dirs_exist_ok=True)
        patch_cue_preview_window(
            cue_dst,
            music_id=mid,
            preview_start_sec=pstart,
            preview_stop_sec=pstop,
        )
        return cue_dst, "penguin-media-audio"
    except Exception as penguin_err:
        raise RuntimeError(
            "PGKO 音频写入失败（已跳过 music export）。\n"
            f"PyCriCodecsEx: {pycri_err}\n"
            f"PenguinTools media audio: {penguin_err}\n"
            f"WAV: {prep.safe_bgm_wav}"
        ) from penguin_err


def install_pgko_pick_to_acus(
    *,
    pick: PgkoChartPick,
    acus_root: Path,
    tool_path: Path | None,
    opts: PgkoInstallOptions,
) -> dict[str, object]:
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise RuntimeError("安装到 ACUS 需要 mgxc（或可回退到同目录 mgxc）")
        source_path = fb

    base_meta = _parse_mgxc_meta(source_path)

    mid = int(opts.music_id)
    mdir = acus_root / "music" / f"music{mid:04d}"
    if mdir.exists():
        raise FileExistsError(f"乐曲 ID 已存在：{mid}")

    try:
        prep = prepare_mgxc_for_penguin_tools(source_path, base_meta, mid)
    except FileNotFoundError as e:
        raise RuntimeError(str(e)) from e

    cli_meta = _parse_mgxc_meta(prep.cli_mgxc)
    title = (cli_meta.title or base_meta.title or source_path.stem or str(mid)).strip()
    artist = (cli_meta.artist or base_meta.artist or "").strip() or "PGKO"
    sort_name = title

    export_root = source_path.parent / "chuni_music_export" / f"_penguin_export_{mid:04d}"
    if export_root.exists():
        shutil.rmtree(export_root, ignore_errors=True)
    export_root.mkdir(parents=True, exist_ok=True)

    # 分步导入（不用 music export）：chart convert + 封面 + media audio / 本地 ACB 回退。
    import xml.etree.ElementTree as ET

    slot_work = export_root / "bundle_slots"
    slot_map, levels_by_type = _build_pgko_bundle_slot_map(
        source_path,
        work_dir=slot_work,
        prefer_mgxc=source_path.resolve(),
    )
    if not slot_map:
        raise RuntimeError(
            "谱面包内未找到可转换的 mgxc 谱面。\n"
            f"目录: {source_path.parent}"
        )

    mdir.mkdir(parents=True, exist_ok=True)
    jacket_name = f"CHU_UI_Jacket_{mid:04d}.dds"
    jacket_raw = _resolve_jacket_path_from_ugc_near(source_path)
    _write_pgko_jacket_dds(
        out_dds=mdir / jacket_name,
        prep=prep,
        jacket_raw=jacket_raw,
        tool_path=tool_path,
    )
    jacket_rel = jacket_name if (mdir / jacket_name).is_file() else ""

    for chuni, src_c2s in slot_map.items():
        idx = _slot_file_index(chuni)
        dst = mdir / f"{mid:04d}_{idx:02d}.c2s"
        shutil.copy2(src_c2s, dst)

    installed_slot_paths = {
        chuni: mdir / f"{mid:04d}_{_slot_file_index(chuni):02d}.c2s" for chuni in slot_map
    }
    tree = build_music_xml(
        chuni_id=mid,
        title=title,
        artist=artist,
        sort_name=sort_name,
        stage_id=int(opts.stage_id),
        stage_str=opts.stage_str,
        genre_id=-1,
        genre_str="Invalid",
        jacket_rel=jacket_rel,
        slot_map=installed_slot_paths,
        levels_by_type=levels_by_type,
    )
    music_xml = mdir / "Music.xml"
    ET.indent(tree.getroot(), space="  ")  # type: ignore[attr-defined]
    tree.write(music_xml, encoding="utf-8", xml_declaration=True)

    # 回写 PGKO releaseTag 与 UI 所选 Stage（引用 ACUS 已有舞台，不由 CLI 构建）。
    try:
        root = ET.parse(music_xml).getroot()
        rtag = root.find("./releaseTagName")
        if rtag is not None:
            rid = rtag.find("id")
            rstr = rtag.find("str")
            if rid is not None:
                rid.text = str(PGKO_RELEASE_TAG_ID)
            if rstr is not None:
                rstr.text = PGKO_RELEASE_TAG_STR
        _patch_music_xml_stage_name(
            root, stage_id=int(opts.stage_id), stage_str=opts.stage_str
        )
        ET.indent(root, space="  ")  # type: ignore[attr-defined]
        ET.ElementTree(root).write(music_xml, encoding="utf-8", xml_declaration=True)
    except Exception:
        pass

    try:
        cue_dst, audio_backend = _export_pgko_cue_for_acus(
            prep=prep,
            cli_meta=cli_meta,
            mid=mid,
            export_root=export_root,
            acus_root=acus_root,
        )
    except Exception as e:
        filled_tip = (
            f"已自动补全元数据: {', '.join(prep.filled_fields)}\n"
            if prep.filled_fields
            else ""
        )
        raise RuntimeError(
            f"PGKO 导入失败（管线 {PGKO_INSTALL_PIPELINE_ID}）。\n"
            f"{filled_tip}"
            f"working-audio: {prep.safe_bgm_wav}\n"
            f"detail: {e}"
        ) from e

    append_music_sort(acus_root, mid)

    enabled_slots = _enabled_fumen_types_from_music_xml(music_xml)
    created_event_id: int | None = None
    has_ult = "ULTIMA" in enabled_slots
    has_we = "WORLD'S END" in enabled_slots
    if opts.create_unlock_event and (has_ult or has_we):
        created_event_id = next_custom_event_id(acus_root, start=70000)
        if has_ult:
            write_ultima_unlock_event(
                acus_root,
                event_id=created_event_id,
                music_id=mid,
                music_title=title,
            )
        else:
            _write_worlds_end_unlock_event(
                acus_root,
                event_id=created_event_id,
                music_id=mid,
                music_title=title,
            )

    return {
        "musicId": mid,
        "slots": ",".join(sorted(enabled_slots)),
        "musicXml": str(mdir / "Music.xml"),
        "c2sDir": str(mdir),
        "cueDir": str(cue_dst),
        "eventId": created_event_id,
        "metaFilled": ",".join(prep.filled_fields) if prep.filled_fields else "",
        "audioBackend": audio_backend,
        "pipeline": PGKO_INSTALL_PIPELINE_ID,
    }
