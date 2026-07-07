"""
资源压缩包快捷导入 — 编排器（Phase 2）。

整合 Phase 1 的 4 个模块，提供完整的"解压→扫描→冲突检测→重映射规划→写入→校验"流程。

核心入口
--------
    ``import_resource_pack(zip_path, acus_root)``
    ``plan_import(zip_path, acus_root)``
    ``apply_and_write(staging_root, plan, graph, acus_root)``
    ``cleanup_staging(staging_root)``
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import xml.etree.ElementTree as ET

from .acus_scan import (
    infer_system_voice_cue_numeric_id,
    scan_charas,
    scan_dds_images,
    scan_events,
    scan_maps,
    scan_map_bonuses,
    scan_map_icons,
    scan_music,
    scan_nameplates,
    scan_quests,
    scan_stages,
    scan_system_voices,
    scan_trophies,
)
from .chuni_formats import ChuniCharaId
from .map_export_bundle import _resource_dir_by_xml_glob, _safe_int
from .resource_id_allocator import ResourceIdAllocator, UnsupportedAllocationError
from .resource_reference_graph import (
    PackageResource,
    ReferenceGraph,
    RefEdge,
    build_reference_graph,
)
from .resource_xml_rewriter import (
    FieldEdit,
    NamingRule,
    RemapPlan,
    ApplyReport,
    NAMING_RULES,
    apply_field_edits,
    apply_remap_plan,
    compute_dir_renames,
    compute_file_renames,
    rewrite_own_name_id,
    _dir_for_id,
)
from .sheet_install import install_zip_to_acus_non_overwriting
from .system_voice_pack import cue_numeric_id_for_voice, cue_folder_name, system_voice_dir_name

# ---------------------------------------------------------------------------
# 本模块数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConflictEntry:
    kind: str
    old_id: int
    reason: str
    package_resource: PackageResource
    referencing_files: tuple[Path, ...]


@dataclass(frozen=True)
class ConflictReport:
    conflicts: tuple[ConflictEntry, ...]
    clean_resources: tuple[PackageResource, ...]
    package_warnings: tuple[str, ...]


@dataclass(frozen=True)
class ImportResult:
    success: bool
    written_count: int
    remaps: dict[tuple[str, int], int]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# 资源类型 → 扫描函数（用于 scan_package_resources）
# ---------------------------------------------------------------------------

# 常见 XML 文件名（一个目录内可能有的 XML）
_KNOWN_XML_NAMES = frozenset({
    "Music.xml", "Map.xml", "MapArea.xml", "MapBonus.xml", "Reward.xml",
    "Event.xml", "Chara.xml", "Stage.xml", "Course.xml", "Quest.xml",
    "NamePlate.xml", "Trophy.xml", "MapIcon.xml", "Mapicon.xml",
    "SystemVoice.xml", "CueFile.xml", "DDSMap.xml", "DDSImage.xml",
    "DDSBanner.xml", "CharaWorks.xml", "DDSGlobalImage.xml",
    "Gauge.xml", "NetOpen.xml", "ReleaseTag.xml", "TimeTable.xml",
    "NotesFieldLine.xml", "Skill.xml", "SkillCategory.xml",
    "MusicGenre.xml", "MusicLabel.xml", "Ticket.xml",
    "AvatarAccessory.xml",
})


def _is_known_xml(path: Path) -> bool:
    return path.name in _KNOWN_XML_NAMES or path.name.startswith("DDSGlobalImage")


# ---------------------------------------------------------------------------
# 1. scan_package_resources
# ---------------------------------------------------------------------------

def scan_package_resources(staging_root: Path) -> list[PackageResource]:
    """
    扫描 *staging_root* 下所有已知 XML 文件，收集包内资源清单。

    复用 ``acus_scan.scan_*`` 函数扫描 staging_root（结构与 ACUS 同构），
    把扫描结果统一映射为 ``PackageResource``。

    对 systemVoice 额外计算 ``cue_numeric_id``（存入 ``extra["cue_numeric_id"]``）。

    检测包内同 kind 重复 ID，发现重复则抛 ``ValueError``。
    """
    staging = staging_root.resolve()
    resources: list[PackageResource] = []

    # 对每个 ACUS 子目录，调用对应的 scan_* 函数
    scan_dispatch: list[tuple[str, Callable[[Path], list]]] = [
        ("music",      lambda r: scan_music(r)),
        ("trophy",     lambda r: scan_trophies(r)),
        ("chara",      lambda r: scan_charas(r)),
        ("namePlate",  lambda r: scan_nameplates(r)),
        ("stage",      lambda r: scan_stages(r)),
        ("event",      lambda r: scan_events(r)),
        ("map",        lambda r: scan_maps(r)),
        ("mapBonus",   lambda r: scan_map_bonuses(r)),
        ("mapIcon",    lambda r: scan_map_icons(r)),
        ("systemVoice", lambda r: scan_system_voices(r)),
        ("ddsImage",   lambda r: scan_dds_images(r)),
    ]

    for kind, scan_fn in scan_dispatch:
        kind_path = staging / kind
        if not kind_path.is_dir():
            continue
        try:
            items = scan_fn(staging)
        except Exception:
            continue
        for item in items:
            xml_rel = Path(item.xml_path).relative_to(staging)
            dir_rel = xml_rel.parent
            extra: dict = {}
            if kind == "systemVoice" and hasattr(item, "cue_numeric_id") and item.cue_numeric_id is not None:
                extra["cue_numeric_id"] = item.cue_numeric_id
            resources.append(PackageResource(
                kind=kind,
                resource_id=item.name.id,
                xml_path=xml_rel,
                dir_path=dir_rel,
                extra=extra,
            ))

    # 也扫描不在上述 dispatch 中的类型（ddsMap, charaWorks 等）
    # 通过递归扫描所有目录中的已知 XML 文件名
    for xml_path in staging.rglob("*.xml"):
        if not _is_known_xml(xml_path):
            continue
        # 跳过已经通过 scan_dispatch 处理过的 XML
        rel = xml_path.relative_to(staging)
        kind_guess = xml_path.name  # 从文件名推断
        # 检查是否已经被前面的扫描覆盖
        if any(
            r.xml_path == rel and r.kind in ("music", "trophy", "chara", "namePlate",
                                              "stage", "event", "map", "mapBonus",
                                              "mapIcon", "systemVoice", "ddsImage")
            for r in resources
        ):
            continue
        # 推断 kind
        kind = _infer_kind_from_xml_path(xml_path.name)
        if kind is None:
            continue
        dir_path = rel.parent
        try:
            root = ET.parse(str(xml_path)).getroot()
            name_el = root.find("name/id")
            if name_el is None:
                continue
            rid = _safe_int(name_el.text)
            if rid is None or rid < 0:
                continue
            # 去重检查已添加的同 kind+id
            if any(r.kind == kind and r.resource_id == rid for r in resources):
                continue
            resources.append(PackageResource(
                kind=kind,
                resource_id=rid,
                xml_path=rel,
                dir_path=dir_path,
                extra={},
            ))
        except Exception:
            continue

    # 包内重复 ID 检测
    seen: dict[tuple[str, int], Path] = {}
    for res in resources:
        key = (res.kind, res.resource_id)
        if key in seen:
            dup_xml = seen[key]
            raise ValueError(
                f"包内 {res.kind} ID {res.resource_id} 重复，请修复压缩包。"
                f"（存在于 {dup_xml} 和 {res.xml_path}）"
            )
        seen[key] = res.xml_path

    return resources


def _infer_kind_from_xml_path(xml_name: str) -> str | None:
    """从 XML 文件名推断资源 kind（非引用图场景）。"""
    _EXACT = {
        "Music.xml": "music",
        "Map.xml": "map",
        "MapArea.xml": "mapArea",
        "MapBonus.xml": "mapBonus",
        "Reward.xml": "reward",
        "Event.xml": "event",
        "Chara.xml": "chara",
        "Stage.xml": "stage",
        "Course.xml": "course",
        "Quest.xml": "quest",
        "NamePlate.xml": "namePlate",
        "Trophy.xml": "trophy",
        "MapIcon.xml": "mapIcon",
        "Mapicon.xml": "mapIcon",
        "SystemVoice.xml": "systemVoice",
        "CueFile.xml": "cueFile",
        "DDSMap.xml": "ddsMap",
        "DDSBanner.xml": "ddsBanner",
        "CharaWorks.xml": "charaWorks",
    }
    exact = _EXACT.get(xml_name)
    if exact is not None:
        return exact
    if xml_name.startswith("DDSGlobalImage"):
        return "ddsImage"
    return None


# ---------------------------------------------------------------------------
# 2. detect_conflicts
# ---------------------------------------------------------------------------

def detect_conflicts(
    resources: list[PackageResource],
    graph: ReferenceGraph,
    acus_root: Path,
) -> ConflictReport:
    """
    检测包内资源与 ACUS 已有资源的 ID 冲突。

    Parameters
        resources:  scan_package_resources 返回的包内资源列表
        graph:      包内引用图
        acus_root:  ACUS 根目录

    Returns
        ConflictReport（conflicts + clean_resources + package_warnings）。
    """
    allocator = ResourceIdAllocator(acus_root)
    # 构建 ACUS used_ids 缓存
    acus_used_ids: dict[str, set[int]] = {}
    # 只扫描可能出现在包内的类型
    kinds_needed = set(r.kind for r in resources)
    for kind in kinds_needed:
        acus_used_ids[kind] = allocator.used_ids(kind)

    conflicts: list[ConflictEntry] = []
    clean: list[PackageResource] = []
    warnings: list[str] = []

    for res in resources:
        is_conflict = False
        reason = ""

        if res.kind == "systemVoice":
            # systemVoice 特殊：检查 voice_id 和 cue_numeric_id 都不冲突
            cue_numeric_id = res.extra.get("cue_numeric_id")
            if cue_numeric_id is not None:
                cue_ids = acus_used_ids.get("cueFile", set())
                if res.resource_id in acus_used_ids.get(res.kind, set()) or cue_numeric_id in cue_ids:
                    is_conflict = True
                    if res.resource_id in acus_used_ids.get(res.kind, set()) and cue_numeric_id in cue_ids:
                        reason = "voice ID 和 cueFile ID 均在 ACUS 中已有"
                    elif res.resource_id in acus_used_ids.get(res.kind, set()):
                        reason = "voice ID 已在 ACUS 中已有"
                    else:
                        reason = "cueFile ID 已在 ACUS 中已有"
                else:
                    clean.append(res)
            else:
                if res.resource_id in acus_used_ids.get(res.kind, set()):
                    is_conflict = True
                    reason = "voice ID 已在 ACUS 中已有"
                else:
                    clean.append(res)
        else:
            used = acus_used_ids.get(res.kind, set())
            if res.resource_id in used:
                is_conflict = True
                reason = f"ACUS 已有同 {res.kind} ID {res.resource_id}"
            else:
                clean.append(res)

        if is_conflict:
            # 从引用图获取引用此资源的文件
            ref_edges = graph.referencers_of(res.kind, res.resource_id)
            referencing = tuple(sorted({e.source_file for e in ref_edges}))
            conflicts.append(ConflictEntry(
                kind=res.kind,
                old_id=res.resource_id,
                reason=reason,
                package_resource=res,
                referencing_files=referencing,
            ))
        else:
            # clean 已添加
            pass

    # 悬空引用检测
    dangling = graph.dangling_references(acus_used_ids)
    for edge in dangling:
        warnings.append(
            f"包内 {edge.source_kind} 引用 {edge.target_kind}#{edge.target_id}"
            f" 但包内/ACUS 均无此资源，引用保留原值"
        )

    return ConflictReport(
        conflicts=tuple(conflicts),
        clean_resources=tuple(clean),
        package_warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------
# 3. plan_remap
# ---------------------------------------------------------------------------

def _plan_remap(
    staging_root: Path,
    graph: ReferenceGraph,
    conflict_report: ConflictReport,
    allocator: ResourceIdAllocator,
    acus_root: Path,
) -> RemapPlan:
    """
    按架构文档 §4.3 实现重映射规划。

    步骤：
    1. 为每个冲突项分配新 ID
    2. 对每条引用边传播改写到 source_file
    3. 对被重映射资源的自身 XML 加 name/id 改写
    4. 计算目录/文件重命名
    5. chara ddsImage 联动
    6. cueFile 联动
    7. 校验
    """
    remaps: dict[tuple[str, int], int] = {}

    # Step 1: 为每个冲突项分配新 ID
    for entry in conflict_report.conflicts:
        old_key = (entry.kind, entry.old_id)
        try:
            new_id = allocator.allocate(entry.kind)
        except UnsupportedAllocationError as e:
            return RemapPlan(
                remaps={},
                file_edits={},
                dir_renames=[],
                file_renames=[],
                warnings=conflict_report.package_warnings,
                errors=(f"无法为 {entry.kind} 分配新 ID：{e}",),
            )
        remaps[old_key] = new_id

    # Step 2: 对每条引用边传播改写到 source_file
    file_edits: dict[Path, list[FieldEdit]] = {}
    acus_used_ids = {
        kind: allocator.used_ids(kind) for kind in set(e.target_kind for e in graph.edges) | set(e.source_kind for e in graph.edges)
    }

    for edge in graph.edges:
        target_key = (edge.target_kind, edge.target_id)
        if target_key not in remaps:
            # target 不在 remaps 中
            if not edge.in_package:
                # 检查是否是悬空引用（target 不在包内也不在 ACUS）
                acus_ids = acus_used_ids.get(edge.target_kind, set())
                if edge.target_id not in acus_ids:
                    # 悬空引用：warning，保留原值，不产生 edit
                    continue
                else:
                    # 外部引用（在 ACUS 中）：不产生 edit
                    continue
            # target 在包内且不冲突：不产生 edit
            continue

        # target 在 remaps 中 → 产生 FieldEdit
        new_id = remaps[target_key]
        file_edits.setdefault(edge.source_file, []).append(
            FieldEdit(xpath=edge.xpath, old_id=edge.target_id, new_id=new_id)
        )

    # Step 3: 对被重映射资源的自身 XML 加 name/id 改写
    # （apply_remap_plan 内部会自动处理，但我们需要确保 remaps 包含所有
    #  联动产生的 (kind, old) → new）

    # Step 4: 计算目录/文件重命名
    dir_renames = compute_dir_renames(staging_root, remaps)
    file_renames = compute_file_renames(staging_root, remaps)

    # Step 5: chara ddsImage 联动
    _dds_warnings: list[str] = []
    for (kind, old_id), new_id in list(remaps.items()):
        if kind != "chara":
            continue
        try:
            cid_old = ChuniCharaId(old_id)
            cid_new = ChuniCharaId(new_id)
            raw6_old = cid_old.raw6
            raw6_new = cid_new.raw6

            # 检查 ddsImage 是否已在这个 plan 中被其他 chara 使用
            dds_old_key = ("ddsImage", int(raw6_old))
            dds_new_key = ("ddsImage", int(raw6_new))

            if dds_old_key not in remaps:
                # 需要新增 ddsImage 重映射
                # 先检查 ddsImage 新 ID 是否冲突
                dds_used = allocator.used_ids("ddsImage")
                raw6_new_int = int(raw6_new)
                if raw6_new_int in dds_used:
                    # 需要为这个 ddsImage 分配新 ID
                    try:
                        new_raw6 = allocator.allocate("ddsImage")
                        remaps[dds_old_key] = new_raw6
                    except UnsupportedAllocationError:
                        # 分配失败，warning
                        pass
                    else:
                        remaps[dds_old_key] = new_raw6
                        new_dir = _dir_for_id("ddsImage", new_raw6, NAMING_RULES)
                        if new_dir:
                            dir_renames.append((
                                staging_root / "ddsImage" / f"ddsImage{raw6_old}",
                                staging_root / "ddsImage" / new_dir,
                            ))
                        else:
                            remaps.pop(dds_old_key, None)
                else:
                    remaps[dds_old_key] = raw6_new_int
                    # 加到 dir_renames
                    old_dds_dir = staging_root / "ddsImage" / f"ddsImage{raw6_old}"
                    new_dds_dir = staging_root / "ddsImage" / f"ddsImage{raw6_new}"
                    if old_dds_dir.is_dir():
                        dir_renames.append((old_dds_dir, new_dds_dir))

                    # 同步重写 DDSImage.xml 的 name/id
                    # （apply_remap_plan 内部会自动处理，但需要确保 remaps 有这项）
            else:
                # ddsImage 已被其他 chara 重映射
                existing_new = remaps[dds_old_key]
                if existing_new != int(raw6_new):
                    # 被多个 chara 共享，产生 warning
                    # 查找共享的 chara
                    sharing_charas = []
                    for (ck, cv), nv in remaps.items():
                        if ck == "chara" and cv != old_id:
                            try:
                                c = ChuniCharaId(cv)
                                if c.raw6 == raw6_old:
                                    sharing_charas.append(cv)
                            except Exception:
                                pass
                    warnings_msg = (
                        f"ddsImage{raw6_old} 被 chara {old_id}"
                        + (f" 和 chara {','.join(str(c) for c in sharing_charas)} 共享"
                           if sharing_charas else "")
                        + "，重映射后可能受影响"
                    )
                    _dds_warnings.append(warnings_msg)
        except Exception:
            pass

    # Step 6: cueFile 联动
    _cuefile_warnings: list[str] = []
    for (kind, old_id), new_id in list(remaps.items()):
        if kind != "systemVoice":
            continue
        # voice V → V'，cue_id 从 10000+V 改为 10000+V'
        cue_old = 10000 + old_id
        cue_new = 10000 + new_id
        cue_old_key = ("cueFile", cue_old)

        if cue_old_key not in remaps:
            # 检查 cueFile 新 ID 是否冲突
            cue_used = allocator.used_ids("cueFile")
            if cue_new in cue_used:
                # 需要分配新 cueFile ID
                try:
                    new_cue_id = allocator.allocate("cueFile")
                    remaps[cue_old_key] = new_cue_id
                except UnsupportedAllocationError:
                    _cuefile_warnings.append(
                        f"systemVoice {old_id}→{new_id} 的联动 cueFile "
                        f"(10000+{old_id}→10000+{new_id}) 分配失败"
                    )
                else:
                    remaps[cue_old_key] = new_cue_id
                    new_cue_dir = cue_folder_name(new_cue_id)
                    old_cue_dir = cue_folder_name(cue_old)
                    old_dir_path = staging_root / "cueFile" / old_cue_dir
                    new_dir_path = staging_root / "cueFile" / new_cue_dir
                    if old_dir_path.is_dir():
                        dir_renames.append((old_dir_path, new_dir_path))
                    # 查找包内所有引用此 cueFile 的 XML 并加 FieldEdit
                    # 注意：cueFile 的引用来自 Music.xml 的 cueFileName/id
                    _propagate_cuefile_edits(
                        staging_root, cue_old, new_cue_id, file_edits
                    )
            else:
                remaps[cue_old_key] = cue_new
                # 加到 dir_renames
                old_cue_dir = cue_folder_name(cue_old)
                new_cue_dir = cue_folder_name(cue_new)
                old_dir_path = staging_root / "cueFile" / old_cue_dir
                new_dir_path = staging_root / "cueFile" / new_cue_dir
                if old_dir_path.is_dir():
                    dir_renames.append((old_dir_path, new_dir_path))
                # 查找包内所有引用此 cueFile 的 XML 并加 FieldEdit
                _propagate_cuefile_edits(staging_root, cue_old, cue_new, file_edits)

    # Step 7: 校验
    errors: list[str] = []
    warnings_list: list[str] = list(conflict_report.package_warnings)

    # 7a. 所有 new_id 不与 ACUS 原有已有 ID 冲突
    # （allocator.allocate 已保证，但二次校验防御）
    # 注意：不能直接用 allocator.used_ids()，因为它包含本次分配的 ID
    # 需要重新扫描 ACUS 原始状态
    fresh_acus_ids: dict[str, set[int]] = {}
    for (k, _old), new in remaps.items():
        if k not in fresh_acus_ids:
            fresh_alloc = ResourceIdAllocator(acus_root)
            fresh_acus_ids[k] = fresh_alloc._scan_acus_ids(k)
    for (k, _old), new in remaps.items():
        if new in fresh_acus_ids.get(k, set()):
            errors.append(f"重映射新 ID 冲突：{k}#{new}（ACUS 已有）")

    # 7b. 所有 new_id 不与包内其他保留原 ID 的资源冲突
    clean_ids = {(r.kind, r.resource_id) for r in conflict_report.clean_resources}
    for (k, old), new in remaps.items():
        if (k, new) in clean_ids:
            errors.append(
                f"重映射新 ID {new} 与包内保留资源 {k}#{new} 冲突"
            )

    # 7c. 所有 new_id 在 plan 内同 kind 唯一
    new_ids_by_kind: dict[str, set[int]] = {}
    for (k, old), new in remaps.items():
        new_ids_by_kind.setdefault(k, set()).add(new)
    for k, ids in new_ids_by_kind.items():
        if len(ids) != len([r for r in remaps if r[0] == k]):
            errors.append(f"重映射 plan 内 {k} 的新 ID 不唯一")

    if _cuefile_warnings:
        warnings_list.extend(_cuefile_warnings)
    if _dds_warnings:
        warnings_list.extend(_dds_warnings)

    return RemapPlan(
        remaps=remaps,
        file_edits=file_edits,
        dir_renames=dir_renames,
        file_renames=file_renames,
        warnings=tuple(warnings_list),
        errors=tuple(errors),
    )


def _propagate_cuefile_edits(
    staging_root: Path,
    cue_old: int,
    cue_new: int,
    file_edits: dict[Path, list[FieldEdit]],
) -> None:
    """
    对包内所有引用 cueFile{cue_old} 的 XML（主要是 Music.xml），
    产生 FieldEdit(cueFileName/id, cue_old, cue_new)。
    """
    # 查找包内所有 Music.xml
    music_dir = staging_root / "music"
    if not music_dir.is_dir():
        return
    for music_xml in music_dir.rglob("Music.xml"):
        try:
            root = ET.parse(str(music_xml)).getroot()
            cue_el = root.find("cueFileName/id")
            if cue_el is not None:
                val = (cue_el.text or "").strip()
                if val.isdigit() and int(val) == cue_old:
                    file_edits.setdefault(music_xml, []).append(
                        FieldEdit(xpath="cueFileName/id", old_id=cue_old, new_id=cue_new)
                    )
        except Exception:
            continue


# ---------------------------------------------------------------------------
# 4. apply_and_write
# ---------------------------------------------------------------------------

def apply_and_write(
    *,
    staging_root: Path,
    plan: RemapPlan,
    graph: ReferenceGraph,
    acus_root: Path,
) -> ImportResult:
    """
    应用 plan 并写入 ACUS。供 UI 确认后调用。

    流程（架构文档 §8）：
    1. 调 apply_remap_plan(staging_root, plan) 应用 XML 重写 + 重命名
    2. 写入前校验
    3. 打包暂存区为临时 zip，调 install_zip_to_acus_non_overwriting 写入 ACUS
    4. 写入后校验
    5. 失败回滚
    """
    staging = staging_root.resolve()
    acus = acus_root.resolve()

    # Step 1: 应用 RemapPlan
    try:
        report = apply_remap_plan(staging, plan)
    except Exception as e:
        return ImportResult(
            success=False,
            written_count=0,
            remaps=dict(plan.remaps),
            errors=(f"应用重映射计划失败：{e}",),
        )

    if not report.success:
        return ImportResult(
            success=False,
            written_count=0,
            remaps=dict(plan.remaps),
            warnings=plan.warnings,
            errors=plan.errors,
        )

    # Step 2: 写入前校验
    pre_errors: list[str] = []

    # 2a. 暂存区内所有 XML 可被 ET.parse 正常解析
    for xml_path in staging.rglob("*.xml"):
        try:
            ET.parse(str(xml_path))
        except ET.ParseError as e:
            pre_errors.append(f"XML 解析失败：{xml_path.relative_to(staging)} — {e}")

    # 2b. 目录名与 name/id 一致
    for (kind, old_id), new_id in plan.remaps.items():
        dir_name = _dir_for_id(kind, new_id, NAMING_RULES)
        if dir_name is None:
            continue
        resource_dir = staging / kind / dir_name
        if not resource_dir.is_dir():
            continue
        # 查找该目录下的主 XML，验证 name/id 匹配
        found_xml = False
        for xml_name in ("Music.xml", "Chara.xml", "Map.xml", "Event.xml",
                         "Trophy.xml", "NamePlate.xml", "SystemVoice.xml",
                         "CueFile.xml", "DDSMap.xml", "DDSImage.xml",
                         "MapArea.xml", "MapBonus.xml", "Reward.xml",
                         "Stage.xml", "CharaWorks.xml"):
            xp = resource_dir / xml_name
            if xp.is_file():
                try:
                    root = ET.parse(str(xp)).getroot()
                    name_id_el = root.find("name/id")
                    if name_id_el is not None:
                        parsed_id = _safe_int(name_id_el.text)
                        if parsed_id is not None and parsed_id != new_id:
                            pre_errors.append(
                                f"目录名与 name/id 不一致："
                                f"{kind}/{dir_name} name/id={parsed_id} 预期 {new_id}"
                            )
                except ET.ParseError:
                    pre_errors.append(f"校验 XML 解析失败：{xp.relative_to(staging)}")
                found_xml = True
                break

    # 2c. 重新扫 ACUS 确认 new_id 仍不冲突
    try:
        check_allocator = ResourceIdAllocator(acus)
        for (kind, _old), new_id in plan.remaps.items():
            used = check_allocator.used_ids(kind)
            if new_id in used:
                pre_errors.append(
                    f"ACUS 在导入期间被改动，{kind}#{new_id} 已被占用，请重试"
                )
    except Exception as e:
        pre_errors.append(f"二次冲突校验失败：{e}")

    if pre_errors:
        return ImportResult(
            success=False,
            written_count=0,
            remaps=dict(plan.remaps),
            warnings=plan.warnings,
            errors=tuple(pre_errors),
        )

    # Step 3: 打包暂存区为临时 zip，写入 ACUS
    written_files: list[str] = []
    zip_path: Path | None = None
    try:
        zip_path = Path(tempfile.mkdtemp(prefix="chuni_pack_")) / "import.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root_dir, dirs, files in os.walk(str(staging)):
                root_dir_p = Path(root_dir)
                for fname in files:
                    fpath = root_dir_p / fname
                    arcname = fpath.relative_to(staging).as_posix()
                    zf.write(fpath, arcname)

        # 调 install_zip_to_acus_non_overwriting
        written, skipped = install_zip_to_acus_non_overwriting(zip_path, acus)

        if skipped:
            # 任何 skipped 都应视为异常
            return ImportResult(
                success=False,
                written_count=len(written),
                remaps=dict(plan.remaps),
                warnings=plan.warnings,
                errors=(
                    f"写入时检测到 {len(skipped)} 个文件已存在（ACUS 在 plan 后被改动），请重试。"
                    f" 已写入 {len(written)} 个文件。"
                ),
            )

        written_files = written

    except Exception as e:
        return ImportResult(
            success=False,
            written_count=0,
            remaps=dict(plan.remaps),
            errors=(f"打包或写入失败：{e}",),
        )

    # Step 4: 写入后校验
    post_errors: list[str] = []

    # 4a. 统计写入文件数，与暂存区文件数比对
    staging_file_count = sum(
        1 for _ in staging.rglob("*") if _.is_file()
    )
    # 实际写入数应该 ≥ 暂存区文件数（可能有些文件未被映射）
    if len(written_files) < staging_file_count * 0.5:
        post_errors.append(
            f"写入文件数 ({len(written_files)}) 远少于暂存区文件数 ({staging_file_count})"
        )

    # 4b. 对写入的 XML 做 ET.parse 抽查
    for rel in written_files[:50]:  # 抽查前 50
        xp = acus / rel
        if xp.suffix.lower() == ".xml":
            try:
                ET.parse(str(xp))
            except ET.ParseError as e:
                post_errors.append(f"写入后 XML 解析失败：{rel} — {e}")

    # 4c. 对每个被重映射的资源，确认新 ID 资源存在
    for (kind, _old), new_id in plan.remaps.items():
        dir_name = _dir_for_id(kind, new_id, NAMING_RULES)
        if dir_name is None:
            continue
        # 用 _resource_dir_by_xml_glob 确认
        found_dir = _resource_dir_by_xml_glob(acus, f"{kind}/**/*.{kind[0].upper()}{kind[1:]}.xml", new_id)
        if found_dir is None:
            # 尝试更宽泛的 glob
            found_dir = _resource_dir_by_xml_glob(acus, f"{kind}/**/Music.xml", new_id)
            if found_dir is None:
                found_dir = _resource_dir_by_xml_glob(acus, f"{kind}/**/Chara.xml", new_id)
            if found_dir is None:
                found_dir = _resource_dir_by_xml_glob(acus, f"{kind}/**/Map.xml", new_id)
        # 如果仍然未找到，跳过（可能是其他类型的 XML）
        # 检查目录是否存在
        expected_dir = acus / kind / dir_name
        if not expected_dir.is_dir():
            post_errors.append(
                f"写入后校验：预期目录 {kind}/{dir_name} 不存在"
            )

    if post_errors:
        # Step 5: 失败回滚
        _rollback(acus, written_files)
        return ImportResult(
            success=False,
            written_count=len(written_files),
            remaps=dict(plan.remaps),
            warnings=plan.warnings,
            errors=tuple(post_errors),
        )

    return ImportResult(
        success=True,
        written_count=len(written_files),
        remaps=dict(plan.remaps),
        warnings=plan.warnings,
        errors=(),
    )


# ---------------------------------------------------------------------------
# 5. import_resource_pack（完整流程）
# ---------------------------------------------------------------------------

def import_resource_pack(
    *,
    zip_path: Path,
    acus_root: Path,
    on_progress: Callable[[str], None] | None = None,
) -> ImportResult:
    """
    完整导入流程（plan + apply + write）。

    参数
        zip_path:     资源压缩包路径
        acus_root:    ACUS 根目录
        on_progress:  可选进度回调

    返回
        ImportResult(success, written_count, remaps, warnings, errors)
    """
    zip_path = Path(zip_path).resolve()
    acus_root = Path(acus_root).resolve()
    staging_root: Path | None = None

    try:
        # 0. 格式校验
        if not zipfile.is_zipfile(zip_path):
            return ImportResult(
                success=False,
                written_count=0,
                remaps={},
                errors=("无法识别的压缩包格式",),
            )

        # 1. 解压
        if on_progress:
            on_progress("解压中...")
        staging_root = Path(tempfile.mkdtemp(prefix="chuni_pack_import_"))

        with zipfile.ZipFile(zip_path, "r") as zf:
            # 安全校验：防止路径穿越
            for member in zf.namelist():
                if member.endswith("/"):
                    continue
                parts = Path(member).resolve().parts
                # 检查解压后的路径是否在 staging_root 下
                candidate = staging_root / member
                try:
                    candidate.resolve().relative_to(staging_root.resolve())
                except ValueError:
                    shutil.rmtree(staging_root, ignore_errors=True)
                    staging_root = None
                    return ImportResult(
                        success=False,
                        written_count=0,
                        remaps={},
                        errors=(f"压缩包包含路径穿越文件：{member}",),
                    )
            zf.extractall(staging_root)

        # 2. 扫描
        if on_progress:
            on_progress("扫描包内资源...")
        resources = scan_package_resources(staging_root)
        if not resources:
            return ImportResult(
                success=False,
                written_count=0,
                remaps={},
                errors=("包内未发现任何可识别资源 XML",),
            )

        # 2b. 检查 XML 可解析
        parse_errors: list[str] = []
        for xml_path in staging_root.rglob("*.xml"):
            try:
                ET.parse(str(xml_path))
            except ET.ParseError as e:
                parse_errors.append(f"{xml_path.relative_to(staging_root)}: {e}")
        if parse_errors:
            return ImportResult(
                success=False,
                written_count=0,
                remaps={},
                errors=tuple(f"XML 解析失败：{e}" for e in parse_errors),
            )

        # 3. 构建引用图
        if on_progress:
            on_progress("构建引用图...")
        graph = build_reference_graph(staging_root, resources)

        # 4. 检测冲突
        if on_progress:
            on_progress("检测冲突...")
        conflict_report = detect_conflicts(resources, graph, acus_root)

        # 5. 规划重映射
        if on_progress:
            on_progress("规划重映射...")
        allocator = ResourceIdAllocator(acus_root)
        plan = _plan_remap(staging_root, graph, conflict_report, allocator, acus_root)

        if plan.errors:
            return ImportResult(
                success=False,
                written_count=0,
                remaps={},
                warnings=plan.warnings,
                errors=plan.errors,
            )

        # 6. 应用并重写 + 写入
        if on_progress:
            on_progress("写入ACUS...")
        result = apply_and_write(
            staging_root=staging_root,
            plan=plan,
            graph=graph,
            acus_root=acus_root,
        )

        return result

    except ValueError as e:
        return ImportResult(
            success=False,
            written_count=0,
            remaps={},
            errors=(str(e),),
        )
    except Exception as e:
        return ImportResult(
            success=False,
            written_count=0,
            remaps={},
            errors=(f"导入过程异常：{e}",),
        )
    finally:
        # 7. 清理暂存区
        if staging_root is not None:
            try:
                shutil.rmtree(staging_root, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 6. plan_import（仅规划，不写入）
# ---------------------------------------------------------------------------

def plan_import(
    *,
    zip_path: Path,
    acus_root: Path,
) -> tuple[ConflictReport, RemapPlan, ReferenceGraph, Path]:
    """
    仅规划，不写入。返回 ``(conflicts, plan, graph, staging_root)`` 供 UI 预览。

    staging_root 是解压后的暂存区（用 tempfile.mkdtemp 创建，不自动清理）。
    调用方用完后需调 ``cleanup_staging(staging_root)`` 清理。
    """
    zip_path = Path(zip_path).resolve()
    acus_root = Path(acus_root).resolve()

    if not zipfile.is_zipfile(zip_path):
        raise ValueError("无法识别的压缩包格式")

    staging_root = Path(tempfile.mkdtemp(prefix="chuni_pack_import_"))

    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            candidate = staging_root / member
            try:
                candidate.resolve().relative_to(staging_root.resolve())
            except ValueError:
                shutil.rmtree(staging_root, ignore_errors=True)
                raise ValueError(f"压缩包包含路径穿越文件：{member}")
        zf.extractall(staging_root)

    resources = scan_package_resources(staging_root)
    if not resources:
        shutil.rmtree(staging_root, ignore_errors=True)
        raise ValueError("包内未发现任何可识别资源 XML")

    graph = build_reference_graph(staging_root, resources)
    conflict_report = detect_conflicts(resources, graph, acus_root)
    allocator = ResourceIdAllocator(acus_root)
    plan = _plan_remap(staging_root, graph, conflict_report, allocator, acus_root)

    return (conflict_report, plan, graph, staging_root)


# ---------------------------------------------------------------------------
# 7. cleanup_staging
# ---------------------------------------------------------------------------

def cleanup_staging(staging_root: Path) -> None:
    """清理暂存区目录。"""
    try:
        shutil.rmtree(staging_root, ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 8. 回滚
# ---------------------------------------------------------------------------

def _rollback(acus_root: Path, written_files: list[str]) -> None:
    """
    按 written 清单反向删除已写入文件，删除空目录。
    """
    acus = acus_root.resolve()
    errors: list[str] = []

    for rel in reversed(written_files):
        dest = (acus / rel).resolve()
        try:
            if dest.exists():
                dest.unlink()
        except OSError as e:
            errors.append(f"回滚删除失败：{rel} — {e}")

    # 清理空目录（从最深往最浅）
    deleted_dirs: set[Path] = set()
    for rel in reversed(written_files):
        dest = (acus / rel).resolve()
        parent = dest.parent
        while parent != acus:
            try:
                if parent in deleted_dirs:
                    break
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    deleted_dirs.add(parent)
                    parent = parent.parent
                else:
                    break
            except OSError:
                break

    if errors:
        # 回滚失败，报告残留
        import sys
        print(f"[WARN] 回滚部分失败：{errors}", file=sys.stderr)