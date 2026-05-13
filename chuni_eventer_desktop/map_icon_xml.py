"""
MapIcon.xml 读写（结构对齐 ``A001/mapIcon/mapIcon1001/MapIcon.xml``：字段齐全、顺序一致）。
若样本使用 ``ddsFile/path``，读取侧会容错。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .acus_scan import scan_map_icons
from .game_data_index import GameDataIndex


MAP_ICON_ID_START = 7000

# 与 A001 mapIcon1001 一致（自定义条目除 name / image / dataName 外默认沿用）
_DEFAULT_NET_OPEN_ID = 2701
_DEFAULT_NET_OPEN_STR = "v2_40 00_1"
_DEFAULT_DISABLE_FLAG = "false"
_DEFAULT_DEFAULT_HAVE = "false"
_DEFAULT_EXPLAIN_TEXT = "-"
_DEFAULT_PRIORITY = "0"


def _safe_int(text: str | None) -> int | None:
    try:
        t = (text or "").strip()
        if not t:
            return None
        return int(t)
    except ValueError:
        return None


def map_icon_dir_name(map_icon_id: int) -> str:
    return f"mapIcon{int(map_icon_id):08d}"


def map_icon_dds_basename(map_icon_id: int) -> str:
    return f"CHU_UI_MapIcon_{int(map_icon_id):08d}.dds"


def read_map_icon_image_relpath(xml_path: Path) -> str:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return ""
    img = (root.findtext("image/path") or "").strip()
    if img:
        return img
    return (root.findtext("ddsFile/path") or "").strip()


def _sort_name_default(display_name: str) -> str:
    """有显示名则用首字符（与官方按名称排序的习惯一致），否则 ``-``。"""
    s = (display_name or "").strip()
    if s:
        return s[:1]
    return "-"


def _merge_extra_from_existing(existing: Path) -> dict[str, object] | None:
    """
    编辑时保留原 XML 中除 dataName/name/image 外的字段；缺失键不返回，由写入端用 A001 默认补齐。
    """
    if not existing.is_file():
        return None
    try:
        root = ET.parse(existing).getroot()
    except Exception:
        return None
    out: dict[str, object] = {}
    no = root.find("netOpenName")
    if no is not None:
        data_el = no.find("data")
        if data_el is not None:
            out["net_open_data"] = data_el.text if data_el.text is not None else ""
        nid = _safe_int(no.findtext("id"))
        ns = (no.findtext("str") or "").strip()
        if nid is not None and ns:
            out["net_open_id"] = nid
            out["net_open_str"] = ns
    df = root.findtext("disableFlag")
    if df is not None and str(df).strip() != "":
        out["disable_flag"] = str(df).strip()
    sn = root.findtext("sortName")
    if sn is not None:
        out["sort_name"] = sn
    dh = root.findtext("defaultHave")
    if dh is not None and str(dh).strip() != "":
        out["default_have"] = str(dh).strip()
    et = root.findtext("explainText")
    if et is not None:
        out["explain_text"] = et
    pr = root.findtext("priority")
    if pr is not None and str(pr).strip() != "":
        try:
            out["priority"] = int(str(pr).strip())
        except ValueError:
            out["priority"] = str(pr).strip()
    return out or None


def write_map_icon_xml(
    *,
    out_dir: Path,
    map_icon_id: int,
    name_str: str,
    dds_basename: str,
    preserve_fields_from: Path | None = None,
) -> Path:
    """
    写入 ``out_dir/mapIcon/mapIconXXXXXXXX/MapIcon.xml``。
    节点与顺序对齐 A001 ``mapIcon1001``；``preserve_fields_from`` 为已有文件时合并 netOpen/disable/sort 等字段。
    """
    folder = out_dir / "mapIcon" / map_icon_dir_name(map_icon_id)
    folder.mkdir(parents=True, exist_ok=True)
    xml_path = folder / "MapIcon.xml"
    base = map_icon_dir_name(map_icon_id)
    display = (name_str or "").strip() or f"MapIcon{map_icon_id}"

    merged = _merge_extra_from_existing(preserve_fields_from) if preserve_fields_from else None
    net_id = int(merged["net_open_id"]) if merged and "net_open_id" in merged else _DEFAULT_NET_OPEN_ID
    net_str = str(merged["net_open_str"]) if merged and "net_open_str" in merged else _DEFAULT_NET_OPEN_STR
    net_data = merged.get("net_open_data", "") if merged else ""
    disable_flag = str(merged["disable_flag"]) if merged and "disable_flag" in merged else _DEFAULT_DISABLE_FLAG
    sort_name = (
        str(merged["sort_name"])
        if merged and "sort_name" in merged
        else _sort_name_default(display)
    )
    default_have = str(merged["default_have"]) if merged and "default_have" in merged else _DEFAULT_DEFAULT_HAVE
    explain_text = str(merged["explain_text"]) if merged and "explain_text" in merged else _DEFAULT_EXPLAIN_TEXT
    priority_val = merged.get("priority", _DEFAULT_PRIORITY) if merged else _DEFAULT_PRIORITY
    priority_text = str(int(priority_val)) if isinstance(priority_val, int) else str(priority_val)

    root = ET.Element("MapIconData")
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")

    dn = ET.SubElement(root, "dataName")
    dn.text = base

    net = ET.SubElement(root, "netOpenName")
    ET.SubElement(net, "id").text = str(net_id)
    ET.SubElement(net, "str").text = net_str
    nod = ET.SubElement(net, "data")
    nod.text = net_data if net_data is not None else ""

    df_el = ET.SubElement(root, "disableFlag")
    df_el.text = disable_flag

    nm = ET.SubElement(root, "name")
    ET.SubElement(nm, "id").text = str(int(map_icon_id))
    ET.SubElement(nm, "str").text = display
    ndata = ET.SubElement(nm, "data")
    ndata.text = ""

    sn_el = ET.SubElement(root, "sortName")
    sn_el.text = sort_name

    img = ET.SubElement(root, "image")
    ET.SubElement(img, "path").text = dds_basename.strip()

    dh_el = ET.SubElement(root, "defaultHave")
    dh_el.text = default_have

    ex_el = ET.SubElement(root, "explainText")
    ex_el.text = explain_text

    pr_el = ET.SubElement(root, "priority")
    pr_el.text = priority_text

    try:
        ET.indent(root, space="  ")  # type: ignore[attr-defined]
    except Exception:
        pass
    tree = ET.ElementTree(root)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return xml_path


def collect_used_map_icon_ids(acus_root: Path, game_index: GameDataIndex | None) -> set[int]:
    used: set[int] = set()
    for it in scan_map_icons(acus_root):
        used.add(it.name.id)
    if game_index is None:
        return used
    try:
        gr = Path(game_index.game_root).expanduser().resolve(strict=False)
    except OSError:
        return used
    if not gr.is_dir():
        return used
    for rel in game_index.roots_scanned:
        try:
            pack = (gr / rel).resolve(strict=False)
        except OSError:
            continue
        if not pack.is_dir():
            continue
        for pat in ("mapIcon/**/MapIcon.xml", "mapIcon/**/Mapicon.xml"):
            for xp in pack.glob(pat):
                if not xp.is_file():
                    continue
                try:
                    root = ET.parse(xp).getroot()
                    mid = _safe_int(root.findtext("name/id") or "")
                    if mid is not None and mid >= 0:
                        used.add(mid)
                except Exception:
                    continue
    # 仓库旁 A001（与 map_add_dialog._reward_source_roots 一致）
    a001 = acus_root.parent / "A001"
    if a001.is_dir():
        try:
            if a001.resolve() not in {acus_root.resolve()}:
                for pat in ("mapIcon/**/MapIcon.xml", "mapIcon/**/Mapicon.xml"):
                    for xp in a001.glob(pat):
                        if not xp.is_file():
                            continue
                        try:
                            root = ET.parse(xp).getroot()
                            mid = _safe_int(root.findtext("name/id") or "")
                            if mid is not None and mid >= 0:
                                used.add(mid)
                        except Exception:
                            continue
        except OSError:
            pass
    return used


def suggest_next_map_icon_id(acus_root: Path, game_index: GameDataIndex | None = None) -> int:
    used = collect_used_map_icon_ids(acus_root, game_index)
    n = MAP_ICON_ID_START
    while n in used:
        n += 1
    return n
