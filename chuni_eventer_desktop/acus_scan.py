from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class IdStr:
    id: int
    str: str


def _get_idstr(node: ET.Element | None) -> IdStr | None:
    if node is None:
        return None
    id_el = node.find("id")
    str_el = node.find("str")
    if id_el is None or str_el is None:
        return None
    try:
        i = int((id_el.text or "").strip())
    except Exception:
        return None
    return IdStr(i, (str_el.text or "").strip())


@dataclass(frozen=True)
class DdsImageItem:
    xml_path: Path
    name: IdStr
    dds0: str
    dds1: str
    dds2: str


@dataclass(frozen=True)
class MusicItem:
    xml_path: Path
    name: IdStr
    artist: IdStr | None
    genres: tuple[str, ...]
    release_date: str  # Music.xml releaseDate
    release_tag: IdStr | None  # releaseTagName；UI「版本」用 str
    stage: IdStr | None
    cue_file: IdStr | None
    levels: tuple[str, ...]
    jacket_path: str
    # 是否存在已启用的 Ultima 谱面（fumen type/id=4），用于课题称号 rareType=8
    has_ultima: bool


@dataclass(frozen=True)
class MapItem:
    xml_path: Path
    name: IdStr
    map_filter: IdStr | None


@dataclass(frozen=True)
class StageItem:
    xml_path: Path
    name: IdStr
    notes_field_line: IdStr | None
    image_path: str


@dataclass(frozen=True)
class CharaItem:
    xml_path: Path
    name: IdStr
    default_image_key: str


@dataclass(frozen=True)
class NamePlateItem:
    xml_path: Path
    name: IdStr
    image_path: str


@dataclass(frozen=True)
class TrophyItem:
    xml_path: Path
    name: IdStr
    explain_text: str
    rare_type: int | None
    image_path: str


@dataclass(frozen=True)
class RewardItem:
    xml_path: Path
    name: IdStr
    substance_type: int | None
    type_label: str
    target_summary: str
    music_course_id: int | None
    music_course_str: str


@dataclass(frozen=True)
class EventItem:
    xml_path: Path
    name: IdStr
    event_type: int | None
    map_name: IdStr | None
    map_filter: IdStr | None
    dds_banner_id: int | None
    info_image_path: str

    @property
    def is_ult_we_unlock(self) -> bool:
        """
        ULT/WE 曲开锁事件（合并分类）。
        经验规则：substances/type=3 且标题包含 ULT 或 WE。
        """
        if self.event_type != 3:
            return False
        t = self.name.str.upper()
        return ("ULT" in t) or ("WE" in t)

    @property
    def is_map_unlock(self) -> bool:
        return self.map_name is not None and self.map_name.id != -1

    @property
    def promo_dds_path(self) -> Path | None:
        """宣传用 information/image/path，且同目录下存在对应 DDS 文件。"""
        rel = self.info_image_path.strip()
        if not rel:
            return None
        cand = self.xml_path.parent / rel
        return cand if cand.is_file() else None

    @property
    def is_promo_with_dds(self) -> bool:
        return self.promo_dds_path is not None

    @property
    def category_label(self) -> str:
        parts: list[str] = []
        if self.is_ult_we_unlock:
            parts.append("ULT/WE解锁")
        if self.is_map_unlock:
            parts.append("MapUnlock")
        if self.is_promo_with_dds:
            parts.append("Promo+DDS")
        elif self.info_image_path.strip():
            parts.append("Promo(no DDS file)")
        if self.dds_banner_id is not None and self.dds_banner_id != -1:
            parts.append(f"Banner#{self.dds_banner_id}")
        return " | ".join(parts) if parts else "Other"

    @property
    def filter_bucket(self) -> str:
        """与列表筛选下拉框对应：ult_we / map_unlock / promo / other"""
        if self.is_ult_we_unlock:
            return "ult_we"
        if self.is_map_unlock:
            return "map_unlock"
        if self.is_promo_with_dds:
            return "promo"
        return "other"


@dataclass(frozen=True)
class QuestItem:
    xml_path: Path
    name: IdStr
    chara_count: int
    chara_label: str
    tier_label: str


def iter_xml_files(root: Path, rel_glob: str) -> Iterable[Path]:
    yield from root.glob(rel_glob)


