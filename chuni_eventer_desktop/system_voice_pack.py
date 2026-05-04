"""
自定义系统语音（42 槽 / systemvoice0062 模板）：扫描可用 ID、校验输入、ffmpeg 转 WAV、
调用 repack 写 ACB/AWB，并生成 CueFile.xml、SystemVoiceData XML。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from .acus_workspace import acus_generated_dir, app_root_dir
from .pjsk_audio_chuni import find_ffmpeg
from .repack_system_voice_acb import _natural_wav_sort, repack_streaming_voice_bank

# 与官方 systemvoice0062 / cueFile010062 相同的 42 条逻辑序号（文件名 1..24、35..52）
LOGICAL_IDS_42: tuple[int, ...] = tuple(list(range(1, 25)) + list(range(35, 53)))

AUDIO_EXTENSIONS: tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".m4a",
    ".aac",
    ".opus",
)


def system_voice_stem(voice_id: int) -> str:
    """与游戏内 acb 文件名一致的小写 stem，例如 700 -> systemvoice0700。"""
    return f"systemvoice{int(voice_id):04d}"


def system_voice_dir_name(voice_id: int) -> str:
    """资源目录名，例如 systemVoice0700。"""
    return f"systemVoice{int(voice_id):04d}"


def system_voice_preview_ui_dds_basename(voice_id: int) -> str:
    """UI 预览贴图文件名，与 A001 官方一致：``CHU_UI_SystemVoice_`` + **8 位** id（如 62 -> ``00000062``）。"""
    return f"CHU_UI_SystemVoice_{int(voice_id):08d}.dds"


def cue_folder_name(cue_numeric_id: int) -> str:
    return f"cueFile{int(cue_numeric_id):06d}"


def cue_numeric_id_for_voice(voice_id: int) -> int:
    """与官方规律一致：cueFile010062 <-> 系统语音 62，即 10000 + voice_id。"""
    return 10000 + int(voice_id)


def resolve_system_voice_42_template_acb() -> Path:
    """开发树：audio_test；可选：exe 旁 audio_test；随包 data（若日后打入）。"""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "data" / "system_voice_0062_template" / "systemvoice0062.acb",
        here.parent / "audio_test" / "test" / "cueFile010062" / "systemvoice0062.acb",
        app_root_dir() / "audio_test" / "test" / "cueFile010062" / "systemvoice0062.acb",
    ]
    for p in candidates:
        if p.is_file():
            return p
    raise FileNotFoundError(
        "找不到 42 槽模板 systemvoice0062.acb。\n"
        "请保留仓库内 audio_test/test/cueFile010062/，或将模板复制到 "
        "chuni_eventer_desktop/data/system_voice_0062_template/。"
    )


def load_doc_descriptions() -> dict[int, str]:
    """内置 doc 表（由 audio_test/doc.xlsx 导出）。"""
    p = Path(__file__).resolve().parent / "data" / "system_voice_doc_rows.json"
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: dict[int, str] = {}
    for row in data:
        try:
            i = int(row["id"])
        except Exception:
            continue
        out[i] = str(row.get("desc") or "")
    return out


def find_audio_for_logical_id(folder: Path, logical_id: int) -> Path | None:
    for ext in AUDIO_EXTENSIONS:
        for name in (f"{logical_id}{ext}", f"{logical_id:02d}{ext}", f"{logical_id:03d}{ext}"):
            cand = folder / name
            if cand.is_file():
                return cand
    return None


def validate_voice_folder(folder: Path) -> tuple[list[str], dict[int, Path], list[str]]:
    """
    返回 (缺失 id 列表, 逻辑 id -> 源文件, 多余/无关音频文件名)。
    """
    found: dict[int, Path] = {}
    missing: list[str] = []
    for lid in LOGICAL_IDS_42:
        p = find_audio_for_logical_id(folder, lid)
        if p is None:
            missing.append(str(lid))
        else:
            found[lid] = p
    extra: list[str] = []
    if folder.is_dir():
        for p in folder.iterdir():
            if not p.is_file():
                continue
            if p.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            m = re.match(r"^(\d+)\.", p.name)
            if not m:
                continue
            try:
                n = int(m.group(1))
            except ValueError:
                continue
            if n not in LOGICAL_IDS_42:
                extra.append(p.name)
    return missing, found, extra


def ffmpeg_to_mono_48k_wav(src: Path, dst: Path) -> None:
    ff = find_ffmpeg()
    if ff is None:
        raise RuntimeError("未找到 ffmpeg（需在 PATH 中），无法转码系统语音。")
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(ff),
        "-hide_banner",
        "-nostdin",
        "-y",
        "-i",
        str(src),
        "-ar",
        "48000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 转码失败：{src.name}\n" f"stderr:\n{p.stderr or '(empty)'}\n"
        )


def build_wav_list_in_slot_order(work_dir: Path, source_by_id: dict[int, Path]) -> list[Path]:
    """写出 1.wav…顺序与 LOGICAL_IDS_42 一致，供 _natural_wav_sort 排序。"""
    wavs: list[Path] = []
    for lid in LOGICAL_IDS_42:
        src = source_by_id[lid]
        out = work_dir / f"{lid}.wav"
        ffmpeg_to_mono_48k_wav(src, out)
        wavs.append(out)
    ordered = _natural_wav_sort([p.resolve() for p in wavs])
    if len(ordered) != len(LOGICAL_IDS_42):
        raise RuntimeError("内部错误：WAV 数量与槽位不一致。")
    return ordered


def _parse_cue_dir_id(dirname: str) -> int | None:
    m = re.fullmatch(r"cueFile(\d{6})", dirname, flags=re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1), 10)


def _parse_system_voice_dir_id(dirname: str) -> int | None:
    m = re.fullmatch(r"systemVoice(\d{4})", dirname, flags=re.IGNORECASE)
    if not m:
        return None
    return int(m.group(1), 10)


def _collect_ids_under(root: Path | None) -> tuple[set[int], set[int]]:
    """返回 (已占用的 voice_id 集合, 已占用的 cue 数字 id 集合)。"""
    voices: set[int] = set()
    cues: set[int] = set()
    if root is None or not root.is_dir():
        return voices, cues
    sv = root / "systemVoice"
    if sv.is_dir():
        for p in sv.iterdir():
            if not p.is_dir():
                continue
            vid = _parse_system_voice_dir_id(p.name)
            if vid is not None:
                voices.add(vid)
    cf = root / "cueFile"
    if cf.is_dir():
        for p in cf.iterdir():
            if not p.is_dir():
                continue
            cid = _parse_cue_dir_id(p.name)
            if cid is not None:
                cues.add(cid)
    return voices, cues


def allocate_voice_id(
    *,
    acus_root: Path,
    game_roots: Iterable[Path],
    start_voice_id: int = 700,
) -> int:
    """
    从 start_voice_id 起找最小 voice_id，使得：
    - ACUS 与各游戏包下均未存在 systemVoice{vid} 与 cueFile{10000+vid}。
    """
    occupied_v: set[int] = set()
    occupied_c: set[int] = set()
    v0, c0 = _collect_ids_under(acus_root)
    occupied_v |= v0
    occupied_c |= c0
    for gr in game_roots:
        v2, c2 = _collect_ids_under(gr)
        occupied_v |= v2
        occupied_c |= c2
    vid = max(1, int(start_voice_id))
    for _ in range(200_000):
        cue_id = cue_numeric_id_for_voice(vid)
        if vid not in occupied_v and cue_id not in occupied_c:
            return vid
        vid += 1
    raise RuntimeError("无法在合理范围内找到可用的系统语音 / cueFile ID。")


def write_cue_file_xml(*, out_dir: Path, cue_numeric_id: int, acb_stem: str) -> None:
    data_name = cue_folder_name(cue_numeric_id)
    xsi = "http://www.w3.org/2001/XMLSchema-instance"
    xsd = "http://www.w3.org/2001/XMLSchema"
    root = ET.Element("CueFileData", {"xmlns:xsi": xsi, "xmlns:xsd": xsd})
    ET.SubElement(root, "dataName").text = data_name
    name_el = ET.SubElement(root, "name")
    ET.SubElement(name_el, "id").text = str(int(cue_numeric_id))
    ET.SubElement(name_el, "str").text = acb_stem
    ET.SubElement(name_el, "data")
    acb_el = ET.SubElement(root, "acbFile")
    ET.SubElement(acb_el, "path").text = f"{acb_stem}.acb"
    awb_el = ET.SubElement(root, "awbFile")
    ET.SubElement(awb_el, "path").text = f"{acb_stem}.awb"
    tree = ET.ElementTree(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    tree.write(out_dir / "CueFile.xml", encoding="utf-8", xml_declaration=True)


def _xml_text(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def write_system_voice_xml(
    *,
    out_dir: Path,
    voice_id: int,
    display_str: str,
    dds_filename: str,
    net_open_id: int | None = None,
    net_open_str: str | None = None,
) -> None:
    """
    写入与 A001 官方结构一致的 ``SystemVoiceData``（含 ``cue``：指向 ``cueFile`` 内 ACB/AWB stem）。

    缺 ``cue`` 时客户端会回退默认系统语音（如 001）。
    """
    from .xml_writer import CHARA_DEFAULT_NET_OPEN_ID, CHARA_DEFAULT_NET_OPEN_STR

    dir_name = system_voice_dir_name(voice_id)
    stem = system_voice_stem(voice_id)
    cue_id = cue_numeric_id_for_voice(voice_id)
    no_id = int(CHARA_DEFAULT_NET_OPEN_ID) if net_open_id is None else int(net_open_id)
    no_str = (CHARA_DEFAULT_NET_OPEN_STR if net_open_str is None else net_open_str).strip()
    name_s = _xml_text((display_str or "").strip() or stem)
    sort_s = _xml_text((display_str or "").strip()[:64] or stem)

    root = ET.Element(
        "SystemVoiceData",
        {
            "xmlns:xsd": "http://www.w3.org/2001/XMLSchema",
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        },
    )
    ET.SubElement(root, "dataName").text = dir_name
    net_el = ET.SubElement(root, "netOpenName")
    ET.SubElement(net_el, "id").text = str(no_id)
    ET.SubElement(net_el, "str").text = no_str
    ET.SubElement(net_el, "data")
    ET.SubElement(root, "disableFlag").text = "false"
    name_el = ET.SubElement(root, "name")
    ET.SubElement(name_el, "id").text = str(int(voice_id))
    ET.SubElement(name_el, "str").text = name_s
    ET.SubElement(name_el, "data")
    ET.SubElement(root, "sortName").text = sort_s
    cue_el = ET.SubElement(root, "cue")
    ET.SubElement(cue_el, "id").text = str(int(cue_id))
    ET.SubElement(cue_el, "str").text = stem
    ET.SubElement(cue_el, "data")
    img = ET.SubElement(root, "image")
    ET.SubElement(img, "path").text = dds_filename
    ET.SubElement(root, "defaultHave").text = "false"
    ET.SubElement(root, "explainText").text = "-"
    ET.SubElement(root, "priority").text = "0"
    ET.indent(root, space="  ")  # type: ignore[attr-defined]
    tree = ET.ElementTree(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    tree.write(out_dir / "SystemVoice.xml", encoding="utf-8", xml_declaration=True)


def pack_system_voice_to_acus(
    *,
    acus_root: Path,
    audio_folder: Path,
    voice_id: int,
    display_name: str,
    preview_source: Path,
    tool_path: Path | None = None,
) -> tuple[Path, Path]:
    """
    将 42 条音频打包进 ACUS，并写入 systemVoice / cueFile 目录。

    ``preview_source`` 可为 PNG 等常见图片或已是 BC3 的 DDS；经 ``ingest_to_bc3_dds`` 编码后写入
    ``systemVoice/systemVoiceNNNN/``，文件名为 ``CHU_UI_SystemVoice_{id:04d}.dds``，
    ``SystemVoice.xml`` 为完整官方字段（含 ``netOpenName`` / ``cue`` / ``sortName`` 等），
    ``image/path`` 与同目录下 DDS 文件名一致（``CHU_UI_SystemVoice_`` + 8 位 id）。

    返回 (system_voice_dir, cue_dir)。
    """
    from .dds_convert import DdsToolError, ingest_to_bc3_dds, is_bc3_dds

    missing, found, extra = validate_voice_folder(audio_folder)
    if extra:
        raise ValueError(f"目录中含有非本表要求的音频（将忽略）：{', '.join(extra[:8])}" + ("…" if len(extra) > 8 else ""))
    if missing:
        raise ValueError("缺少以下逻辑序号的音频文件：" + ", ".join(missing))

    template_acb = resolve_system_voice_42_template_acb()
    stem = system_voice_stem(voice_id)
    cue_id = cue_numeric_id_for_voice(voice_id)

    work = acus_generated_dir(acus_root, "sysvoice_build", f"{stem}_{cue_id}")
    work.mkdir(parents=True, exist_ok=True)
    try:
        wavs = build_wav_list_in_slot_order(work, found)
        cue_dir = acus_root / "cueFile" / cue_folder_name(cue_id)
        sv_dir = acus_root / "systemVoice" / system_voice_dir_name(voice_id)
        cue_dir.mkdir(parents=True, exist_ok=True)
        sv_dir.mkdir(parents=True, exist_ok=True)

        out_acb = cue_dir / f"{stem}.acb"
        out_awb = cue_dir / f"{stem}.awb"
        repack_streaming_voice_bank(
            template_acb=template_acb.resolve(),
            wav_paths=wavs,
            out_acb=out_acb,
            out_awb=out_awb,
        )
        write_cue_file_xml(out_dir=cue_dir, cue_numeric_id=cue_id, acb_stem=stem)

        if not preview_source.is_file():
            raise FileNotFoundError(f"预览图不存在：{preview_source}")
        dds_name = system_voice_preview_ui_dds_basename(voice_id)
        tmp_dds = work / dds_name
        ingest_to_bc3_dds(tool_path=tool_path, input_path=preview_source, output_dds=tmp_dds)
        if not is_bc3_dds(tmp_dds):
            raise DdsToolError("预览图编码后不是 BC3(DXT5) DDS，请检查源图或 DDS 工具。")
        shutil.copy2(tmp_dds, sv_dir / dds_name)
        write_system_voice_xml(out_dir=sv_dir, voice_id=voice_id, display_str=display_name, dds_filename=dds_name)
        return sv_dir, cue_dir
    finally:
        shutil.rmtree(work, ignore_errors=True)
