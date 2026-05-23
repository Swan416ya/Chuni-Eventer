"""
PJSK long audio -> CHUNITHM-style streaming ACB/AWB.

烤谱音频：先用 ffmpeg 裁掉 PJSK 长音频前约 **9 秒**，再交给 **PenguinTools.CLI** + **SUS**
（按谱面 BPM/片头空白小节做二次对齐，与 mgxc 转 c2s 同源逻辑）。
CLI 不可用时回退为「仅裁 9 秒 + 本地 PyCriCodecsEx 编码」。
并按 Foahh/PenguinTools MusicConverter (MIT) 同款密钥与表结构打包 HCA + ACB/AWB：

https://github.com/Foahh/PenguinTools/blob/main/PenguinTools.Core/Media/MusicConverter.cs

Template ``dummy.acb`` is vendored from PenguinTools (PenguinTools/Resources/dummy.acb).
"""
from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

# Same ulong as PenguinTools.Core.Media.MusicConverter
CHUNITHM_HCA_KEY = 32931609366120192

# PJSK 长音频片头空白（秒）：ffmpeg -ss 裁掉后再作为 PenguinTools --working-audio 输入
PJSK_AUDIO_TRIM_LEADING_SEC = 9.0

_DUMMY_REL = Path(__file__).resolve().parent / "data" / "dummy.acb"


def find_ffmpeg(cfg: object | None = None) -> Path | None:
    if cfg is None:
        from .acus_workspace import AcusConfig

        cfg = AcusConfig.load()
    from .external_tools import TOOL_FFMPEG, resolve_tool_path

    p = resolve_tool_path(TOOL_FFMPEG, cfg)  # type: ignore[arg-type]
    if p is not None:
        return p
    p = shutil.which("ffmpeg")
    return Path(p) if p else None


def ffmpeg_trim_to_chuni_wav(
    src: Path,
    dst: Path,
    *,
    trim_leading_sec: float = PJSK_AUDIO_TRIM_LEADING_SEC,
    on_stderr_line: Callable[[str], None] | None = None,
) -> None:
    """Decode any ffmpeg-supported format -> 48 kHz stereo s16le WAV；``trim_leading_sec>0`` 时用 ``-ss`` 跳过片头。"""
    ff = find_ffmpeg()
    if ff is None:
        raise RuntimeError("未找到 ffmpeg（需在 PATH 中），无法裁剪/重采样音频。")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(ff),
        "-hide_banner",
        "-nostdin",
        "-y",
    ]
    if float(trim_leading_sec) > 1e-6:
        cmd.extend(["-ss", f"{float(trim_leading_sec):.6f}"])
    cmd.extend(
        [
            "-i",
            str(src),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(dst),
        ]
    )
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if on_stderr_line and p.stderr:
        for line in p.stderr.splitlines():
            on_stderr_line(line)
    if p.returncode != 0:
        raise RuntimeError(
            "ffmpeg 处理失败：\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr:\n{p.stderr or '(empty)'}\n"
        )


def _patch_track_preview_command(cmd: bytes, *, start_sec: float, stop_sec: float) -> bytes:
    """Big-endian preview window in milliseconds at offsets 3 and 17 (MusicConverter)."""
    b = bytearray(cmd)
    struct.pack_into(">I", b, 3, int(start_sec * 1000))
    struct.pack_into(">I", b, 17, int(stop_sec * 1000))
    return bytes(b)


def patch_cue_preview_window(
    cue_dir: Path,
    *,
    music_id: int,
    preview_start_sec: float = 0.0,
    preview_stop_sec: float = 30.0,
) -> None:
    """在已生成的 cueFile 目录上修补试听区间（与旧 PyCriCodecsEx 管线一致）。"""
    try:
        from PyCriCodecsEx.acb import ACB
        from PyCriCodecsEx.chunk import UTFTypeValues
        from PyCriCodecsEx.utf import UTFBuilder
    except ImportError:
        return

    mid = int(music_id)
    acb_path = cue_dir / f"music{mid:04d}.acb"
    if not acb_path.is_file():
        return
    acb = ACB(str(acb_path))
    v = acb.view
    if len(v.TrackEventTable) < 2:
        return
    v.TrackEventTable[1].Command = _patch_track_preview_command(
        v.TrackEventTable[1].Command,
        start_sec=preview_start_sec,
        stop_sec=preview_stop_sec,
    )
    acb_path.write_bytes(
        UTFBuilder(acb.dictarray, encoding=acb.encoding, table_name=acb.table_name).bytes()
    )


