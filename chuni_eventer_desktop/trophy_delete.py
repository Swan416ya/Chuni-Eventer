from __future__ import annotations

import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .acus_scan import CharaItem, IdStr, TrophyItem
from .chara_delete import delete_chara_from_acus
from .chuni_formats import ChuniCharaId


def _chara_idstr_from_xml(xml_path: Path) -> IdStr | None:
    try:
        root = ET.parse(xml_path).getroot()
        id_el = root.find("name/id")
        str_el = root.find("name/str")
        if id_el is None or str_el is None:
            return None
        raw = (id_el.text or "").strip()
        if not raw.isdigit():
            return None
        return IdStr(int(raw), (str_el.text or "").strip())
    except Exception:
        return None


_TROPHY_DIR_NAME = re.compile(r"^trophy\d{6}$", re.IGNORECASE)


def linked_chara_ids_from_trophy_xml(xml_path: Path) -> list[int]:
    """
    从 Trophy.xml 中收集条件里出现的 charaName/id（>0）。
    用于「删除称号并删除关联角色」：与课题称号等模板中 charaData 字段一致。
    """
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return []
    seen: set[int] = set()
    for node in root.findall(".//charaName"):
        id_el = node.find("id")
        if id_el is None:
            continue
        raw = (id_el.text or "").strip()
        if not raw.isdigit():
            continue
        v = int(raw)
        if v > 0:
            seen.add(v)
    return sorted(seen)


@dataclass
class TrophyDeletionPlan:
    trophy_dir: Path
    trophy_id: int
    linked_chara_ids: list[int] = field(default_factory=list)
    chara_items_to_remove: list[CharaItem] = field(default_factory=list)

    def summary_lines(self, *, include_chara: bool) -> list[str]:
        lines = [f"称号目录：{self.trophy_dir.name}/"]
        if not include_chara:
            return lines
        if self.chara_items_to_remove:
            for c in self.chara_items_to_remove:
                nm = (c.name.str or "").strip() or "—"
                lines.append(f"角色：{c.name.id}（{nm}）→ chara/{c.xml_path.parent.name}/")
        elif self.linked_chara_ids:
            for cid in self.linked_chara_ids:
                lines.append(f"角色 ID {cid}（未在 ACUS 中找到对应 chara 目录，将跳过）")
        return lines


def plan_trophy_deletion(acus_root: Path, item: TrophyItem, chara_index: list[CharaItem]) -> TrophyDeletionPlan:
    acus_root = acus_root.resolve()
    tdir = item.xml_path.parent.resolve()
    try:
        tdir.relative_to(acus_root)
    except ValueError as e:
        raise ValueError(f"称号目录不在 ACUS 内：{tdir}") from e
    if tdir.parent.name.lower() != "trophy" or not _TROPHY_DIR_NAME.match(tdir.name):
        raise ValueError(f"非标准称号路径（拒绝删除）：{tdir}")

    linked = linked_chara_ids_from_trophy_xml(item.xml_path)
    by_id = {c.name.id: c for c in chara_index}
    chara_items: list[CharaItem] = []
    for cid in linked:
        ch = by_id.get(cid)
        if ch is not None:
            chara_items.append(ch)
            continue
        raw6 = ChuniCharaId(cid).raw6
        cand = acus_root / "chara" / f"chara{raw6}" / "Chara.xml"
        if not cand.is_file():
            continue
        nm = _chara_idstr_from_xml(cand)
        if nm is None:
            continue
        try:
            r = ET.parse(cand).getroot()
            default_key = (r.findtext("defaultImages/str") or "").strip()
        except Exception:
            default_key = ""
        chara_items.append(CharaItem(xml_path=cand, name=nm, default_image_key=default_key))

    return TrophyDeletionPlan(
        trophy_dir=tdir,
        trophy_id=item.name.id,
        linked_chara_ids=linked,
        chara_items_to_remove=chara_items,
    )


def execute_trophy_deletion(acus_root: Path, plan: TrophyDeletionPlan, *, delete_linked_charas: bool) -> None:
    ar = acus_root.resolve()
    if delete_linked_charas:
        for ch in plan.chara_items_to_remove:
            delete_chara_from_acus(ar, ch)
    if plan.trophy_dir.is_dir():
        shutil.rmtree(plan.trophy_dir)
