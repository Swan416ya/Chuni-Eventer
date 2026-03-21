"""
将 ACUS/map/**/Map.xml 的地图头字段改为与 A001 map02006619 一致（活动/Collaboration 用图）：

- netDispPeriod → true
- mapType → 2
- mapFilterID → id 0 / Collaboration / イベント

用法：python -m chuni_eventer_desktop.migrate_map_xml [ACUS 根目录]
默认 ACUS 为当前工作区上一级的 ACUS（与仓库根并列时）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_MAP_FILTER_RE = re.compile(r"<mapFilterID>[\s\S]*?</mapFilterID>", re.MULTILINE)
_MAP_FILTER_NEW = """<mapFilterID>
    <id>0</id>
    <str>Collaboration</str>
    <data>イベント</data>
  </mapFilterID>"""


def patch_map_xml_text(raw: str) -> str:
    s = re.sub(
        r"<netDispPeriod>[\s\S]*?</netDispPeriod>",
        "<netDispPeriod>true</netDispPeriod>",
        raw,
        count=1,
    )
    s = re.sub(r"<mapType>[\s\S]*?</mapType>", "<mapType>2</mapType>", s, count=1)
    s, n = _MAP_FILTER_RE.subn(_MAP_FILTER_NEW, s, count=1)
    if n == 0:
        raise ValueError("未找到 mapFilterID 节点")
    return s


def migrate_acus_maps(acus_root: Path) -> list[Path]:
    map_root = acus_root / "map"
    if not map_root.is_dir():
        return []
    changed: list[Path] = []
    for p in sorted(map_root.glob("**/Map.xml")):
        text = p.read_text(encoding="utf-8")
        if "MapData" not in text:
            continue
        new_text = patch_map_xml_text(text)
        if new_text != text:
            p.write_text(new_text, encoding="utf-8", newline="\n")
            changed.append(p)
    return changed


def main() -> None:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).expanduser().resolve()
    else:
        root = (Path.cwd() / "ACUS").resolve()
    if not root.is_dir():
        print(f"目录不存在：{root}")
        sys.exit(1)
    out = migrate_acus_maps(root)
    for p in out:
        print(f"已更新：{p}")
    print(f"共更新 {len(out)} 个 Map.xml")


if __name__ == "__main__":
    main()
