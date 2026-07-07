"""
资源 XML 重写器 — 资源压缩包快捷导入 Phase 1。

提供字段感知的 XML 改写、目录/文件重命名计算与 ``RemapPlan`` 的批量应用。

关键：修复现有 ``github_sheet_dialog._rewrite_all_id_fields_in_xml`` 的 bug ——
    旧实现把 ``<id>`` 文本等于某值的所有节点全改，会误伤无关资源。
    新实现按 ``(xpath, old_id, new_id)`` 精确改写。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .chuni_formats import ChuniCharaId


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FieldEdit:
    """一个字段的改写：xpath 下的 old_id 改为 new_id。"""
    xpath: str        # 相对 XML root
    old_id: int
    new_id: int


@dataclass(frozen=True)
class NamingRule:
    """资源目录和文件命名规则。"""
    kind: str
    dir_template: str           # 如 "music{ID:04d}"
    file_token_templates: tuple[str, ...] = ()  # 如 ("CHU_UI_Jacket_{ID:04d}", "{ID:04d}_")


@dataclass(frozen=True)
class RemapPlan:
    """完整的重映射计划。"""
    remaps: dict[tuple[str, int], int]          # (kind, old_id) -> new_id
    file_edits: dict[Path, list[FieldEdit]]     # 每个文件要改的字段（绝对路径）
    dir_renames: list[tuple[Path, Path]]        # 目录重命名 (old, new) 绝对路径
    file_renames: list[tuple[Path, Path]]       # 文件重命名 (old, new) 绝对路径
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplyReport:
    """应用重映射计划后的报告。"""
    success: bool
    modified_files: tuple[Path, ...]
    renamed_dirs: tuple[tuple[Path, Path], ...]
    renamed_files: tuple[tuple[Path, Path], ...]
    warnings: tuple[str, ...]


# ---------------------------------------------------------------------------
# NAMING_RULES — 来自架构文档 §6.3，以实际 ACUS 代码为准
# ---------------------------------------------------------------------------
# 核查差异（2026-07-07）：
#   - event 目录名实际使用 :08d（8 位零填充），文档写 :06d → 已修正
#   - mapBonus 使用 :08d（8 位零填充），与文档一致
#   - mapIcon 使用 :08d（8 位零填充），与文档一致
#   - charaWorks 实际存在 :06d 和裸整数两种风格，取 :06d 为主
# ---------------------------------------------------------------------------

NAMING_RULES: dict[str, NamingRule] = {
    "music":       NamingRule("music",       "music{ID:04d}",      ("CHU_UI_Jacket_{ID:04d}", "{ID:04d}_")),
    "cueFile":     NamingRule("cueFile",     "cueFile{ID:06d}",    ()),
    "event":       NamingRule("event",       "event{ID:08d}",      ()),
    "chara":       NamingRule("chara",       "chara{ID:06d}",      ()),
    "namePlate":   NamingRule("namePlate",   "namePlate{ID:08d}",  ()),
    "trophy":      NamingRule("trophy",      "trophy{ID:06d}",     ()),
    "map":         NamingRule("map",         "map{ID:08d}",        ()),
    "mapArea":     NamingRule("mapArea",     "mapArea{ID:08d}",    ()),
    "mapBonus":    NamingRule("mapBonus",    "mapBonus{ID:08d}",   ()),
    "mapIcon":     NamingRule("mapIcon",     "mapIcon{ID:08d}",    ()),
    "systemVoice": NamingRule("systemVoice", "systemVoice{ID:04d}", ()),
    "stage":       NamingRule("stage",       "stage{ID}",          ()),
    "reward":      NamingRule("reward",      "reward{ID:09d}",     ()),
    "ddsImage":    NamingRule("ddsImage",    "ddsImage{ID}",       ()),
    "ddsMap":      NamingRule("ddsMap",      "ddsMap{ID}",         ()),
    "ddsBanner":   NamingRule("ddsBanner",   "ddsBanner{ID}",      ()),
    "charaWorks":  NamingRule("charaWorks",  "charaWorks{ID:06d}", ()),
    "quest":       NamingRule("quest",       "quest{ID}",          ()),
    "ticket":      NamingRule("ticket",      "ticket{ID}",         ()),
    "avatarAccessory": NamingRule("avatarAccessory", "avatarAccessory{ID}", ()),
    "course":      NamingRule("course",      "course{ID:08d}",     ()),
    "courseRule":  NamingRule("courseRule",  "courseRule{ID}",     ()),
    "releaseTag":  NamingRule("releaseTag",  "releaseTag{ID}",     ()),
    "netOpen":     NamingRule("netOpen",     "netOpen{ID}",        ()),
    "gauge":       NamingRule("gauge",       "gauge{ID}",          ()),
    "timeTable":   NamingRule("timeTable",   "timeTable{ID}",      ()),
    "notesFieldLine": NamingRule("notesFieldLine", "notesFieldLine{ID}", ()),
    "skill":       NamingRule("skill",       "skill{ID}",          ()),
    "skillCategory": NamingRule("skillCategory", "skillCategory{ID}", ()),
    "musicGenre":  NamingRule("musicGenre",  "musicGenre{ID}",     ()),
    "musicLabel":  NamingRule("musicLabel",  "musicLabel{ID}",     ()),
}


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _format_template(template: str, id_value: int) -> str:
    """
    把 ``template`` 中的 ``{ID:Wd}`` 占位符替换为格式化后的 id 字符串。
    示例：``"music{ID:04d}"`` + 7001 -> ``"music7001"``
         ``"music{ID:04d}"`` + 7    -> ``"music0007"``
    """
    # 匹配 {ID:0Nd} 模式
    m = re.search(r"\{ID:(\d+)d\}", template)
    if not m:
        # 无零填充占位符，直接拼接
        return template.replace("{ID}", str(id_value))
    width = int(m.group(1))
    fmt = f"{{ID:0{width}d}}"
    return template.replace(fmt, f"{id_value:0{width}d}")


def _dir_for_id(kind: str, rid: int, rules: dict[str, NamingRule] = NAMING_RULES) -> str | None:
    """根据 kind 和 id 生成目录名。"""
    rule = rules.get(kind)
    if rule is None:
        return None
    return _format_template(rule.dir_template, rid)


# ---------------------------------------------------------------------------
# apply_field_edits
# ---------------------------------------------------------------------------

def apply_field_edits(xml_path: Path, edits: list[FieldEdit]) -> int:
    """
    按 xpath 分组，每个 xpath 一次 ``findall``，只改文本匹配 ``old_id`` 的节点。

    返回修改节点数。写回时统一用 ``utf-8`` + ``xml_declaration``。

    关键：不误改无关的 ``<id>`` 节点。
    """
    if not edits:
        return 0

    # 按 xpath 分组
    by_xpath: dict[str, list[FieldEdit]] = {}
    for edit in edits:
        by_xpath.setdefault(edit.xpath, []).append(edit)

    tree = ET.parse(xml_path)
    root = tree.getroot()
    changed = 0

    for xpath, xpath_edits in by_xpath.items():
        try:
            nodes = root.findall(xpath)
        except Exception:
            # xpath 可能不合法（特殊字符等），跳过
            continue

        for node in nodes:
            for edit in xpath_edits:
                if node.text is not None and node.text.strip() == str(edit.old_id):
                    node.text = str(edit.new_id)
                    changed += 1

    if changed > 0:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    return changed


# ---------------------------------------------------------------------------
# rewrite_own_name_id
# ---------------------------------------------------------------------------

def rewrite_own_name_id(xml_path: Path, new_id: int) -> None:
    """
    改资源自身 XML 的 ``name/id`` 为 ``new_id``。
    若 ``name/id`` 文本等于 ``new_id``（已改好或无需改），也正常通过。
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    name_id = root.find("name/id")
    if name_id is None:
        return
    old = (name_id.text or "").strip()
    if old.isdigit() and int(old) == new_id:
        return
    name_id.text = str(new_id)
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# path 元素 token 替换
# ---------------------------------------------------------------------------

