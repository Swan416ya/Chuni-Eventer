"""
从 ACUS 导出单张地图及其在 ACUS 内可解析的关联资源，打成 zip。
包内路径相对于 ACUS 根（如 map/map02006570/、mapArea/、reward/、event/…），与数据包层级一致。

含：地图解锁类 Event（``substances/map/mapName/id`` 与 Map.xml ``name/id`` 一致时，整包 ``event/event…/`` 目录）。
不含 ``event/EventSort.xml``（全局排序表）；合并到其他 ACUS 时需自行把对应事件条目并入目标 EventSort。

在首轮收集后，会对包内已纳入的 **XML** 做 **引用闭包**：解析 ``path`` 相对路径及常见 ``*Name/id``，
反复加入 chara/ddsImage、ddsMap、Music/cueFile/stage、MapBonus、Event 等关联目录，直至不再增长（有轮数上限）。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable

from .chuni_formats import ChuniCharaId
from .mapbonus_xml import FIELD_PATHS
from .music_delete import _resolve_cue_dir, _resolve_stage_dir
from .system_voice_pack import cue_folder_name, cue_numeric_id_for_voice, system_voice_dir_name


def _safe_int(text: str | None) -> int | None:
    try:
        t = (text or "").strip()
        if not t:
            return None
        return int(t)
    except ValueError:
        return None


def _is_under_acus(acus_root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(acus_root.resolve())
        return True
    except ValueError:
        return False


def _resource_dir_by_xml_glob(acus_root: Path, glob_pat: str, want_id: int) -> Path | None:
    for xp in acus_root.glob(glob_pat):
        if not xp.is_file():
            continue
        try:
            root = ET.parse(xp).getroot()
            nid = _safe_int(root.findtext("name/id") or "")
            if nid == want_id:
                return xp.parent
        except Exception:
            continue
    return None


def resolve_reward_xml_acus(acus_root: Path, rid: int) -> Path | None:
    """仅在 ACUS/reward 下解析 Reward.xml（不扫 A001/游戏包）。"""
    if rid < 0:
        return None
    root = acus_root / "reward"
    p9 = root / f"reward{rid:09d}" / "Reward.xml"
    if p9.is_file():
        return p9
    alt = root / f"reward{rid}" / "Reward.xml"
    if alt.is_file():
        return alt
    if not root.is_dir():
        return None
    try:
        for folder in root.iterdir():
            if not folder.is_dir():
                continue
            rx = folder / "Reward.xml"
            if not rx.is_file():
                continue
            try:
                rr = ET.parse(rx).getroot()
                if _safe_int(rr.findtext("name/id") or "") == rid:
                    return rx
            except Exception:
                continue
    except OSError:
        pass
    return None


def _add_dir_all_files(acus_root: Path, d: Path, into: set[Path]) -> None:
    if not d.is_dir() or not _is_under_acus(acus_root, d):
        return
    try:
        for f in d.rglob("*"):
            if f.is_file():
                into.add(f.resolve())
    except OSError:
        pass


def _enqueue_music_for_substance(acus_root: Path, sub: ET.Element, into: set[Path]) -> None:
    mid = _safe_int(sub.findtext("music/musicName/id") or "")
    if mid is not None and mid >= 0:
        d = _resource_dir_by_xml_glob(acus_root, "music/**/Music.xml", mid)
        if d is not None:
            _add_dir_all_files(acus_root, d, into)


def _expand_reward_substances(acus_root: Path, reward_root: ET.Element, into: set[Path]) -> None:
    for sub in reward_root.findall(".//RewardSubstanceData"):
        t = _safe_int(sub.findtext("type") or "") or 0
        if t == 1:
            tid = _safe_int(sub.findtext("ticket/ticketName/id") or "")
            if tid is not None and tid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "ticket/**/Ticket.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
        elif t == 2:
            tid = _safe_int(sub.findtext("trophy/trophyName/id") or "")
            if tid is not None and tid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "trophy/**/Trophy.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            _enqueue_music_for_substance(acus_root, sub, into)
        elif t == 3:
            cid = _safe_int(sub.findtext("chara/charaName/id") or "")
            if cid is not None and cid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "chara/**/Chara.xml", cid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            _enqueue_music_for_substance(acus_root, sub, into)
        elif t == 5:
            nid = _safe_int(sub.findtext("namePlate/namePlateName/id") or "")
            if nid is not None and nid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "namePlate/**/NamePlate.xml", nid)
                if d is None:
                    d = _resource_dir_by_xml_glob(acus_root, "nameplate/**/NamePlate.xml", nid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            _enqueue_music_for_substance(acus_root, sub, into)
        elif t == 6:
            mid = _safe_int(sub.findtext("music/musicName/id") or "")
            if mid is not None and mid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "music/**/Music.xml", mid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
        elif t == 7:
            iid = _safe_int(sub.findtext("mapIcon/mapIconName/id") or "")
            if iid is not None and iid >= 0:
                for pat in ("mapIcon/**/MapIcon.xml", "mapIcon/**/Mapicon.xml"):
                    d = _resource_dir_by_xml_glob(acus_root, pat, iid)
                    if d is not None:
                        _add_dir_all_files(acus_root, d, into)
                        break
        elif t == 8:
            vid = _safe_int(sub.findtext("systemVoice/systemVoiceName/id") or "")
            if vid is not None and vid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "systemVoice/**/SystemVoice.xml", vid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
                else:
                    sv_fallback = acus_root / "systemVoice" / system_voice_dir_name(vid)
                    _add_dir_all_files(acus_root, sv_fallback, into)
                cue_id = cue_numeric_id_for_voice(vid)
                cue_d = acus_root / "cueFile" / cue_folder_name(cue_id)
                _add_dir_all_files(acus_root, cue_d, into)
        elif t == 9:
            aid = _safe_int(sub.findtext("avatarAccessory/avatarAccessoryName/id") or "")
            if aid is not None and aid >= 0:
                for pat in (
                    "avatarAccessory/**/AvatarAccessory.xml",
                    "avatarAccessory/**/avatarAccessory.xml",
                ):
                    d = _resource_dir_by_xml_glob(acus_root, pat, aid)
                    if d is not None:
                        _add_dir_all_files(acus_root, d, into)
                        break
        elif t == 13:
            sid = _safe_int(sub.findtext("stage/stageName/id") or "")
            if sid is not None and sid >= 0:
                d = _resource_dir_by_xml_glob(acus_root, "stage/**/Stage.xml", sid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)


def _enqueue_reward_chain(acus_root: Path, rid: int, into: set[Path], seen: set[int]) -> None:
    if rid < 0 or rid in seen:
        return
    rx = resolve_reward_xml_acus(acus_root, rid)
    if rx is None or not rx.is_file():
        return
    seen.add(rid)
    _add_dir_all_files(acus_root, rx.parent, into)
    try:
        root = ET.parse(rx).getroot()
        _expand_reward_substances(acus_root, root, into)
    except Exception:
        pass


def _enqueue_events_referencing_map(acus_root: Path, map_id: int, into: set[Path]) -> None:
    """收集 substances/map/mapName/id 指向该地图的 Event 目录（含目录内全部文件）。"""
    if map_id < 0:
        return
    ev_root = acus_root / "event"
    if not ev_root.is_dir():
        return
    try:
        for ev_xml in ev_root.glob("**/Event.xml"):
            if not ev_xml.is_file() or not _is_under_acus(acus_root, ev_xml):
                continue
            try:
                r = ET.parse(ev_xml).getroot()
                mid = _safe_int(r.findtext("substances/map/mapName/id") or "")
            except Exception:
                continue
            if mid != map_id:
                continue
            _add_dir_all_files(acus_root, ev_xml.parent, into)
    except OSError:
        pass


def _apply_map_xml_tree(
    acus_root: Path, root: ET.Element, into: set[Path], seen_reward: set[int]
) -> None:
    """根据已解析的 MapData 根节点，纳入 mapArea / 层奖励 / 音乐 / ddsMap 及地图解锁 Event。"""
    map_id = _safe_int(root.findtext("name/id") or "")
    if map_id is not None and map_id >= 0:
        _enqueue_events_referencing_map(acus_root, map_id, into)
    for info in root.findall("infos/MapDataAreaInfo"):
        aid = _safe_int(info.findtext("mapAreaName/id") or "")
        if aid is not None and aid >= 0:
            _enqueue_maparea(acus_root, aid, into, seen_reward)

        rid = _safe_int(info.findtext("rewardName/id") or "")
        if rid is not None:
            _enqueue_reward_chain(acus_root, rid, into, seen_reward)

        mid = _safe_int(info.findtext("musicName/id") or "")
        if mid is not None and mid >= 0:
            d = _resource_dir_by_xml_glob(acus_root, "music/**/Music.xml", mid)
            if d is not None:
                _add_dir_all_files(acus_root, d, into)

        did = _safe_int(info.findtext("ddsMapName/id") or "")
        if did is not None and did >= 0:
            for pat in ("ddsMap/**/DDSMap.xml", "ddsMap/**/DdsMap.xml"):
                d = _resource_dir_by_xml_glob(acus_root, pat, did)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
                    break


def _enqueue_maparea(acus_root: Path, area_id: int, into: set[Path], seen_reward: set[int]) -> None:
    if area_id < 0:
        return
    area_dir = acus_root / "mapArea" / f"mapArea{area_id:08d}"
    if not area_dir.is_dir():
        return
    _add_dir_all_files(acus_root, area_dir, into)
    ma = area_dir / "MapArea.xml"
    if not ma.is_file():
        return
    try:
        r = ET.parse(ma).getroot()
        bid = _safe_int(r.findtext("mapBonusName/id") or "")
        if bid is not None and bid >= 0:
            bd = _resource_dir_by_xml_glob(acus_root, "mapBonus/**/MapBonus.xml", bid)
            if bd is not None:
                _add_dir_all_files(acus_root, bd, into)
        for gd in r.findall("grids/MapAreaGridData"):
            rid = _safe_int(gd.findtext("reward/rewardName/id") or "")
            if rid is not None:
                _enqueue_reward_chain(acus_root, rid, into, seen_reward)
    except Exception:
        pass


_MAX_CLOSURE_PASSES = 400


def _enqueue_path_texts_in_tree(acus_root: Path, base_dir: Path, root: ET.Element, into: set[Path]) -> None:
    """将树中所有 ``<path>`` 文本视为相对 ``base_dir`` 的文件或目录，若在 ACUS 内则纳入。"""
    ar = acus_root.resolve()
    for el in root.iter():
        if (el.tag or "") != "path":
            continue
        raw = (el.text or "").strip()
        if not raw:
            continue
        try:
            cand = (base_dir / raw).resolve()
        except OSError:
            continue
        try:
            cand.relative_to(ar)
        except ValueError:
            continue
        if cand.is_file():
            into.add(cand)
        elif cand.is_dir():
            _add_dir_all_files(acus_root, cand, into)


def _enqueue_release_tag_by_id(acus_root: Path, rt_id: int, into: set[Path]) -> None:
    if rt_id is None or rt_id < 0:
        return
    d = _resource_dir_by_xml_glob(acus_root, "releaseTag/**/ReleaseTag.xml", rt_id)
    if d is not None:
        _add_dir_all_files(acus_root, d, into)


def _enqueue_netopen_by_id(acus_root: Path, no_id: int, into: set[Path]) -> None:
    if no_id is None or no_id < 0:
        return
    for pat in ("netOpen/**/NetOpen.xml", "netopen/**/NetOpen.xml"):
        d = _resource_dir_by_xml_glob(acus_root, pat, no_id)
        if d is not None:
            _add_dir_all_files(acus_root, d, into)
            return


def _enqueue_gauge_by_id(acus_root: Path, gid: int, into: set[Path]) -> None:
    if gid is None or gid < 0:
        return
    for pat in ("gauge/**/Gauge.xml", "gauge/**/gauge.xml"):
        d = _resource_dir_by_xml_glob(acus_root, pat, gid)
        if d is not None:
            _add_dir_all_files(acus_root, d, into)
            return


def _enqueue_time_table_by_id(acus_root: Path, tid: int, into: set[Path]) -> None:
    if tid is None or tid < 0:
        return
    for pat in ("timeTable/**/TimeTable.xml", "timeTable/**/Timetable.xml"):
        d = _resource_dir_by_xml_glob(acus_root, pat, tid)
        if d is not None:
            _add_dir_all_files(acus_root, d, into)
            return


def _enqueue_event_dir_by_id(acus_root: Path, eid: int, into: set[Path]) -> None:
    if eid is None or eid < 0:
        return
    ed = acus_root / "event" / f"event{eid:08d}"
    _add_dir_all_files(acus_root, ed, into)


def _expand_mapbonus_substances_closure(acus_root: Path, root: ET.Element, into: set[Path], seen_reward: set[int]) -> None:
    for sub in root.findall("substances/list/MapBonusSubstanceData"):
        for fld, (outer, leaf) in FIELD_PATHS.items():
            tid = _safe_int(sub.findtext(f"{outer}/{leaf}/id") or "")
            if tid is None or tid < 0:
                continue
            if fld == "chara":
                d = _resource_dir_by_xml_glob(acus_root, "chara/**/Chara.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            elif fld == "music":
                d = _resource_dir_by_xml_glob(acus_root, "music/**/Music.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            elif fld == "musicWorks":
                _enqueue_release_tag_by_id(acus_root, tid, into)
            elif fld == "charaWorks":
                cwd = acus_root / "charaWorks" / f"charaWorks{tid:06d}"
                _add_dir_all_files(acus_root, cwd, into)
            elif fld == "skill":
                d = _resource_dir_by_xml_glob(acus_root, "skill/**/Skill.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            elif fld == "skillCategory":
                d = _resource_dir_by_xml_glob(acus_root, "skillCategory/**/SkillCategory.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            elif fld == "musicGenre":
                d = _resource_dir_by_xml_glob(acus_root, "musicGenre/**/MusicGenre.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)
            elif fld == "musicLabel":
                d = _resource_dir_by_xml_glob(acus_root, "musicLabel/**/MusicLabel.xml", tid)
                if d is not None:
                    _add_dir_all_files(acus_root, d, into)


def _expand_chara_xml_closure(
    acus_root: Path, root: ET.Element, xml_path: Path, into: set[Path], seen_reward: set[int]
) -> None:
    base = xml_path.parent
    _enqueue_path_texts_in_tree(acus_root, base, root, into)
    cid_raw = _safe_int(root.findtext("name/id") or "")
    if cid_raw is not None and cid_raw >= 0:
        try:
            cid_fmt = ChuniCharaId(cid_raw)
            dds_dir = acus_root / "ddsImage" / f"ddsImage{cid_fmt.raw6}"
            _add_dir_all_files(acus_root, dds_dir, into)
        except Exception:
            pass
    for n in range(1, 10):
        sec = root.find(f"addImages{n}")
        if sec is None:
            continue
        aid = _safe_int(sec.findtext("charaName/id") or "")
        if aid is not None and aid >= 0:
            d = _resource_dir_by_xml_glob(acus_root, "chara/**/Chara.xml", aid)
            if d is not None:
                _add_dir_all_files(acus_root, d, into)
    wi = _safe_int(root.findtext("works/id") or "")
    if wi is not None and wi >= 0:
        cwd = acus_root / "charaWorks" / f"charaWorks{wi:06d}"
        _add_dir_all_files(acus_root, cwd, into)
    ri = _safe_int(root.findtext("releaseTagName/id") or "")
    _enqueue_release_tag_by_id(acus_root, ri if ri is not None else -1, into)
    ni = _safe_int(root.findtext("netOpenName/id") or "")
    _enqueue_netopen_by_id(acus_root, ni if ni is not None else -1, into)
    for rank in root.findall("ranks/CharaRankData"):
        rsid = _safe_int(rank.findtext("rewardSkillSeed/rewardSkillSeed/id") or "")
        if rsid is not None and rsid >= 0:
            _enqueue_reward_chain(acus_root, rsid, into, seen_reward)


def _expand_music_xml_closure(acus_root: Path, root: ET.Element, into: set[Path]) -> None:
    rt = _safe_int(root.findtext("releaseTagName/id") or "")
    _enqueue_release_tag_by_id(acus_root, rt if rt is not None else -1, into)
    nt = _safe_int(root.findtext("netOpenName/id") or "")
    _enqueue_netopen_by_id(acus_root, nt if nt is not None else -1, into)
    st = _safe_int(root.findtext("stageName/id") or "")
    if st is not None and st > 0:
        sd = _resolve_stage_dir(acus_root, st)
        if sd is not None:
            _add_dir_all_files(acus_root, sd, into)
    cf = _safe_int(root.findtext("cueFileName/id") or "")
    if cf is not None and cf > 0:
        cd = _resolve_cue_dir(acus_root, cf)
        if cd is not None:
            _add_dir_all_files(acus_root, cd, into)


def _expand_stage_xml_closure(acus_root: Path, root: ET.Element, into: set[Path]) -> None:
    rt = _safe_int(root.findtext("releaseTagName/id") or "")
    _enqueue_release_tag_by_id(acus_root, rt if rt is not None else -1, into)
    nt = _safe_int(root.findtext("netOpenName/id") or "")
    _enqueue_netopen_by_id(acus_root, nt if nt is not None else -1, into)
    nfl = _safe_int(root.findtext("notesFieldLine/id") or "")
    if nfl is not None and nfl >= 0:
        for pat in ("notesFieldLine/**/NotesFieldLine.xml", "notesFieldLine/**/NoteFieldLine.xml"):
            d = _resource_dir_by_xml_glob(acus_root, pat, nfl)
            if d is not None:
                _add_dir_all_files(acus_root, d, into)
                break


def _expand_map_data_closure(acus_root: Path, root: ET.Element, into: set[Path]) -> None:
    tt = _safe_int(root.findtext("timeTableName/id") or "")
    _enqueue_time_table_by_id(acus_root, tt if tt is not None else -1, into)
    se = _safe_int(root.findtext("stopReleaseEventName/id") or "")
    _enqueue_event_dir_by_id(acus_root, se if se is not None else -1, into)
    for info in root.findall("infos/MapDataAreaInfo"):
        gid = _safe_int(info.findtext("gaugeName/id") or "")
        _enqueue_gauge_by_id(acus_root, gid if gid is not None else -1, into)


def _expand_event_xml_closure(acus_root: Path, root: ET.Element, xml_path: Path, into: set[Path], seen_reward: set[int]) -> None:
    base = xml_path.parent
    _enqueue_path_texts_in_tree(acus_root, base, root, into)
    nt = _safe_int(root.findtext("netOpenName/id") or "")
    _enqueue_netopen_by_id(acus_root, nt if nt is not None else -1, into)
    bid = _safe_int(root.findtext("ddsBannerName/id") or "")
    if bid is not None and bid >= 0:
        for pat in ("ddsBanner/**/DDSBanner.xml", "ddsBanner/**/DdsBanner.xml"):
            d = _resource_dir_by_xml_glob(acus_root, pat, bid)
            if d is not None:
                _add_dir_all_files(acus_root, d, into)
                break
    subs = root.find("substances")
    if subs is not None:
        mid = _safe_int(subs.findtext("map/mapName/id") or "")
        if mid is not None and mid >= 0:
            mdir = map_xml_dir_for_map_id(acus_root, mid)
            if mdir is not None:
                _add_dir_all_files(acus_root, mdir, into)
    for sid in root.findall(".//musicNames/list/StringID"):
        mid = _safe_int(sid.findtext("id") or "")
        if mid is not None and mid >= 0:
            d = _resource_dir_by_xml_glob(acus_root, "music/**/Music.xml", mid)
            if d is not None:
                _add_dir_all_files(acus_root, d, into)


def map_xml_dir_for_map_id(acus_root: Path, map_id: int) -> Path | None:
    """解析 ``map/**/Map.xml`` 中 ``name/id`` 为 ``map_id`` 的目录（用于 Event 引用其它地图时一并导出）。"""
    if map_id < 0:
        return None
    d = _resource_dir_by_xml_glob(acus_root, "map/**/Map.xml", map_id)
    return d


def _expand_one_xml_for_closure(
    acus_root: Path, xml_path: Path, into: set[Path], seen_reward: set[int]
) -> None:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return
    tag = (root.tag or "").strip()
    base = xml_path.parent
    name = xml_path.name

    if name == "Chara.xml" or tag == "CharaData":
        _expand_chara_xml_closure(acus_root, root, xml_path, into, seen_reward)
        return
    if name == "Music.xml" or tag.endswith("MusicData") or tag == "MusicData":
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        _expand_music_xml_closure(acus_root, root, into)
        return
    if name == "DDSMap.xml" or tag.endswith("DDSMapData") or tag == "DDSMapData":
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        return
    if name == "DDSImage.xml" or tag.endswith("DDSImageData") or tag == "DDSImageData":
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        ni = _safe_int(root.findtext("netOpenName/id") or "")
        _enqueue_netopen_by_id(acus_root, ni if ni is not None else -1, into)
        return
    if name == "Stage.xml" or tag.endswith("StageData") or tag == "StageData":
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        _expand_stage_xml_closure(acus_root, root, into)
        return
    if name == "MapBonus.xml" or tag.endswith("MapBonusData") or tag == "MapBonusData":
        _expand_mapbonus_substances_closure(acus_root, root, into, seen_reward)
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        return
    if name == "Reward.xml" or tag.endswith("RewardData") or tag == "RewardData":
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        try:
            _expand_reward_substances(acus_root, root, into)
        except Exception:
            pass
        return
    if name == "Event.xml" or tag.endswith("EventData") or tag == "EventData":
        _expand_event_xml_closure(acus_root, root, xml_path, into, seen_reward)
        return
    if name == "Map.xml" or tag.endswith("MapData") or tag == "MapData":
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        _expand_map_data_closure(acus_root, root, into)
        _apply_map_xml_tree(acus_root, root, into, seen_reward)
        return
    if name in ("Trophy.xml", "NamePlate.xml", "Ticket.xml", "SystemVoice.xml", "AvatarAccessory.xml", "MapArea.xml"):
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        return
    if name == "CueFile.xml" or "CueFile" in tag:
        _enqueue_path_texts_in_tree(acus_root, base, root, into)
        return

    _enqueue_path_texts_in_tree(acus_root, base, root, into)


def _closure_expand_acus_references(acus_root: Path, into: set[Path], seen_reward: set[int]) -> None:
    """对已收集集合内的 XML 反复解析引用，直到不再增长（轮数上限）。"""
    ar = acus_root.resolve()
    seen_xml: set[Path] = set()
    for _ in range(_MAX_CLOSURE_PASSES):
        before = len(into)
        xml_list = [
            p.resolve()
            for p in into
            if p.is_file() and p.suffix.lower() == ".xml" and _is_under_acus(acus_root, p)
        ]
        for xp in sorted(xml_list):
            if xp in seen_xml:
                continue
            seen_xml.add(xp)
            _expand_one_xml_for_closure(acus_root, xp, into, seen_reward)
        if len(into) == before:
            break


def collect_map_bundle_files(*, acus_root: Path, map_xml_path: Path) -> list[Path]:
    """
    收集 map 目录、Map.xml 引用的 mapArea/ddsMap、各层 reward 及 reward 物质在 ACUS 内存在的实体目录/文件；
    并对已纳入的 XML 做引用闭包（chara↔ddsImage、Music↔cue/stage、MapBonus、Event 内 path/乐曲等），直至饱和。
    返回去重后的绝对路径列表（仅文件）。
    """
    acus_root = acus_root.resolve()
    map_xml_path = map_xml_path.resolve()
    if not _is_under_acus(acus_root, map_xml_path):
        raise ValueError("地图 XML 不在当前 ACUS 目录下。")
    into: set[Path] = set()
    seen_reward: set[int] = set()

    map_dir = map_xml_path.parent
    _add_dir_all_files(acus_root, map_dir, into)

    try:
        root = ET.parse(map_xml_path).getroot()
    except Exception as e:
        raise ValueError(f"无法解析 Map.xml：{e}") from e

    _apply_map_xml_tree(acus_root, root, into, seen_reward)

    _closure_expand_acus_references(acus_root, into, seen_reward)

    return sorted(into)


def export_map_bundle_to_zip(
    *,
    acus_root: Path,
    map_xml_path: Path,
    output_zip: Path,
    paths: Iterable[Path] | None = None,
) -> int:
    """
    将 ``collect_map_bundle_files`` 收集到的文件写入 zip，条目中路径为相对 ACUS 根的正斜杠路径。
    若传入 ``paths`` 则使用该列表（便于测试）；否则现场收集。
    返回写入的文件数。
    """
    acus_root = acus_root.resolve()
    output_zip = Path(output_zip).expanduser().resolve()
    files = list(paths) if paths is not None else collect_map_bundle_files(acus_root=acus_root, map_xml_path=map_xml_path)
    if not files:
        raise ValueError("未收集到任何可导出的文件（请确认地图与关联资源均在 ACUS 内）。")
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in files:
            fp = fp.resolve()
            if not fp.is_file():
                continue
            try:
                arc = fp.relative_to(acus_root).as_posix()
            except ValueError:
                continue
            zf.write(fp, arcname=arc)
            written += 1
    if written == 0:
        try:
            output_zip.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError("zip 内未写入任何文件。")
    return written
