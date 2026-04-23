"""
Install a PJSK cache bundle (pjsk_cache/pjsk_XXXX) into ACUS as official-style music + cueFile.

Aligns with Foahh/PenguinTools Music.xml / Event.xml (ULT unlock) layout:
https://github.com/Foahh/PenguinTools/tree/main/PenguinTools.Core/Xml

Release tag for 烤谱: releaseTagName id=-2 str=PJSK (fixed).
"""
from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import pjsk_audio_chuni as pjsk_ac
from .dds_convert import DdsToolError, convert_to_bc3_dds
from .penguin_tools_cli import convert_chart_with_penguin_tools_cli

XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSD = "http://www.w3.org/2001/XMLSchema"

# User request: fixed release tag for PJSK imports
PJSK_RELEASE_TAG_ID = -2
PJSK_RELEASE_TAG_STR = "PJSK"

# PenguinTools.Xml.XmlConstants.NetOpenName
NET_OPEN_ID = 2600
NET_OPEN_STR = "v2_30 00_0"

# PenguinTools.Metadata.Meta.Display default stage
DEFAULT_STAGE_ID = 8
DEFAULT_STAGE_STR = "レーベル 共通0008_新イエローリング"

# Fumen order: Basic..WorldsEnd (PenguinTools Difficulty enum indices 0..5)
_FUMEN_ORDER: tuple[tuple[str, str], ...] = (
    ("Basic", "BASIC"),
    ("Advanced", "ADVANCED"),
    ("Expert", "EXPERT"),
    ("Master", "MASTER"),
    ("Ultima", "ULTIMA"),
    ("WorldsEnd", "WORLD'S END"),
)


