from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

from .acus_scan import MusicItem


@dataclass
class MusicDeletionPlan:
    music_id: int
    music_dir: Path | None = None
    cue_dir: Path | None = None
    stage_dir: Path | None = None
    event_dirs_to_remove: list[Path] = field(default_factory=list)
    event_xmls_to_rewrite: list[Path] = field(default_factory=list)

    def summary_lines(self) -> list[str]:
        lines: list[str] = []
        if self.music_dir:
            lines.append(f"乐曲目录：{self.music_dir.name}/")
        if self.cue_dir:
            lines.append(f"CueFile：{self.cue_dir.name}/")
        if self.stage_dir:
            lines.append(f"舞台：{self.stage_dir.name}/")
        for p in self.event_dirs_to_remove:
            lines.append(f"事件（整夹删除）：{p.name}/")
        for p in self.event_xmls_to_rewrite:
            lines.append(f"事件（仅从列表移除本曲）：{p.parent.name}/")
        if not lines:
            lines.append("（无待删项）")
        return lines


def _safe_resolved_dir(path: Path, acus_root: Path) -> Path | None:
    try:
        p = path.resolve()
        ar = acus_root.resolve()
        if not str(p).startswith(str(ar)):
            return None
        return p
    except OSError:
        return None


def _resolve_music_dir(item: MusicItem, acus_root: Path) -> Path | None:
    d = _safe_resolved_dir(item.xml_path.parent, acus_root)
    if d is None:
        return None
    try:
        rel = d.relative_to(acus_root.resolve())
    except ValueError:
        return None
    if len(rel.parts) < 2 or rel.parts[0] != "music":
        return None
    return d


def _resolve_cue_dir(acus_root: Path, cue_id: int) -> Path | None:
    if cue_id <= 0:
        return None
    root = acus_root / "cueFile"
    if not root.is_dir():
        return None
    cand = root / f"cueFile{cue_id:06d}"
    if cand.is_dir() and (cand / "CueFile.xml").is_file():
        return cand
    for p in root.iterdir():
        if not p.is_dir():
            continue
        xf = p / "CueFile.xml"
        if not xf.is_file():
            continue
        try:
            r = ET.parse(xf).getroot()
            raw = (r.findtext("name/id") or "").strip()
            if raw.isdigit() and int(raw) == cue_id:
                return p
        except Exception:
            continue
    return None


def _resolve_stage_dir(acus_root: Path, stage_name_id: int) -> Path | None:
    if stage_name_id <= 0:
        return None
    root = acus_root / "stage"
    if not root.is_dir():
        return None
    for p in root.iterdir():
        if not p.is_dir():
            continue
        xf = p / "Stage.xml"
        if not xf.is_file():
            continue
        try:
            r = ET.parse(xf).getroot()
            raw = (r.findtext("name/id") or "").strip()
            if raw.isdigit() and int(raw) == stage_name_id:
                return p
        except Exception:
            continue
    return None


def _count_music_string_ids(substances: ET.Element) -> int:
    n = 0
    for list_el in substances.findall(".//musicNames/list"):
        n += len(list_el.findall("StringID"))
    return n


def _classify_event_change(path: Path, music_id: int) -> tuple[bool, bool]:
    """
    若移除 music_id 后 substances 内所有 musicNames/list 均无 StringID，则整夹删除事件。
    """
    tree = ET.parse(path)
    root = tree.getroot()
    subs = root.find("substances")
    if subs is None:
        return False, False

    before = _count_music_string_ids(subs)
    changed = False
    for list_el in subs.findall(".//musicNames/list"):
        for sid in list(list_el.findall("StringID")):
            id_el = sid.find("id")
            if id_el is None or not (id_el.text or "").strip().isdigit():
                continue
            if int(id_el.text.strip()) != music_id:
                continue
            list_el.remove(sid)
            changed = True

    after = _count_music_string_ids(subs)
    remove_whole = before > 0 and after == 0
    return changed, remove_whole


def plan_music_deletion(acus_root: Path, item: MusicItem) -> MusicDeletionPlan:
    music_id = item.name.id
    plan = MusicDeletionPlan(music_id=music_id)
    acus_root = acus_root.resolve()

    plan.music_dir = _resolve_music_dir(item, acus_root)
    if item.cue_file and item.cue_file.id > 0:
        plan.cue_dir = _resolve_cue_dir(acus_root, item.cue_file.id)
    if item.stage and item.stage.id > 0:
        plan.stage_dir = _resolve_stage_dir(acus_root, item.stage.id)

    for ev_xml in sorted(acus_root.glob("event/event*/Event.xml")):
        try:
            changed, remove_whole = _classify_event_change(ev_xml, music_id)
        except Exception:
            continue
        if not changed:
            continue
        ev_dir = ev_xml.parent.resolve()
        if remove_whole:
            plan.event_dirs_to_remove.append(ev_dir)
        else:
            plan.event_xmls_to_rewrite.append(ev_xml)

    rm_set = {p.resolve() for p in plan.event_dirs_to_remove}
    plan.event_xmls_to_rewrite = [
        p for p in plan.event_xmls_to_rewrite if p.parent.resolve() not in rm_set
    ]
    plan.event_dirs_to_remove = list(dict.fromkeys(plan.event_dirs_to_remove))
    plan.event_xmls_to_rewrite = list(dict.fromkeys(plan.event_xmls_to_rewrite))
    return plan


def _apply_event_prune_to_tree(tree: ET.ElementTree, music_id: int) -> None:
    root = tree.getroot()
    subs = root.find("substances")
    if subs is None:
        return
    for list_el in subs.findall(".//musicNames/list"):
        for sid in list(list_el.findall("StringID")):
            id_el = sid.find("id")
            if id_el is None or not (id_el.text or "").strip().isdigit():
                continue
            if int(id_el.text.strip()) != music_id:
                continue
            list_el.remove(sid)


def execute_music_deletion(plan: MusicDeletionPlan) -> None:
    removed_dirs: set[Path] = set()

    for p in plan.event_dirs_to_remove:
        rp = p.resolve()
        if rp in removed_dirs or not rp.is_dir():
            continue
        shutil.rmtree(rp)
        removed_dirs.add(rp)

    for xml_path in plan.event_xmls_to_rewrite:
        if not xml_path.is_file():
            continue
        parent = xml_path.parent.resolve()
        if parent in removed_dirs:
            continue
        tree = ET.parse(xml_path)
        _apply_event_prune_to_tree(tree, plan.music_id)
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    for p in (plan.music_dir, plan.cue_dir, plan.stage_dir):
        if p is None:
            continue
        rp = p.resolve()
        if rp in removed_dirs or not rp.is_dir():
            continue
        shutil.rmtree(rp)
        removed_dirs.add(rp)