def _write_cue_file_xml(out_dir: Path, *, music_id: int) -> Path:
    """Minimal CueFile.xml matching PenguinTools.Core.Xml.CueFileXml / SaveDirectoryAsync layout."""
    mid = int(music_id)
    data_name = f"cueFile{mid:06d}"
    music_tag = f"music{mid:04d}"
    acb_name = f"{music_tag}.acb"
    awb_name = f"{music_tag}.awb"

    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    xsd = "http://www.w3.org/2001/XMLSchema"
    root = ET.Element(
        "CueFileData",
        {"xmlns:xsi": xsi, "xmlns:xsd": xsd},
    )
    ET.SubElement(root, "dataName").text = data_name
    name_el = ET.SubElement(root, "name")
    ET.SubElement(name_el, "id").text = str(mid)
    ET.SubElement(name_el, "str").text = music_tag
    ET.SubElement(name_el, "data").text = ""
    acb_el = ET.SubElement(root, "acbFile")
    ET.SubElement(acb_el, "path").text = acb_name
    awb_el = ET.SubElement(root, "awbFile")
    ET.SubElement(awb_el, "path").text = awb_name

    out = out_dir / "CueFile.xml"
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return out


def build_chuni_music_acb_awb(
    *,
    wav_48k_stereo_s16_path: Path,
    music_id: int,
    out_dir: Path,
    preview_start_sec: float = 0.0,
    preview_stop_sec: float = 30.0,
) -> tuple[Path, Path]:
    """
    WAV must be 48 kHz, stereo, 16-bit PCM (e.g. from :func:`ffmpeg_trim_to_chuni_wav`).

    Writes ``music{music_id:04d}.acb`` and ``music{music_id:04d}.awb`` under ``out_dir``
    (same layout as PenguinTools CueFileXml: one folder, two files).
    """
    try:
        from PyCriCodecsEx.acb import ACB
        from PyCriCodecsEx.awb import AWBBuilder
        from PyCriCodecsEx.chunk import CriHcaQuality, UTFTypeValues
        from PyCriCodecsEx.hca import HCACodec
        from PyCriCodecsEx.utf import UTFBuilder
    except ImportError as e:
        raise RuntimeError(
            "缺少 PyCriCodecsEx，无法生成 ACB/AWB。请安装：pip install PyCriCodecsEx"
        ) from e

    wav_path = wav_48k_stereo_s16_path.resolve()
    if not wav_path.is_file():
        raise FileNotFoundError(wav_path)

    with wave.open(str(wav_path), "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        if ch != 2 or sw != 2 or rate != 48000:
            raise ValueError(
                f"需要 48kHz 立体声 16-bit WAV，当前为 ch={ch} width={sw} rate={rate}：{wav_path}"
            )

    wav_bytes = wav_path.read_bytes()
    length_ms = int(round(nframes * 1000.0 / rate))

    cue_name = f"cueFile{int(music_id):06d}"

    hca_codec = HCACodec(
        wav_bytes,
        key=CHUNITHM_HCA_KEY,
        quality=CriHcaQuality.Highest,
    )
    hca = hca_codec.get_hca()

    # StreamAwbAfs2Header in dummy uses AFS2 v1, align 0x20, 2-byte ids, subkey 0
    awb = AWBBuilder([hca], subkey=0, version=1, id_intsize=2, align=0x20).build()
    sha1 = hashlib.sha1(awb).digest()

    dummy_path = _DUMMY_REL
    if not dummy_path.is_file():
        raise FileNotFoundError(
            f"缺少模板 {dummy_path}（来自 PenguinTools Resources/dummy.acb）。"
        )

    acb = ACB(str(dummy_path))
    v = acb.view
    v.Name = cue_name
    v.CueTable[0].Length = length_ms
    v.WaveformTable[0].SamplingRate = 48000
    v.WaveformTable[0].NumSamples = nframes

    row = acb.payload["StreamAwbHash"][1][0]
    row["Name"] = (UTFTypeValues.string, cue_name)
    row["Hash"] = (UTFTypeValues.bytes, sha1)

    hdr_row = acb.payload["StreamAwbAfs2Header"][1][0]
    old_header = hdr_row["Header"][1]
    new_header = awb[: len(old_header)]
    if len(new_header) < len(old_header):
        new_header = new_header.ljust(len(old_header), b"\x00")
    hdr_row["Header"] = (UTFTypeValues.bytes, new_header)

    v.TrackEventTable[1].Command = _patch_track_preview_command(
        v.TrackEventTable[1].Command,
        start_sec=preview_start_sec,
        stop_sec=preview_stop_sec,
    )

    acb_bytes = UTFBuilder(
        acb.dictarray, encoding=acb.encoding, table_name=acb.table_name
    ).bytes()

    out_dir.mkdir(parents=True, exist_ok=True)
    acb_out = out_dir / f"music{int(music_id):04d}.acb"
    awb_out = out_dir / f"music{int(music_id):04d}.awb"
    acb_out.write_bytes(acb_bytes)
    awb_out.write_bytes(awb)
    _write_cue_file_xml(out_dir, music_id=music_id)
    return acb_out, awb_out


def resolve_pjsk_reference_sus(bundle_root: Path, manifest: dict[str, object]) -> Path | None:
    """优先用 MASTER/EXPERT 的 SUS 供 PenguinTools 读取 BPM 与片头空白小节。"""
    root = bundle_root.resolve()
    slots = manifest.get("slots")
    if not isinstance(slots, list):
        return None
    by_slot: dict[str, dict] = {}
    for s in slots:
        if isinstance(s, dict):
            slot = str(s.get("chuniSlot") or "").strip().upper()
            if slot:
                by_slot[slot] = s
    for slot in ("MASTER", "EXPERT", "ADVANCED", "BASIC", "ULTIMA"):
        s = by_slot.get(slot)
        if not s:
            continue
        rel = s.get("susFile")
        if isinstance(rel, str) and rel.strip():
            p = (root / rel.strip()).resolve()
            if p.is_file():
                return p
    sus_dir = root / "sus"
    if sus_dir.is_dir():
        for name in ("master.sus", "expert.sus", "append.sus", "hard.sus", "normal.sus"):
            p = sus_dir / name
            if p.is_file():
                return p.resolve()
    return None


def resolve_pjsk_raw_audio(bundle_root: Path, manifest: dict[str, object]) -> Path:
    audio = manifest.get("audio")
    if not isinstance(audio, dict):
        raise FileNotFoundError("manifest 缺少 audio 段。")
    rel = audio.get("file")
    if not isinstance(rel, str) or not rel.strip():
        raise FileNotFoundError("manifest.audio.file 为空。")
    p = (bundle_root / rel.strip()).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"未找到原始音频：{p}")
    return p