def _xml_esc(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _entry_el(parent: ET.Element, tag: str, eid: int, s: str, data: str = "") -> None:
    el = ET.SubElement(parent, tag)
    ET.SubElement(el, "id").text = str(int(eid))
    ET.SubElement(el, "str").text = s
    ET.SubElement(el, "data").text = data


def _path_el(parent: ET.Element, tag: str, path: str) -> None:
    el = ET.SubElement(parent, tag)
    ET.SubElement(el, "path").text = path


def _invalid_entry(parent: ET.Element, tag: str) -> None:
    _entry_el(parent, tag, -1, "Invalid", "")


@dataclass(frozen=True)
class PjskLocalBundle:
    pjsk_music_id: int
    root: Path
    manifest: dict[str, Any]

    @property
    def title(self) -> str:
        return str(self.manifest.get("title") or "").strip()

    @property
    def composer(self) -> str:
        return str(self.manifest.get("composer") or "").strip()


def iter_local_pjsk_bundles(cache_root: Path) -> list[PjskLocalBundle]:
    out: list[PjskLocalBundle] = []
    if not cache_root.is_dir():
        return out
    for d in sorted(cache_root.glob("pjsk_*"), key=lambda p: p.name):
        if not d.is_dir():
            continue
        m = d / "manifest.json"
        if not m.is_file():
            continue
        try:
            data = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        mid = data.get("musicId")
        try:
            pid = int(mid)
        except (TypeError, ValueError):
            m2 = re.match(r"^pjsk_(\d+)$", d.name, re.I)
            if not m2:
                continue
            pid = int(m2.group(1))
        out.append(PjskLocalBundle(pjsk_music_id=pid, root=d.resolve(), manifest=data))
    out.sort(key=lambda b: b.pjsk_music_id)
    return out


def next_chuni_music_id(acus_root: Path, *, start: int = 7000) -> int:
    used: set[int] = set()
    music_root = acus_root / "music"
    if music_root.is_dir():
        for p in music_root.glob("music*"):
            if not p.is_dir():
                continue
            suf = p.name[5:]
            if suf.isdigit():
                used.add(int(suf))
    cur = max(0, int(start))
    while cur in used:
        cur += 1
    return cur


def _safe_int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def next_custom_event_id(acus_root: Path, *, start: int = 70000) -> int:
    used: set[int] = set()
    event_root = acus_root / "event"
    if event_root.exists():
        for p in event_root.glob("event*"):
            if not p.is_dir():
                continue
            suffix = p.name[5:]
            if suffix.isdigit():
                used.add(int(suffix))
        sort_path = event_root / "EventSort.xml"
        if sort_path.exists():
            try:
                er = ET.parse(sort_path).getroot()
                for n in er.findall("./SortList/StringID/id"):
                    v = _safe_int((n.text or "").strip())
                    if v is not None:
                        used.add(v)
            except ET.ParseError:
                pass
    cur = max(0, int(start))
    while cur in used:
        cur += 1
    return cur


def append_event_sort(acus_root: Path, event_id: int) -> None:
    sort_path = acus_root / "event" / "EventSort.xml"
    if not sort_path.exists():
        sort_path.parent.mkdir(parents=True, exist_ok=True)
        sort_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>event</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
""",
            encoding="utf-8",
        )
    root = ET.parse(sort_path).getroot()
    sl = root.find("SortList")
    if sl is None:
        return
    for n in sl.findall("StringID/id"):
        if _safe_int((n.text or "").strip()) == int(event_id):
            return
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(int(event_id))
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


def _slot_has_chart_source(root: Path, s: dict) -> bool:
    rel_c2s = s.get("c2sFile")
    if rel_c2s and (root / str(rel_c2s)).is_file():
        return True
    rel_sus = s.get("susFile")
    return bool(rel_sus and (root / str(rel_sus)).is_file())


def _materialize_c2s_for_slot(
    bundle: PjskLocalBundle, slot: str, s: dict, log: Callable[[str], None]
) -> Path:
    root = bundle.root
    rel_c2s = s.get("c2sFile")
    if rel_c2s:
        p = (root / str(rel_c2s)).resolve()
        if p.is_file():
            return p
    rel_sus = s.get("susFile")
    if not rel_sus:
        raise ValueError(f"manifest 槽位 {slot} 缺少 susFile / c2sFile。")
    p_sus = (root / str(rel_sus)).resolve()
    if not p_sus.is_file():
        raise FileNotFoundError(f"缺少 SUS：{p_sus}")
    chuni_dir = root / "chuni"
    chuni_dir.mkdir(parents=True, exist_ok=True)
    out = chuni_dir / f"{slot}.c2s"
    convert_chart_with_penguin_tools_cli(input_path=p_sus, output_path=out)
    log(f"已通过 PenguinTools.CLI 生成 {out.relative_to(root)}")
    return out


def _build_slot_map(
    bundle: PjskLocalBundle, log: Callable[[str], None]
) -> dict[str, Path]:
    root = bundle.root
    slots = bundle.manifest.get("slots")
    out: dict[str, Path] = {}
    if not isinstance(slots, list):
        return out
    for s in slots:
        if not isinstance(s, dict):
            continue
        slot = str(s.get("chuniSlot") or "").strip().upper()
        if not slot or not _slot_has_chart_source(root, s):
            continue
        out[slot] = _materialize_c2s_for_slot(bundle, slot, s, log)
    return out


def _has_ultima(slot_map: dict[str, Path]) -> bool:
    return "ULTIMA" in slot_map


def chuni_slots_with_c2s(bundle: PjskLocalBundle) -> list[str]:
    """Slots that have SUS or c2s on disk (UI / install prep), display order BASIC … ULTIMA."""
    root = bundle.root
    slots = bundle.manifest.get("slots")
    have: set[str] = set()
    if isinstance(slots, list):
        for s in slots:
            if not isinstance(s, dict):
                continue
            slot = str(s.get("chuniSlot") or "").strip().upper()
            if slot and _slot_has_chart_source(root, s):
                have.add(slot)
    order = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA")
    return [x for x in order if x in have]


def _resolve_wav_for_acb(bundle: PjskLocalBundle, log: Callable[[str], None]) -> Path:
    root = bundle.root
    audio = bundle.manifest.get("audio")
    desired_trim = float(pjsk_ac.PJSK_AUDIO_TRIM_LEADING_SEC)
    chuni_wav_rel: str | None = None
    ch_sub: dict | None = None
    if isinstance(audio, dict):
        ch = audio.get("chuni")
        if isinstance(ch, dict):
            ch_sub = ch
            w = ch.get("trimmedWav48k")
            if isinstance(w, str) and w.strip():
                chuni_wav_rel = w.strip()
    meta_trim_ok = False
    if ch_sub is not None:
        mt = ch_sub.get("trimLeadingSec")
        try:
            if mt is not None:
                meta_trim_ok = abs(float(mt) - desired_trim) < 1e-9
        except (TypeError, ValueError):
            pass
    if chuni_wav_rel:
        wpath = (root / chuni_wav_rel).resolve()
        if wpath.is_file() and meta_trim_ok:
            return wpath
        if wpath.is_file() and not meta_trim_ok:
            log(
                "缓存的 48k WAV 与当前片头裁剪策略不一致（将尽量从原文件重编码）。"
            )
    if isinstance(audio, dict):
        rel = audio.get("file")
        if isinstance(rel, str) and rel.strip():
            src = (root / rel.strip()).resolve()
            if src.is_file():
                dst = root / "audio" / f"_acus_install_48k_{bundle.pjsk_music_id:04d}.wav"
                pjsk_ac.ffmpeg_trim_to_chuni_wav(
                    src,
                    dst,
                    trim_leading_sec=desired_trim,
                    on_stderr_line=lambda line: None,
                )
                log("已用 ffmpeg 从原始音频生成 48k WAV（片头裁剪按当前策略）。")
                return dst.resolve()
    if chuni_wav_rel:
        wpath = (root / chuni_wav_rel).resolve()
        if wpath.is_file():
            log("无原始 audio.file，仍使用已缓存的 trimmed WAV。")
            return wpath
    raise FileNotFoundError(
        f"未找到可用音频（需要 manifest 中 chuni.trimmedWav48k 或 audio.file）：{root}"
    )


def append_music_sort(acus_root: Path, music_id: int) -> None:
    sort_path = acus_root / "music" / "MusicSort.xml"
    if not sort_path.exists():
        return
    try:
        root = ET.parse(sort_path).getroot()
    except ET.ParseError:
        return
    sl = root.find("SortList")
    if sl is None:
        return
    for n in sl.findall("StringID/id"):
        if (n.text or "").strip() == str(int(music_id)):
            return
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(int(music_id))
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


def write_ultima_unlock_event(
    acus_root: Path,
    *,
    event_id: int,
    music_id: int,
    music_title: str,
) -> Path:
    """
    PenguinTools EventXml(eventId, MusicType.Ultima, musics): type=3, musicType=2.
    """
    ev_dir = acus_root / "event" / f"event{int(event_id):08d}"
    ev_dir.mkdir(parents=True, exist_ok=True)
    ev_path = ev_dir / "Event.xml"

    root = ET.Element("EventData", {"xmlns:xsi": XSI, "xmlns:xsd": XSD})
    ET.SubElement(root, "dataName").text = f"event{int(event_id):08d}"
    _entry_el(root, "netOpenName", NET_OPEN_ID, NET_OPEN_STR, "")
    event_title = "ULT解禁"
    _entry_el(root, "name", int(event_id), event_title, "")
    ET.SubElement(root, "text").text = ""
    _invalid_entry(root, "ddsBannerName")
    ET.SubElement(root, "periodDispType").text = "1"
    ET.SubElement(root, "alwaysOpen").text = "true"
    ET.SubElement(root, "teamOnly").text = "false"
    ET.SubElement(root, "isKop").text = "false"
    ET.SubElement(root, "priority").text = "0"

    subs = ET.SubElement(root, "substances")
    ET.SubElement(subs, "type").text = "3"
    flag = ET.SubElement(subs, "flag")
    ET.SubElement(flag, "value").text = "0"
    info = ET.SubElement(subs, "information")
    ET.SubElement(info, "informationType").text = "0"
    ET.SubElement(info, "informationDispType").text = "0"
    _invalid_entry(info, "mapFilterID")
    cn = ET.SubElement(info, "courseNames")
    ET.SubElement(cn, "list")
    ET.SubElement(info, "text").text = ""
    _path_el(info, "image", "")
    _invalid_entry(info, "movieName")
    pn = ET.SubElement(info, "presentNames")
    ET.SubElement(pn, "list")

    mp = ET.SubElement(subs, "map")
    ET.SubElement(mp, "tagText").text = ""
    _invalid_entry(mp, "mapName")
    mns = ET.SubElement(mp, "musicNames")
    ET.SubElement(mns, "list")

    mus = ET.SubElement(subs, "music")
    ET.SubElement(mus, "musicType").text = "2"
    mnl = ET.SubElement(mus, "musicNames")
    lst = ET.SubElement(mnl, "list")
    sid = ET.SubElement(lst, "StringID")
    ET.SubElement(sid, "id").text = str(int(music_id))
    ET.SubElement(sid, "str").text = _xml_esc(music_title) or str(music_id)
    ET.SubElement(sid, "data").text = ""

    am = ET.SubElement(subs, "advertiseMovie")
    _invalid_entry(am, "firstMovieName")
    _invalid_entry(am, "secondMovieName")
    rm = ET.SubElement(subs, "recommendMusic")
    rml = ET.SubElement(rm, "musicNames")
    ET.SubElement(rml, "list")
    rel = ET.SubElement(subs, "release")
    ET.SubElement(rel, "value").text = "0"
    ce = ET.SubElement(subs, "course")
    cel = ET.SubElement(ce, "courseNames")
    ET.SubElement(cel, "list")
    qe = ET.SubElement(subs, "quest")
    qel = ET.SubElement(qe, "questNames")
    ET.SubElement(qel, "list")
    de = ET.SubElement(subs, "duel")
    _invalid_entry(de, "duelName")
    cme = ET.SubElement(subs, "cmission")
    _invalid_entry(cme, "cmissionName")
    csu = ET.SubElement(subs, "changeSurfBoardUI")
    ET.SubElement(csu, "value").text = "0"
    ag = ET.SubElement(subs, "avatarAccessoryGacha")
    _invalid_entry(ag, "avatarAccessoryGachaName")
    ri = ET.SubElement(subs, "rightsInfo")
    ril = ET.SubElement(ri, "rightsNames")
    ET.SubElement(ril, "list")
    pr = ET.SubElement(subs, "playRewardSet")
    _invalid_entry(pr, "playRewardSetName")
    db = ET.SubElement(subs, "dailyBonusPreset")
    _invalid_entry(db, "dailyBonusPresetName")
    mb = ET.SubElement(subs, "matchingBonus")
    _invalid_entry(mb, "timeTableName")
    uc = ET.SubElement(subs, "unlockChallenge")
    _invalid_entry(uc, "unlockChallengeName")

    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(ev_path, encoding="utf-8", xml_declaration=True)
    append_event_sort(acus_root, int(event_id))
    return ev_path


def build_music_xml(
    *,
    chuni_id: int,
    title: str,
    artist: str,
    sort_name: str,
    stage_id: int,
    stage_str: str,
    genre_id: int,
    genre_str: str,
    jacket_rel: str,
    slot_map: dict[str, Path],
    levels_by_type: dict[str, tuple[int, int]],
) -> ET.ElementTree:
    mid = int(chuni_id)
    enable_ultima = "ULTIMA" in slot_map

    root = ET.Element("MusicData", {"xmlns:xsi": XSI, "xmlns:xsd": XSD})
    ET.SubElement(root, "dataName").text = f"music{mid:04d}"
    _entry_el(root, "releaseTagName", PJSK_RELEASE_TAG_ID, PJSK_RELEASE_TAG_STR, "")
    _entry_el(root, "netOpenName", NET_OPEN_ID, NET_OPEN_STR, "")
    ET.SubElement(root, "disableFlag").text = "false"
    ET.SubElement(root, "exType").text = "0"
    _entry_el(root, "name", mid, _xml_esc(title) or str(mid), "")
    ET.SubElement(root, "sortName").text = _xml_esc(sort_name or title)
    _entry_el(root, "artistName", mid, _xml_esc(artist) or "PJSK", "")

    gn = ET.SubElement(root, "genreNames")
    gl = ET.SubElement(gn, "list")
    gs = ET.SubElement(gl, "StringID")
    ET.SubElement(gs, "id").text = str(int(genre_id))
    ET.SubElement(gs, "str").text = _xml_esc(genre_str)
    ET.SubElement(gs, "data").text = ""

    _invalid_entry(root, "worksName")
    _invalid_entry(root, "labelName")
    _path_el(root, "jaketFile", jacket_rel)
    ET.SubElement(root, "firstLock").text = "false"
    ET.SubElement(root, "enableUltima").text = "true" if enable_ultima else "false"
    ET.SubElement(root, "isGiftMusic").text = "false"
    ET.SubElement(root, "releaseDate").text = ""
    ET.SubElement(root, "priority").text = "0"
    _entry_el(root, "cueFileName", mid, f"music{mid:04d}", "")
    _invalid_entry(root, "worldsEndTagName")
    ET.SubElement(root, "starDifType").text = "0"
    _entry_el(root, "stageName", int(stage_id), _xml_esc(stage_str), "")

    fumens = ET.SubElement(root, "fumens")
    for idx, (_diff_name, type_str) in enumerate(_FUMEN_ORDER):
        c2s = slot_map.get(type_str) if type_str != "WORLD'S END" else None
        if type_str == "WORLD'S END":
            en = False
        else:
            en = c2s is not None
        fd = ET.SubElement(fumens, "MusicFumenData")
        tid = idx if idx <= 5 else 5
        _entry_el(fd, "type", tid, type_str, "")
        ET.SubElement(fd, "enable").text = "true" if en else "false"
        fname = f"{mid:04d}_{idx:02d}.c2s"
        _path_el(fd, "file", fname if en else "")
        if en:
            lw, ld = levels_by_type.get(type_str, (13, 0))
            lw = max(0, min(99, int(lw)))
            ld = max(0, min(99, int(ld)))
        else:
            lw, ld = 0, 0
        ET.SubElement(fd, "level").text = str(lw)
        ET.SubElement(fd, "levelDecimal").text = str(ld)
        ET.SubElement(fd, "notesDesigner").text = ""
        ET.SubElement(fd, "defaultBpm").text = "0"

    return ET.ElementTree(root)


@dataclass
class PjskAcusInstallOptions:
    chuni_music_id: int
    title: str
    artist: str
    sort_name: str
    stage_id: int
    stage_str: str
    genre_id: int = -1
    genre_str: str = "Invalid"
    # BASIC / ADVANCED / EXPERT / MASTER / ULTIMA -> (level, levelDecimal)
    fumen_levels: dict[str, tuple[int, int]] | None = None
    preview_start_sec: float = 0.0
    preview_stop_sec: float = 30.0
    create_ultima_event: bool = True
    ultima_event_id: int | None = None

    def levels_map(self) -> dict[str, tuple[int, int]]:
        d = self.fumen_levels or {}
        return {k: (int(v[0]), int(v[1])) for k, v in d.items()}


def install_pjsk_bundle_to_acus(
    acus_root: Path,
    bundle: PjskLocalBundle,
    opts: PjskAcusInstallOptions,
    *,
    tool_path: Path | None,
    log: Callable[[str], None],
    on_progress: Callable[[str, float], None] | None = None,
) -> None:
    def _prog(msg: str, t: float) -> None:
        if on_progress:
            on_progress(msg, max(0.0, min(1.0, t)))

    acus_root = acus_root.resolve()
    mid = int(opts.chuni_music_id)
    mdir = acus_root / "music" / f"music{mid:04d}"
    if mdir.exists():
        raise FileExistsError(f"已存在乐曲目录：{mdir}")

    slot_map = _build_slot_map(bundle, log)
    if not slot_map:
        raise ValueError(
            "manifest 中没有任何可用谱面（请确认 sus/ 下已有 SUS，或 chuni/ 下已有 c2s）。"
        )
    if not any(slot_map.get(s) for s in ("BASIC", "ADVANCED", "EXPERT", "MASTER")):
        raise ValueError("至少需要 Basic～Master 中一张谱面才能写入 Music.xml。")

    jacket_png = bundle.root / "封面.png"
    if not jacket_png.is_file():
        raise FileNotFoundError(f"缺少封面：{jacket_png}")

    copy_list = [c for c in ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA") if c in slot_map]
    n_copy = len(copy_list)
    need_ult_ev = bool(_has_ultima(slot_map) and opts.create_ultima_event)
    # prepare + jacket + copies + Music.xml + wav + acb + sort + optional ULT event
    total_steps = 2 + n_copy + 1 + 2 + 1 + (1 if need_ult_ev else 0)
    step_i = 0

    def bump(msg: str) -> None:
        nonlocal step_i
        step_i += 1
        _prog(msg, step_i / max(1, total_steps))

    levels_by_type = opts.levels_map()

    mdir.mkdir(parents=True, exist_ok=True)
    bump("准备目录…")
    jacket_name = f"CHU_UI_Jacket_{mid:04d}.dds"
    jacket_path = mdir / jacket_name
    try:
        convert_to_bc3_dds(tool_path=tool_path, input_image=jacket_png, output_dds=jacket_path)
    except DdsToolError:
        raise
    log(f"已生成封面 DDS：{jacket_name}")
    bump("封面已转为 DDS…")

    for chuni in copy_list:
        src = slot_map[chuni]
        idx = next(i for i, (_, ts) in enumerate(_FUMEN_ORDER) if ts == chuni)
        dst = mdir / f"{mid:04d}_{idx:02d}.c2s"
        shutil.copy2(src, dst)
        log(f"已复制谱面 → {dst.name}")
        bump(f"已复制谱面 {chuni}…")

    tree = build_music_xml(
        chuni_id=mid,
        title=opts.title,
        artist=opts.artist,
        sort_name=opts.sort_name,
        stage_id=opts.stage_id,
        stage_str=opts.stage_str,
        genre_id=opts.genre_id,
        genre_str=opts.genre_str,
        jacket_rel=jacket_name,
        slot_map=slot_map,
        levels_by_type=levels_by_type,
    )
    music_xml = mdir / "Music.xml"
    ET.indent(tree.getroot(), space="  ")  # type: ignore[attr-defined]
    tree.write(music_xml, encoding="utf-8", xml_declaration=True)
    log(f"已写入 {music_xml.relative_to(acus_root)}")
    bump("已写入 Music.xml…")

    bump("准备音频（WAV）…")
    wav = _resolve_wav_for_acb(bundle, log)
    cue_parent = acus_root / "cueFile" / f"cueFile{mid:06d}"
    cue_parent.mkdir(parents=True, exist_ok=True)
    bump("正在编码 ACB / AWB（可能较慢）…")
    pjsk_ac.build_chuni_music_acb_awb(
        wav_48k_stereo_s16_path=wav,
        music_id=mid,
        out_dir=cue_parent,
        preview_start_sec=opts.preview_start_sec,
        preview_stop_sec=opts.preview_stop_sec,
    )
    log(f"已写入音频：{cue_parent.relative_to(acus_root)}")
    bump("音频 ACB/AWB 已完成…")

    append_music_sort(acus_root, mid)
    bump("已更新 MusicSort（若存在）…")

    if need_ult_ev:
        eid = opts.ultima_event_id
        if eid is None:
            eid = next_custom_event_id(acus_root, start=70000)
        write_ultima_unlock_event(
            acus_root,
            event_id=int(eid),
            music_id=mid,
            music_title=opts.title,
        )
        log(f"已写入 ULT 解锁事件 event{int(eid):08d}")
        bump("已写入 ULT 解锁事件…")

    _prog("完成", 1.0)