def _rewrite_path_texts(
    xml_path: Path,
    kind: str,
    old_id: int,
    new_id: int,
    rules: dict[str, NamingRule] = NAMING_RULES,
) -> int:
    """
    在 ``<path>`` 元素的文本内，用 ``file_token_templates`` 做旧 ID token -> 新 ID token 的替换。

    **只对 ``<path>`` 元素做，不对其他元素做**。

    返回替换次数。
    """
    rule = rules.get(kind)
    if rule is None or not rule.file_token_templates:
        return 0

    tree = ET.parse(xml_path)
    root = tree.getroot()
    changed = 0

    for token_tmpl in rule.file_token_templates:
        old_token = _format_template(token_tmpl, old_id)
        new_token = _format_template(token_tmpl, new_id)
        if not old_token or not new_token:
            continue

        for el in root.iter("path"):
            if (el.text or "").find(old_token) == -1:
                continue
            el.text = (el.text or "").replace(old_token, new_token)
            changed += 1

    if changed > 0:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)

    return changed


# ---------------------------------------------------------------------------
# compute_dir_renames
# ---------------------------------------------------------------------------

def compute_dir_renames(
    staging_root: Path,
    remaps: dict[tuple[str, int], int],
    rules: dict[str, NamingRule] = NAMING_RULES,
) -> list[tuple[Path, Path]]:
    """
    根据 ``remaps`` 和 ``NAMING_RULES`` 计算需要重命名的目录。

    返回 ``(old_path, new_path)`` 列表，均为绝对路径。
    """
    result: list[tuple[Path, Path]] = []
    for (kind, old_id), new_id in remaps.items():
        dir_name_old = _dir_for_id(kind, old_id, rules)
        dir_name_new = _dir_for_id(kind, new_id, rules)
        if dir_name_old is None or dir_name_new is None:
            continue
        old_dir = staging_root / kind / dir_name_old
        if old_dir.is_dir():
            new_dir = staging_root / kind / dir_name_new
            result.append((old_dir.resolve(), new_dir.resolve()))
    return result


