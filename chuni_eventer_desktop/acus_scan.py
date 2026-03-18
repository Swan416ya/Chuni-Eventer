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
class EventItem:
    xml_path: Path
    name: IdStr
    event_type: int | None
    map_name: IdStr | None
    map_filter: IdStr | None

    @property
    def kind(self) -> str:
        # Very rough categorization that matches your “宣传类 / 地图解锁类”
        if self.map_name and self.map_name.id != -1:
            return "地图解锁类"
        return "宣传/其他"


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
            jacket = (r.findtext("jaketFile/path") or "").strip()
            items.append(MusicItem(p, name, artist, jacket))
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
            items.append(EventItem(p, name, event_type, map_name, map_filter))
        except Exception:
            continue
    return sorted(items, key=lambda x: x.name.id)

