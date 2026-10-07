"""
PJSK 长音频 → CHUNITHM-style streaming ACB/AWB（底层工具）。

「烤谱」（PJSK → 中二）现在走 :mod:`chuni_eventer_desktop.pjsk2chuni.pipeline`
（上游语义转换 + PenguinTools ``option build``），音频偏移由实测前导静音决定；
本模块只保留其它链路（PGKO / 系统语音 / 舞台等）仍在用的底层件：

* :func:`find_ffmpeg` / :func:`ffmpeg_trim_to_chuni_wav`：任意格式 → 48 kHz 立体声 s16 WAV；
* :func:`build_chuni_music_acb_awb` / :func:`patch_cue_preview_window`：本地打包 HCA + ACB/AWB
  （按 ChuniPingu/PenguinTools MusicConverter (MIT) 同款密钥与表结构）。

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
    trim_leading_sec: float = 0.0,
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
