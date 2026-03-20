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
    release_date: str
    stage: IdStr | None
    cue_file: IdStr | None
    levels: tuple[str, ...]
    jacket_path: str


@dataclass(frozen=True)
class MapItem:
    xml_path: Path
    name: IdStr
    map_filter: IdStr | None


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
            stage = _get_idstr(r.find("stageName"))
            cue_file = _get_idstr(r.find("cueFileName"))
            levels: list[str] = []
            for f in r.findall("fumens/MusicFumenData"):
                enabled = (f.findtext("enable") or "").strip().lower()
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
                    stage=stage,
                    cue_file=cue_file,
                    levels=tuple(levels),
                    jacket_path=jacket,
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

