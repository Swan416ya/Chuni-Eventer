"""
将本工具以前生成的「地图解锁」Event.xml 改为与 A001 マップフラグ一致
（event00018077 Ave Mujica / event00018087 MyGO）：

- substances/type：6 → 2
- information/mapFilterID：改为 Invalid（-1），不再使用 Collaboration

仅处理：名称含「【MapUnlock】」或 substances/type 为 6 且 map/mapName.id 为有效地图 id。

用法：python -m chuni_eventer_desktop.migrate_event_map_flag [ACUS 根目录]
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _map_unlock_event_needs_fix(root: ET.Element) -> bool:
    name_el = root.find("name")
    unlock = False
    if name_el is not None:
        s = name_el.find("str")
        if s is not None and s.text and "【MapUnlock】" in s.text:
            unlock = True
    substances = root.find("substances")
    if substances is None:
        return False
    typ = substances.find("type")
    ttxt = (typ.text or "").strip() if typ is not None else ""
    map_block = substances.find("map")
    if map_block is None:
        return False
    mn = map_block.find("mapName")
    if mn is None:
        return False
    mid_el = mn.find("id")
    if mid_el is None:
        return False
    try:
        mid = int((mid_el.text or "").strip())
    except ValueError:
        return False
    if mid < 0:
        return False
    if unlock or ttxt == "6":
        return True
    return False


def fix_event_map_flag_xml(path: Path) -> bool:
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "EventData":
        return False
    if not _map_unlock_event_needs_fix(root):
        return False
    substances = root.find("substances")
    assert substances is not None
    typ = substances.find("type")
    if typ is not None:
        typ.text = "2"
    info = substances.find("information")
    if info is not None:
        mf = info.find("mapFilterID")
        if mf is not None:
            for tag, val in (("id", "-1"), ("str", "Invalid")):
                el = mf.find(tag)
                if el is not None:
                    el.text = val
    ET.indent(tree.getroot(), space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True, short_empty_elements=False)
    return True


def migrate_acus_events(acus_root: Path) -> list[Path]:
    ev_root = acus_root / "event"
    if not ev_root.is_dir():
        return []
    changed: list[Path] = []
    for p in sorted(ev_root.glob("**/Event.xml")):
        try:
            if fix_event_map_flag_xml(p):
                changed.append(p)
        except Exception:
            continue
    return changed


def main() -> None:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).expanduser().resolve()
    else:
        root = (Path.cwd() / "ACUS").resolve()
    if not root.is_dir():
        print(f"目录不存在：{root}")
        sys.exit(1)
    out = migrate_acus_events(root)
    for p in out:
        print(f"已更新：{p}")
    print(f"共更新 {len(out)} 个 Event.xml")


if __name__ == "__main__":
    main()
