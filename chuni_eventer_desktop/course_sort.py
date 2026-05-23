"""
ACUS ``course/CourseSort.xml``：从游戏数据包复制官方底稿，再将自制课题 id 追加到末尾。
"""
from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from .acus_workspace import _parse_optional_game_root

_SORT_EMPTY_SHELL = """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>course</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
"""


def _safe_int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def course_sort_path(acus_root: Path) -> Path:
    return acus_root / "course" / "CourseSort.xml"


def resolve_game_course_sort_path(game_root: Path) -> Path | None:
    """
    在游戏数据目录下只读定位 ``course/CourseSort.xml``（优先较新的 A??? 数据包）。
    """
    try:
        gr = game_root.expanduser().resolve(strict=False)
    except OSError:
        return None
    if not gr.is_dir():
        return None

    from .game_data_index import enumerate_game_data_roots

    candidates: list[Path] = [
        gr / "data" / "A001" / "course" / "CourseSort.xml",
        gr / "data" / "a001" / "course" / "CourseSort.xml",
        gr / "A001" / "course" / "CourseSort.xml",
    ]
    try:
        packs = sorted(enumerate_game_data_roots(gr), key=lambda p: p.name.upper(), reverse=True)
    except OSError:
        packs = []
    for pack in packs:
        candidates.append(pack / "course" / "CourseSort.xml")

    seen: set[str] = set()
    best: Path | None = None
    best_count = -1
    for cand in candidates:
        key = str(cand).casefold()
        if key in seen:
            continue
        seen.add(key)
        if not cand.is_file():
            continue
        n = len(parse_course_sort_ids(cand))
        if n > best_count:
            best_count = n
            best = cand
    return best


def parse_course_sort_ids(sort_xml: Path) -> list[int]:
    try:
        root = ET.parse(sort_xml).getroot()
    except (OSError, ET.ParseError):
        return []
    sl = root.find("SortList")
    if sl is None:
        return []
    out: list[int] = []
    for n in sl.findall("StringID/id"):
        v = _safe_int(n.text)
        if v is not None:
            out.append(v)
    return out


def collect_acus_course_name_ids(acus_root: Path) -> set[int]:
    used: set[int] = set()
    root = acus_root / "course"
    if not root.is_dir():
        return used
    for p in root.glob("course*/Course.xml"):
        try:
            r = ET.parse(p).getroot()
            v = _safe_int(r.findtext("name/id"))
            if v is not None:
                used.add(v)
        except Exception:
            continue
    return used


def _write_sort_root(sort_path: Path, root: ET.Element) -> None:
    if root.tag != "SerializeSortData":
        pass
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    dn = root.find("dataName")
    if dn is None:
        dn = ET.SubElement(root, "dataName")
    if not (dn.text or "").strip():
        dn.text = "course"
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


def ensure_course_sort_from_game(acus_root: Path, game_root: Path | str | None) -> None:
    """
    若 ACUS 尚无 CourseSort，或现有条目明显少于官包底稿，则从游戏目录复制官方文件。
    只写入 ACUS，不修改游戏安装目录。
    """
    dst = course_sort_path(acus_root)
    dst.parent.mkdir(parents=True, exist_ok=True)

    gr = _parse_optional_game_root(game_root)
    game_src = resolve_game_course_sort_path(gr) if gr is not None else None

    if game_src is not None and game_src.is_file():
        try:
            clash = dst.exists() and game_src.resolve() == dst.resolve()
        except OSError:
            clash = False
        if not clash:
            game_ids = parse_course_sort_ids(game_src)
            local_ids = parse_course_sort_ids(dst) if dst.is_file() else []
            if not dst.is_file() or len(local_ids) < len(game_ids):
                shutil.copyfile(game_src, dst)
                return

    if not dst.is_file():
        dst.write_text(_SORT_EMPTY_SHELL, encoding="utf-8", newline="\n")


def append_course_sort(
    acus_root: Path,
    course_ids: list[int],
    *,
    game_root: Path | str | None = None,
) -> None:
    """
    确保 CourseSort 含官包底稿后，将指定课题 id（及 ACUS 内已有自制课题）追加到 SortList 末尾。
    """
    if game_root is None:
        from .acus_workspace import AcusConfig

        game_root = AcusConfig.load().game_root

    ensure_course_sort_from_game(acus_root, game_root)

    sort_path = course_sort_path(acus_root)
    if not sort_path.is_file():
        sort_path.write_text(_SORT_EMPTY_SHELL, encoding="utf-8", newline="\n")

    root = ET.parse(sort_path).getroot()
    sl = root.find("SortList")
    if sl is None:
        return

    existing: set[int] = set()
    for n in sl.findall("StringID/id"):
        v = _safe_int(n.text)
        if v is not None:
            existing.add(v)

    to_add: list[int] = []
    for cid in sorted(collect_acus_course_name_ids(acus_root) | {int(x) for x in course_ids}):
        if cid not in existing:
            to_add.append(cid)

    for cid in to_add:
        s = ET.SubElement(sl, "StringID")
        ET.SubElement(s, "id").text = str(int(cid))
        ET.SubElement(s, "str")
        ET.SubElement(s, "data")
        existing.add(cid)

    _write_sort_root(sort_path, root)