def build_pjsk_audio_cue_via_penguin_tools(
    *,
    bundle_root: Path,
    manifest: dict[str, object],
    music_id: int,
    log: Callable[[str], None],
    acus_root: Path | None = None,
    cache_root: Path | None = None,
    preview_start_sec: float = 0.0,
    preview_stop_sec: float = 30.0,
) -> Path:
    """
    1) ffmpeg 裁掉片头 ``PJSK_AUDIO_TRIM_LEADING_SEC``（默认 9s）→ 48k WAV
    2) ``PenguinTools.CLI media audio <sus> <out> --working-audio <wav>``（SUS 负责空白小节对齐）
    """
    from .penguin_tools_cli import (
        convert_audio_with_penguin_tools_cli,
        cue_bundle_dir_from_audio_payload,
        relocate_cue_bundle_for_music_id,
        resolve_penguin_tools_cli,
    )

    if resolve_penguin_tools_cli() is None:
        raise RuntimeError("未找到 PenguinTools.CLI")

    sus = resolve_pjsk_reference_sus(bundle_root, manifest)
    if sus is None:
        raise FileNotFoundError("未找到 SUS 文件，无法让 PenguinTools 计算片头空白小节。")

    src_audio = resolve_pjsk_raw_audio(bundle_root, manifest)
    mid = int(music_id)
    if acus_root is not None:
        cue_parent = acus_root.resolve() / "cueFile" / f"cueFile{mid:06d}"
    elif cache_root is not None:
        cue_parent = cache_root.resolve() / "chuni_cue" / f"cueFile{mid:06d}"
    else:
        raise ValueError("需要 acus_root 或 cache_root 之一。")
    export_base = cue_parent.parent
    export_base.mkdir(parents=True, exist_ok=True)

    trim_sec = float(PJSK_AUDIO_TRIM_LEADING_SEC)
    work_wav = bundle_root.resolve() / "audio" / f"_penguin_work_{mid:04d}.wav"
    log(
        f"音频：ffmpeg 裁掉前 {trim_sec:g} 秒 → 48k WAV，再交 PenguinTools（SUS={sus.name}）对齐片头空白…"
    )
    ffmpeg_trim_to_chuni_wav(src_audio, work_wav, trim_leading_sec=trim_sec)

    scratch = export_base / f"_penguin_audio_{mid:06d}"
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True, exist_ok=True)

    payload = convert_audio_with_penguin_tools_cli(
        input_path=sus,
        output_dir=scratch,
        working_audio=work_wav,
    )
    cue_dir = cue_bundle_dir_from_audio_payload(payload)
    cue_dir = relocate_cue_bundle_for_music_id(cue_dir, music_id=mid)

    if cue_parent.exists():
        shutil.rmtree(cue_parent, ignore_errors=True)
    if cue_dir != cue_parent:
        shutil.move(str(cue_dir), str(cue_parent))
    else:
        cue_parent = cue_dir

    patch_cue_preview_window(
        cue_parent,
        music_id=mid,
        preview_start_sec=preview_start_sec,
        preview_stop_sec=preview_stop_sec,
    )
    log(f"PenguinTools 已写入 cueFile：{cue_parent.name}")
    return cue_parent