# ---------------------------------------------------------------------------
# compute_file_renames
# ---------------------------------------------------------------------------

def compute_file_renames(
    staging_root: Path,
    remaps: dict[tuple[str, int], int],
    rules: dict[str, NamingRule] = NAMING_RULES,
) -> list[tuple[Path, Path]]:
    """
    根据 ``remaps`` 和 ``NAMING_RULES.file_token_templates`` 计算需要重命名的文件。

    扫描被重映射资源目录内的文件，匹配 ``file_token_templates`` 生成的旧 token，
    替换为新 token 得到文件名。

    返回 ``(old_path, new_path)`` 列表，均为绝对路径。
    """
    result: list[tuple[Path, Path]] = []
    for (kind, old_id), new_id in remaps.items():
        rule = rules.get(kind)
        if rule is None or not rule.file_token_templates:
            continue

        dir_name = _dir_for_id(kind, old_id, rules)
        if dir_name is None:
            continue

        resource_dir = staging_root / kind / dir_name
        if not resource_dir.is_dir():
            continue

        for token_tmpl in rule.file_token_templates:
            old_token = _format_template(token_tmpl, old_id)
            new_token = _format_template(token_tmpl, new_id)
            if not old_token or not new_token:
                continue

            for f in resource_dir.rglob("*"):
                if not f.is_file():
                    continue
                if old_token not in f.name:
                    continue
                new_name = f.name.replace(old_token, new_token)
                new_path = f.with_name(new_name)
                result.append((f.resolve(), new_path.resolve()))

    return result


# ---------------------------------------------------------------------------
# apply_remap_plan — 核心编排函数
# ---------------------------------------------------------------------------