def scan_dds_images(acus_root: Path) -> list[DdsImageItem]:
    items: list[DdsImageItem] = []
    for p in iter_xml_files(acus_root, "ddsImage/**/DDSImage.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            d0 = (r.findtext("ddsFile0/path") or "").strip()
            d1 = (r.findtext("ddsFile1/path") or "").strip()
            d2 = (r.findtext("ddsFile2/path") or "").strip()
            items.append(DdsImageItem(p, name, d0, d1, d2))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_music(acus_root: Path) -> list[MusicItem]:
    items: list[MusicItem] = []
    for p in iter_xml_files(acus_root, "music/**/Music.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            artist = _get_idstr(r.find("artistName"))
            genre_names: list[str] = []
            for g in r.findall("genreNames/list/StringID/str"):
                s = (g.text or "").strip()
                if s:
                    genre_names.append(s)
            release_date = (r.findtext("releaseDate") or "").strip()
            release_tag = _get_idstr(r.find("releaseTagName"))
            stage = _get_idstr(r.find("stageName"))
            cue_file = _get_idstr(r.find("cueFileName"))
            levels: list[str] = []
            has_ultima = False
            for f in r.findall("fumens/MusicFumenData"):
                enabled = (f.findtext("enable") or "").strip().lower()
                tid_raw = (f.findtext("type/id") or "").strip()
                tid = int(tid_raw) if tid_raw.isdigit() else -1
                if enabled == "true" and tid == 4:
                    has_ultima = True
                if enabled != "true":
                    continue
                diff = (f.findtext("type/str") or "").strip()
                lv = (f.findtext("level") or "").strip()
                dec_raw = (f.findtext("levelDecimal") or "").strip()
                # 13 + 50 -> 13.5; 10 + 20 -> 10.2
                lv_text = lv
                if lv and dec_raw.isdigit():
                    dec_num = int(dec_raw)
                    if dec_num > 0:
                        # game style decimal is usually 10/20/30.../90
                        lv_text = f"{lv}.{dec_num // 10}" if dec_num % 10 == 0 else f"{lv}.{dec_num}"
                if diff and lv_text:
                    levels.append(f"{diff}:{lv_text}")
            jacket = (r.findtext("jaketFile/path") or "").strip()
            items.append(
                MusicItem(
                    xml_path=p,
                    name=name,
                    artist=artist,
                    genres=tuple(genre_names),
                    release_date=release_date,
                    release_tag=release_tag,
                    stage=stage,
                    cue_file=cue_file,
                    levels=tuple(levels),
                    jacket_path=jacket,
                    has_ultima=has_ultima,
                )
            )
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_maps(acus_root: Path) -> list[MapItem]:
    items: list[MapItem] = []
    for p in iter_xml_files(acus_root, "map/**/Map.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            mf = _get_idstr(r.find("mapFilterID"))
            items.append(MapItem(p, name, mf))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_stages(acus_root: Path) -> list[StageItem]:
    items: list[StageItem] = []
    for p in iter_xml_files(acus_root, "stage/**/Stage.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            nfl = _get_idstr(r.find("notesFieldLine"))
            image = (r.findtext("image/path") or "").strip()
            items.append(StageItem(p, name, nfl, image))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_charas(acus_root: Path) -> list[CharaItem]:
    items: list[CharaItem] = []
    for p in iter_xml_files(acus_root, "chara/**/Chara.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            default_key = (r.findtext("defaultImages/str") or "").strip()
            items.append(CharaItem(p, name, default_key))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_quests(acus_root: Path) -> list[QuestItem]:
    items: list[QuestItem] = []
    for p in iter_xml_files(acus_root, "quest/**/Quest.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            charas = r.findall("charas/list/StringID")
            n_char = len(charas)
            if n_char <= 0:
                cl = "无角色条件"
            elif n_char <= 3:
                bits: list[str] = []
                for c in charas:
                    ids = _get_idstr(c)
                    if ids:
                        bits.append(f"{ids.id}")
                cl = f"{n_char}名·" + ",".join(bits)
            else:
                cl = f"{n_char}名角色"
            tiers: list[str] = []
            for block in r.findall("info/QuestRewardDataInfo"):
                sr = (block.findtext("sumRank") or "").strip()
                if not sr:
                    continue
                t = _get_idstr(block.find("keyTrophyName"))
                n = _get_idstr(block.find("keyNamePlateName"))
                c = _get_idstr(block.find("keyCharaName"))
                if t is not None and t.id != -1:
                    tiers.append(f"{sr}→称号")
                elif n is not None and n.id != -1:
                    tiers.append(f"{sr}→名牌")
                elif c is not None and c.id != -1:
                    tiers.append(f"{sr}→角色")
                else:
                    tiers.append(f"{sr}→?")
            tier_label = " | ".join(tiers) if tiers else "—"
            items.append(QuestItem(p, name, n_char, cl, tier_label))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_events(acus_root: Path) -> list[EventItem]:
    items: list[EventItem] = []
    for p in iter_xml_files(acus_root, "event/**/Event.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            t = r.findtext("substances/type")
            event_type = int(t.strip()) if (t or "").strip().isdigit() else None
            map_name = _get_idstr(r.find("substances/map/mapName"))
            map_filter = _get_idstr(r.find("substances/information/mapFilterID"))
            banner = _get_idstr(r.find("ddsBannerName"))
            banner_id = banner.id if banner else None
            img_path = (r.findtext("substances/information/image/path") or "").strip()
            items.append(
                EventItem(
                    p,
                    name,
                    event_type,
                    map_name,
                    map_filter,
                    banner_id,
                    img_path,
                )
            )
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_nameplates(acus_root: Path) -> list[NamePlateItem]:
    items: list[NamePlateItem] = []
    for p in iter_xml_files(acus_root, "namePlate/**/NamePlate.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            img = (r.findtext("image/path") or "").strip()
            items.append(NamePlateItem(p, name, img))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def scan_trophies(acus_root: Path) -> list[TrophyItem]:
    items: list[TrophyItem] = []
    for p in iter_xml_files(acus_root, "trophy/**/Trophy.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            explain = (r.findtext("explainText") or "").strip()
            rare_raw = (r.findtext("rareType") or "").strip()
            rare_type = int(rare_raw) if rare_raw.isdigit() else None
            img = (r.findtext("image/path") or "").strip()
            items.append(TrophyItem(p, name, explain, rare_type, img))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)


def _int_or_none(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def _reward_substance_type_label(t: int | None) -> str:
    if t is None:
        return "未知"
    return {
        0: "其它",
        1: "功能票",
        2: "称号",
        3: "角色",
        5: "姓名牌",
        6: "乐曲解锁",
        7: "地图图标",
        9: "头像配件",
        13: "场景",
    }.get(t, f"type={t}")


def _pick_reward_substance(root: ET.Element) -> ET.Element | None:
    subs = root.findall(".//RewardSubstanceData")
    if not subs:
        return None
    chosen = subs[0]
    best_score = -1
    for sub in subs:
        t_raw = (sub.findtext("type") or "0").strip()
        t = int(t_raw) if t_raw.isdigit() else 0
        mid = _int_or_none(sub.findtext("music/musicName/id"))
        score = 0
        if t in (2, 3, 5):
            score += 4
        if mid is not None and mid != -1:
            score += 2
        if score > best_score:
            best_score = score
            chosen = sub
    return chosen


def _summarize_reward_substance(sub: ET.Element) -> tuple[int | None, str, str, int | None, str]:
    """
    返回 substance_type, type_label, target_summary, music_course_id, music_course_str
    """
    t_raw = (sub.findtext("type") or "0").strip()
    t = int(t_raw) if t_raw.isdigit() else None
    label = _reward_substance_type_label(t)

    mid = _int_or_none(sub.findtext("music/musicName/id"))
    mstr = (sub.findtext("music/musicName/str") or "").strip()
    if mid == -1:
        mid = None

    parts: list[str] = []
    if t == 1:
        tid = _int_or_none(sub.findtext("ticket/ticketName/id"))
        if tid is not None and tid != -1:
            parts.append(f"功能票ID {tid}")
    elif t == 2:
        tid = _int_or_none(sub.findtext("trophy/trophyName/id"))
        if tid is not None and tid != -1:
            parts.append(f"称号ID {tid}")
    elif t == 3:
        cid = _int_or_none(sub.findtext("chara/charaName/id"))
        if cid is not None and cid != -1:
            parts.append(f"角色ID {cid}")
    elif t == 5:
        nid = _int_or_none(sub.findtext("namePlate/namePlateName/id"))
        if nid is not None and nid != -1:
            parts.append(f"姓名牌ID {nid}")
    elif t == 6:
        if mid is not None:
            parts.append(f"乐曲ID {mid}")
    elif t == 7:
        iid = _int_or_none(sub.findtext("mapIcon/mapIconName/id"))
        if iid is not None and iid != -1:
            parts.append(f"地图图标ID {iid}")
    elif t == 9:
        aid = _int_or_none(sub.findtext("avatarAccessory/avatarAccessoryName/id"))
        if aid is not None and aid != -1:
            parts.append(f"头像配件ID {aid}")
    elif t == 13:
        sid = _int_or_none(sub.findtext("stage/stageName/id"))
        if sid is not None and sid != -1:
            parts.append(f"场景ID {sid}")

    course_id: int | None = None
    course_str = ""
    if t in (2, 3, 5) and mid is not None and mid != -1:
        course_id = mid
        course_str = mstr or f"Music{mid}"
        parts.append(f"课题曲 {mid}")

    summary = "；".join(parts) if parts else "—"
    return t, label, summary, course_id, course_str


def scan_rewards(acus_root: Path) -> list[RewardItem]:
    items: list[RewardItem] = []
    for p in iter_xml_files(acus_root, "reward/**/Reward.xml"):
        try:
            r = ET.parse(p).getroot()
            name = _get_idstr(r.find("name"))
            if not name:
                continue
            sub = _pick_reward_substance(r)
            if sub is None:
                items.append(
                    RewardItem(
                        p,
                        name,
                        None,
                        "（无 RewardSubstanceData）",
                        "—",
                        None,
                        "",
                    )
                )
                continue
            st, tlabel, summary, mc_id, mc_str = _summarize_reward_substance(sub)
            items.append(RewardItem(p, name, st, tlabel, summary, mc_id, mc_str))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)