def try_pipeline_pjsk_audio_via_penguin(
    *,
    bundle_root: Path,
    manifest: dict[str, object],
    music_id: int,
    cache_root: Path,
    preview_start_sec: float = 0.0,
    preview_stop_sec: float = 30.0,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, object] | None:
    """下载缓存完成后：用 SUS + PenguinTools 生成 chuni_cue（需已下载至少一份 SUS）。"""
    log = on_log or (lambda _m: None)
    sus_path = resolve_pjsk_reference_sus(bundle_root, manifest)
    if sus_path is None:
        log("未找到 SUS，跳过 PenguinTools 音频。")
        return None
    try:
        cue_dir = build_pjsk_audio_cue_via_penguin_tools(
            bundle_root=bundle_root,
            manifest=manifest,
            music_id=music_id,
            cache_root=cache_root,
            log=log,
            preview_start_sec=preview_start_sec,
            preview_stop_sec=preview_stop_sec,
        )
    except Exception as e:
        log(str(e))
        return None

    mid = int(music_id)
    acb_p = cue_dir / f"music{mid:04d}.acb"
    awb_p = cue_dir / f"music{mid:04d}.awb"
    cue_xml = cue_dir / "CueFile.xml"
    if not acb_p.is_file() or not awb_p.is_file():
        return None

    def _rel(p: Path) -> str:
        return p.resolve().relative_to(cache_root.resolve()).as_posix()

    return {
        "engine": "penguin_tools_cli",
        "susPath": _rel(sus_path),
        "workingWav48k": _rel(bundle_root.resolve() / "audio" / f"_penguin_work_{mid:04d}.wav"),
        "trimLeadingSec": float(PJSK_AUDIO_TRIM_LEADING_SEC),
        "cueDirectory": _rel(cue_dir),
        "cueFileXml": _rel(cue_xml),
        "acbFile": _rel(acb_p),
        "awbFile": _rel(awb_p),
        "previewStartSec": preview_start_sec,
        "previewStopSec": preview_stop_sec,
    }


def try_pipeline_pjsk_audio_to_chuni(
    *,
    src_audio: Path,
    music_id: int,
    cache_root: Path,
    trim_leading_sec: float = PJSK_AUDIO_TRIM_LEADING_SEC,
    preview_start_sec: float = 0.0,
    preview_stop_sec: float = 30.0,
    on_log: Callable[[str], None] | None = None,
) -> dict[str, object] | None:
    """
    Full pipeline: original download -> trimmed WAV -> ACB/AWB under
    ``cache_root / chuni_cue / cueFile{music_id:06d}``.

    Returns a dict for manifest embedding, or None if PyCriCodecsEx is missing
    (caller may still keep the raw file only).
    """
    log = on_log or (lambda _m: None)

    inter = cache_root / "audio" / f"_chuni_48k_{int(music_id):04d}.wav"
    try:
        def _err(line: str) -> None:
            if "time=" in line or "Duration:" in line:
                log(line.strip())

        ffmpeg_trim_to_chuni_wav(
            src_audio,
            inter,
            trim_leading_sec=trim_leading_sec,
            on_stderr_line=_err,
        )
    except Exception as e:
        log(str(e))
        raise

    cue_dir = cache_root / "chuni_cue" / f"cueFile{int(music_id):06d}"
    try:
        acb_p, awb_p = build_chuni_music_acb_awb(
            wav_48k_stereo_s16_path=inter,
            music_id=music_id,
            out_dir=cue_dir,
            preview_start_sec=preview_start_sec,
            preview_stop_sec=preview_stop_sec,
        )
    except ImportError:
        return None
    except RuntimeError as e:
        if "PyCriCodecsEx" in str(e):
            return None
        raise

    cue_xml = cue_dir / "CueFile.xml"

    def _rel(p: Path) -> str:
        return p.resolve().relative_to(cache_root.resolve()).as_posix()

    return {
        "trimmedWav48k": _rel(inter),
        "cueDirectory": _rel(cue_dir),
        "cueFileXml": _rel(cue_xml),
        "acbFile": _rel(acb_p),
        "awbFile": _rel(awb_p),
        "hcaKeyUlong": CHUNITHM_HCA_KEY,
        "trimLeadingSec": trim_leading_sec,
        "previewStartSec": preview_start_sec,
        "previewStopSec": preview_stop_sec,
    }
