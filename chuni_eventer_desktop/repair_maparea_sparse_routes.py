"""
修复因「新建地图」时未传入 grid_indices 而被写成 index 0~8 的 MapArea.xml，
改为与 A001 map02006619 相同的稀疏 index：起点 0、终点前最终奖励、终点 Invalid。

按 Map.xml 中 pageIndex=0 的格子按 indexInPage 排序，依次套用 page0_steps；
pageIndex=1 同理套用 page1_steps。

用法：
  python -m chuni_eventer_desktop.repair_maparea_sparse_routes <ACUS根> <mapXXXXXXXX目录名或8位id>
  python -m chuni_eventer_desktop.repair_maparea_sparse_routes <ACUS根> map70000000 \\
      --page0 25,45,65,85,105 --page1 125,125

默认 page0=25,45,65,85,105 page1=125,125（与 A001 Ave Mujica 第一页五格 + 第二页两格总长相近）。
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _grid_node(ix: int, rid: int, rname: str, dt: int, ct: int) -> str:
    return (
        f"""    <MapAreaGridData>
      <index>{ix}</index><displayType>{dt}</displayType><type>{ct}</type><exit /><entrance />
      <reward><rewardName><id>{rid}</id><str>{_xml_esc(rname)}</str><data /></rewardName></reward>
    </MapAreaGridData>"""
    )


def _parse_areas_from_map(map_xml: Path) -> dict[int, dict[str, object]]:
    root = ET.parse(map_xml).getroot()
    out: dict[int, dict[str, object]] = {}
    for el in root.findall("infos/MapDataAreaInfo"):
        aid = int((el.findtext("mapAreaName/id") or "0").strip())
        out[aid] = {
            "page": int((el.findtext("pageIndex") or "0").strip()),
            "slot": int((el.findtext("indexInPage") or "0").strip()),
            "rid": int((el.findtext("rewardName/id") or "-1").strip()),
            "rstr": (el.findtext("rewardName/str") or "").strip() or "Invalid",
        }
    return out


def _build_grids_inner(total: int, reward_id: int, reward_name: str) -> str:
    parts: list[str] = []
    if total >= 2:
        parts.append(_grid_node(0, -1, "Invalid", 1, 1))
    if total >= 1:
        parts.append(_grid_node(total - 1, reward_id, reward_name, 3, 3))
        parts.append(_grid_node(total, -1, "Invalid", 2, 2))
    return "\n".join(parts)


def _replace_grids_section(raw: str, grids_inner: str) -> str:
    return re.sub(
        r"<grids>\s*[\s\S]*?</grids>",
        f"<grids>\n{grids_inner}\n  </grids>",
        raw,
        count=1,
        flags=re.MULTILINE,
    )


def repair_map(
    acus: Path,
    map_key: str,
    page0_steps: list[int],
    page1_steps: list[int],
) -> list[Path]:
    mid = map_key.replace("map", "").strip()
    if len(mid) <= 8 and mid.isdigit():
        map_dir = acus / "map" / f"map{int(mid):08d}"
    else:
        map_dir = acus / "map" / (map_key if map_key.startswith("map") else f"map{map_key}")
    mp = map_dir / "Map.xml"
    if not mp.is_file():
        raise FileNotFoundError(mp)

    areas = _parse_areas_from_map(mp)
    p0 = sorted(
        ((a["slot"], aid, a["rid"], a["rstr"]) for aid, a in areas.items() if a["page"] == 0),
        key=lambda x: x[0],
    )
    p1 = sorted(
        ((a["slot"], aid, a["rid"], a["rstr"]) for aid, a in areas.items() if a["page"] == 1),
        key=lambda x: x[0],
    )
    if len(p0) != len(page0_steps):
        raise ValueError(f"page0 区域数 {len(p0)} 与 --page0 长度 {len(page0_steps)} 不一致")
    if len(p1) != len(page1_steps):
        raise ValueError(f"page1 区域数 {len(p1)} 与 --page1 长度 {len(page1_steps)} 不一致")

    aid_to_total: dict[int, int] = {}
    for i, (_, aid, _, _) in enumerate(p0):
        aid_to_total[aid] = page0_steps[i]
    for i, (_, aid, _, _) in enumerate(p1):
        aid_to_total[aid] = page1_steps[i]

    changed: list[Path] = []
    for aid, a in areas.items():
        total = aid_to_total.get(aid)
        if total is None:
            continue
        rid = int(a["rid"])
        rstr = str(a["rstr"])
        area_dir = acus / "mapArea" / f"mapArea{aid:08d}"
        xp = area_dir / "MapArea.xml"
        if not xp.is_file():
            continue
        raw = xp.read_text(encoding="utf-8")
        inner = _build_grids_inner(total, rid, rstr)
        new_raw = _replace_grids_section(raw, inner)
        if new_raw != raw:
            xp.write_text(new_raw, encoding="utf-8", newline="\n")
            changed.append(xp)
    return changed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("acus", type=Path, help="ACUS 根目录")
    ap.add_argument("map_id", help="例如 map70000000 或 70000000")
    ap.add_argument(
        "--page0",
        default="25,45,65,85,105",
        help="第一页各区域总步数（按 indexInPage 排序），逗号分隔",
    )
    ap.add_argument(
        "--page1",
        default="125,125",
        help="第二页各区域总步数，逗号分隔",
    )
    args = ap.parse_args()
    p0 = [int(x.strip()) for x in args.page0.split(",") if x.strip()]
    p1 = [int(x.strip()) for x in args.page1.split(",") if x.strip()]
    acus = args.acus.expanduser().resolve()
    try:
        out = repair_map(acus, args.map_id, p0, p1)
    except Exception as e:
        print(f"失败：{e}", file=sys.stderr)
        sys.exit(1)
    for p in out:
        print(f"已修复：{p}")
    print(f"共写入 {len(out)} 个 MapArea.xml")


if __name__ == "__main__":
    main()
