"""
Install a PJSK cache bundle (pjsk_cache/pjsk_XXXX) into ACUS as official-style music + cueFile.

Aligns with ChuniPingu/PenguinTools Music.xml / Event.xml (ULT unlock) layout:
https://github.com/ChuniPingu/PenguinTools/tree/main/PenguinTools.Core/Xml

「PJSK 谱面 → 中二」的实际转换/打包/落位链路在 :mod:`chuni_eventer_desktop.pjsk2chuni.pipeline`；
本模块只保留两条线都要用的公共件：

* 本地缓存清单（:func:`iter_local_pjsk_bundles` / :func:`chuni_slots_with_c2s` / :func:`chuni_slot_sources`）；
* id 分配、MusicSort 追加、ULT 解锁事件（:func:`append_music_sort` / :func:`write_ultima_unlock_event`）；
* PGKO 线仍在用的 :func:`build_music_xml`（PJSK 线现在由 PenguinTools 生成 Music.xml）。

Release tag for 烤谱: releaseTagName id=-2 str=PJSK (fixed).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .pjsk2chuni.pipeline import SlotSource

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


def next_chuni_music_id(acus_root: Path, *, start: int = 5000) -> int:
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
    cur = max(0, int(start))
    while cur in used:
        cur += 1
    return cur


def _slot_has_chart_source(root: Path, s: dict) -> bool:
    rel_c2s = s.get("c2sFile")
    if rel_c2s and (root / str(rel_c2s)).is_file():
        return True
    rel_sus = s.get("susFile")
    return bool(rel_sus and (root / str(rel_sus)).is_file())


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


def chuni_slot_sources(bundle: PjskLocalBundle) -> list[SlotSource]:
    """缓存清单 → 可转换的 (槽位, SUS 路径) 列表。"""
    root = bundle.root
    out: list[SlotSource] = []
    slots = bundle.manifest.get("slots")
    if not isinstance(slots, list):
        return out
    by_slot: dict[str, SlotSource] = {}
    for s in slots:
        if not isinstance(s, dict):
            continue
        slot = str(s.get("chuniSlot") or "").strip().upper()
        rel = s.get("susFile")
        if not slot or not isinstance(rel, str) or not rel.strip():
            continue
        p = (root / rel.strip()).resolve()
        if p.is_file():
            by_slot[slot] = SlotSource(slot=slot, sus_path=p)
    for slot in ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA"):
        if slot in by_slot:
            out.append(by_slot[slot])
    return out


def bundle_play_levels(bundle: PjskLocalBundle) -> dict[str, int]:
    """清单里记录的 PJSK 难度等级：``{槽位: 1..38}``（老缓存可能为空）。"""
    out: dict[str, int] = {}
    slots = bundle.manifest.get("slots")
    if not isinstance(slots, list):
        return out
    for s in slots:
        if not isinstance(s, dict):
            continue
        slot = str(s.get("chuniSlot") or "").strip().upper()
        try:
            lv = int(s.get("pjskPlayLevel"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if slot and lv > 0:
            out[slot] = lv
    return out


def backfill_bundle_play_levels(
    bundle: PjskLocalBundle,
    levels_by_difficulty: dict[str, int],
) -> bool:
    """把查到的 PJSK 等级（``{难度名: 等级}``）补进 manifest.json；有改动返回 True。"""
    slots = bundle.manifest.get("slots")
    if not isinstance(slots, list) or not levels_by_difficulty:
        return False
    changed = False
    for s in slots:
        if not isinstance(s, dict):
            continue
        diff = str(s.get("pjskDifficulty") or "").strip().lower()
        lv = levels_by_difficulty.get(diff)
        if lv is None or lv <= 0:
            continue
        try:
            if int(s.get("pjskPlayLevel") or 0) == int(lv):
                continue
        except (TypeError, ValueError):
            pass
        s["pjskPlayLevel"] = int(lv)
        changed = True
    if not changed:
        return False
    path = bundle.root / "manifest.json"
    try:
        path.write_text(
            json.dumps(bundle.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        return False
    return True


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
