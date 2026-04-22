from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class ReleaseTagEntry:
    id: int
    name: str
    title: str
    xml_path: Path


def _safe_int(text: str | None, default: int) -> int:
    try:
        return int((text or "").strip())
    except Exception:
        return default


def list_release_tags(acus_root: Path) -> list[ReleaseTagEntry]:
    items: list[ReleaseTagEntry] = []
    base = acus_root / "releaseTag"
    if not base.is_dir():
        return items
    for xml_path in base.glob("releaseTag*/ReleaseTag.xml"):
        try:
            root = ET.parse(xml_path).getroot()
        except Exception:
            continue
        rid = _safe_int(root.findtext("name/id"), -1)
        name = (root.findtext("name/str") or "").strip()
        title = (root.findtext("titleName") or "").strip()
        if not name:
            name = f"ReleaseTag{rid}"
        if not title:
            title = name
        items.append(ReleaseTagEntry(id=rid, name=name, title=title, xml_path=xml_path))
    items.sort(key=lambda x: (x.id, x.name.lower()))
    return items


def suggest_next_custom_release_tag_id(acus_root: Path, *, start: int = 700) -> int:
    used: set[int] = set()
    for item in list_release_tags(acus_root):
        used.add(item.id)
    out = max(1, start)
    while out in used:
        out += 1
    return out


def write_release_tag_xml(
    acus_root: Path,
    *,
    release_tag_id: int,
    release_tag_str: str,
    title_name: str | None = None,
) -> Path:
    rid = int(release_tag_id)
    rstr = (release_tag_str or "").strip() or f"ReleaseTag{rid}"
    title = (title_name or "").strip() or rstr
    out_dir = acus_root / "releaseTag" / f"releaseTag{rid:06d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "ReleaseTag.xml"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ReleaseTagData xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <dataName>releaseTag{rid:06d}</dataName>
  <name>
    <id>{rid}</id>
    <str>{_esc(rstr)}</str>
    <data />
  </name>
  <titleName>{_esc(title)}</titleName>
</ReleaseTagData>
"""
    out.write_text(xml, encoding="utf-8")
    return out


def count_music_using_release_tag(acus_root: Path, release_tag_id: int) -> int:
    rid = int(release_tag_id)
    n = 0
    music_root = acus_root / "music"
    if not music_root.is_dir():
        return 0
    for p in music_root.glob("music*/Music.xml"):
        try:
            root = ET.parse(p).getroot()
            cur = _safe_int(root.findtext("releaseTagName/id"), -10**9)
            if cur == rid:
                n += 1
        except Exception:
            continue
    return n


def delete_release_tag(acus_root: Path, release_tag_id: int) -> Path | None:
    rid = int(release_tag_id)
    for item in list_release_tags(acus_root):
        if item.id == rid:
            dir_path = item.xml_path.parent
            if dir_path.is_dir():
                shutil.rmtree(dir_path)
                return dir_path
            return item.xml_path
    return None


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