def apply_remap_plan(staging_root: Path, plan: RemapPlan) -> ApplyReport:
    """
    在 ``staging_root`` 应用 ``RemapPlan``。

    步骤：
    1. 对每个 ``file_edits`` 项调 ``apply_field_edits``
    2. 对每个被重映射资源的 XML 调 ``rewrite_own_name_id``
    3. 处理 ``path`` 元素文本内的 ID token 替换（限定在 ``<path>`` 元素内）
    4. 执行目录重命名（深度优先，先子后父）
    5. 执行文件重命名（按 ``file_token_templates`` 匹配文件名子串）
    6. 处理 chara 变体目录（chara ``{C*10}`` -> chara ``{C'*10}``）
    7. 处理 chara ddsImage 联动（强制重命名 ``ddsImage{raw6(C)}`` -> ``ddsImage{raw6(C')}``）

    返回 ``ApplyReport(success, modified_files, renamed_dirs, renamed_files, warnings)``。

    注意：若 ``plan.errors`` 非空，不执行任何写入，直接返回 ``success=False``。
    """
    # 零写入阶段校验
    if plan.errors:
        return ApplyReport(
            success=False,
            modified_files=(),
            renamed_dirs=(),
            renamed_files=(),
            warnings=plan.warnings,
        )

    warnings: list[str] = list(plan.warnings)
    modified_files: list[Path] = []
    renamed_dirs: list[tuple[Path, Path]] = []
    renamed_files: list[tuple[Path, Path]] = []

    # ---------- 1. XML 字段改写 ----------
    for xml_path, edits in plan.file_edits.items():
        if not edits:
            continue
        if not xml_path.is_file():
            warnings.append(f"file_edits 指向的 XML 不存在：{xml_path}")
            continue
        count = apply_field_edits(xml_path, edits)
        if count > 0:
            modified_files.append(xml_path)

    # ---------- 2. 重写资源自身 name/id ----------
    for (kind, old_id), new_id in plan.remaps.items():
        dir_name = _dir_for_id(kind, old_id)
        if dir_name is None:
            continue
        xml_path = staging_root / kind / dir_name
        # 尝试常见 XML 文件名
        for xml_name in ("Music.xml", "Chara.xml", "Map.xml", "Event.xml",
                         "Trophy.xml", "NamePlate.xml", "SystemVoice.xml",
                         "CueFile.xml", "DDSMap.xml", "DDSImage.xml",
                         "MapArea.xml", "MapBonus.xml", "Reward.xml",
                         "Stage.xml", "CharaWorks.xml"):
            xp = xml_path / xml_name
            if xp.is_file():
                rewrite_own_name_id(xp, new_id)
                if xp not in modified_files:
                    modified_files.append(xp)
                break  # 每个资源只改一个主 XML

    # ---------- 3. path 元素文本 token 替换 ----------
    for (kind, old_id), new_id in plan.remaps.items():
        dir_name = _dir_for_id(kind, old_id)
        if dir_name is None:
            continue
        resource_dir = staging_root / kind / dir_name
        if not resource_dir.is_dir():
            continue
        for xml_file in resource_dir.rglob("*.xml"):
            count = _rewrite_path_texts(xml_file, kind, old_id, new_id)
            if count > 0 and xml_file not in modified_files:
                modified_files.append(xml_file)

    # ---------- 4. 目录重命名（深度优先，先子后父） ----------
    # 按路径深度降序排序：最深的目录先重命名
    sorted_renames = sorted(plan.dir_renames, key=lambda x: len(x[0].parts), reverse=True)
    for old_dir, new_dir in sorted_renames:
        if old_dir.is_dir():
            if not new_dir.exists():
                old_dir.rename(new_dir)
            else:
                warnings.append(f"目录重命名跳过（目标已存在）：{old_dir} -> {new_dir}")
            renamed_dirs.append((old_dir, new_dir))
        else:
            warnings.append(f"目录重命名跳过（目录不存在）：{old_dir}")

    # ---------- 5. 文件重命名 ----------
    # 按文件路径深度降序排序，避免父目录先动导致路径失效
    sorted_file_renames = sorted(
        plan.file_renames, key=lambda x: len(x[0].parts), reverse=True
    )
    for old_file, new_file in sorted_file_renames:
        if old_file.is_file():
            # 注意：new_file 可能与 old_file 同名不同目录
            new_file.parent.mkdir(parents=True, exist_ok=True)
            if not new_file.exists():
                old_file.rename(new_file)
            renamed_files.append((old_file, new_file))
        else:
            warnings.append(f"文件重命名跳过（文件不存在）：{old_file}")

    # ---------- 6. chara 变体目录联动 ----------
    for (kind, old_id), new_id in plan.remaps.items():
        if kind != "chara":
            continue
        try:
            base_old = old_id // 10
            base_new = new_id // 10
            var_dir_old = staging_root / "chara" / f"chara{base_old:06d}0"
            var_dir_new = staging_root / "chara" / f"chara{base_new:06d}0"
            if var_dir_old.is_dir():
                if not var_dir_new.exists():
                    var_dir_old.rename(var_dir_new)
                renamed_dirs.append((var_dir_old, var_dir_new))
        except Exception:
            warnings.append(f"chara 变体目录重命名失败：{old_id} -> {new_id}")

    # ---------- 7. chara ddsImage 联动（强制） ----------
    for (kind, old_id), new_id in plan.remaps.items():
        if kind != "chara":
            continue
        try:
            cid_old = ChuniCharaId(old_id)
            cid_new = ChuniCharaId(new_id)
            raw6_old = cid_old.raw6
            raw6_new = cid_new.raw6
            dds_dir_old = staging_root / "ddsImage" / f"ddsImage{raw6_old}"
            dds_dir_new = staging_root / "ddsImage" / f"ddsImage{raw6_new}"
            if dds_dir_old.is_dir():
                if not dds_dir_new.exists():
                    dds_dir_old.rename(dds_dir_new)
                    renamed_dirs.append((dds_dir_old, dds_dir_new))

                    # 同步重写 DDSImage.xml 的 name/id
                    dds_xml = dds_dir_new / "DDSImage.xml"
                    if dds_xml.is_file():
                        rewrite_own_name_id(dds_xml, int(raw6_new))
                        modified_files.append(dds_xml)
                else:
                    warnings.append(
                        f"ddsImage 联动重命名跳过（目标已存在）：{dds_dir_old} -> {dds_dir_new}。"
                        f"ddsImage{raw6_old} 可能被其他 chara 共享。"
                    )
        except Exception:
            warnings.append(f"chara ddsImage 联动失败：{old_id} -> {new_id}")

    # ---------- 排序输出，保证确定性 ----------
    modified_files.sort(key=lambda p: str(p))
    renamed_dirs.sort(key=lambda p: (str(p[0]), str(p[1])))
    renamed_files.sort(key=lambda p: (str(p[0]), str(p[1])))
    warnings.sort()

    return ApplyReport(
        success=True,
        modified_files=tuple(modified_files),
        renamed_dirs=tuple(renamed_dirs),
        renamed_files=tuple(renamed_files),
        warnings=tuple(warnings),
    )