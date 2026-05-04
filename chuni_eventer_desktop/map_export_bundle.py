"""
从 ACUS 导出单张地图及其在 ACUS 内可解析的关联资源，打成 zip。
包内路径相对于 ACUS 根（如 map/map02006570/、mapArea/、reward/、event/…），与数据包层级一致。

含：地图解锁类 Event（``substances/map/mapName/id`` 与 Map.xml ``name/id`` 一致时，整包 ``event/event…/`` 目录）。
不含 ``event/EventSort.xml``（全局排序表）；合并到其他 ACUS 时需自行把对应事件条目并入目标 EventSort。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterable

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


def collect_map_bundle_files(*, acus_root: Path, map_xml_path: Path) -> list[Path]:
    """
    收集 map 目录、Map.xml 引用的 mapArea/ddsMap、各层 reward 及 reward 物质在 ACUS 内存在的实体目录/文件。
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
