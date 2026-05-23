"""
ACUS ``courseRule/courseRuleXXXX/CourseRule.xml`` 的读取、explain 生成与写入。

自定义规则 ID 从 7001 起分配（7000 之后第一个可用号）。
"""
from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET
from pathlib import Path

CUSTOM_COURSE_RULE_ID_MIN = 7001
CUSTOM_COURSE_RULE_ID_MAX = 7999

DEFAULT_COURSE_LIFE = 50
DEFAULT_COURSE_CLEAR_LIFE = 1


@dataclass
class CourseRuleParams:
    recovery_life: int = 10
    damage_miss: int = 1
    damage_attack: int = 1
    damage_justice: int = 0
    damage_justice_c: int = 0
    life: int = DEFAULT_COURSE_LIFE


def _safe_int(text: str | None, default: int = 0) -> int:
    try:
        return int((text or "").strip())
    except Exception:
        return default


def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def course_rule_dir_name(rule_id: int) -> str:
    return f"courseRule{int(rule_id):04d}"


def course_rule_xml_path(acus_root: Path, rule_id: int) -> Path:
    return acus_root / "courseRule" / course_rule_dir_name(rule_id) / "CourseRule.xml"


def _used_course_rule_ids(acus_root: Path) -> set[int]:
    used: set[int] = set()
    root = acus_root / "courseRule"
    if not root.is_dir():
        return used
    for p in root.glob("courseRule*/CourseRule.xml"):
        try:
            rid = _safe_int(ET.parse(p).getroot().findtext("name/id"), -1)
            if rid >= 0:
                used.add(rid)
        except Exception:
            continue
    return used


def next_custom_course_rule_id(acus_root: Path) -> int:
    used = _used_course_rule_ids(acus_root)
    for rid in range(CUSTOM_COURSE_RULE_ID_MIN, CUSTOM_COURSE_RULE_ID_MAX + 1):
        if rid not in used:
            return rid
    raise ValueError(
        f"{CUSTOM_COURSE_RULE_ID_MIN}～{CUSTOM_COURSE_RULE_ID_MAX} 内已无空闲 CourseRule ID。"
    )


def load_course_rule_params(acus_root: Path, rule_id: int) -> CourseRuleParams | None:
    path = course_rule_xml_path(acus_root, rule_id)
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except Exception:
        return None
    return CourseRuleParams(
        recovery_life=_safe_int(root.findtext("recovery_life"), 0),
        damage_miss=_safe_int(root.findtext("damage_miss"), 0),
        damage_attack=_safe_int(root.findtext("damage_attack"), 0),
        damage_justice=_safe_int(root.findtext("damage_justice"), 0),
        damage_justice_c=_safe_int(root.findtext("damage_justice_c"), 0),
        life=_safe_int(root.findtext("life"), DEFAULT_COURSE_LIFE),
    )


def _judgment_damage_line(color: str, label: str, suffix: str, amount: int) -> str:
    if amount > 0:
        return f"$c[{color}]{label}$c{suffix}でLIFEが$c[FF0000FF]-{amount}$c"
    if amount < 0:
        return f"$c[{color}]{label}$c判定でLIFEが$c[00FFFFFF]+{-amount}$c"
    return ""


def build_course_rule_explain(params: CourseRuleParams) -> str:
    """
    根据 damage / recovery 字段生成游戏内显示的 ``explain`` 文案。
    对齐 A001 段位组曲常用写法（如 courseRule0024/0025/0034）。
    """
    lines: list[str] = []
    jc = int(params.damage_justice_c)
    j = int(params.damage_justice)
    atk = int(params.damage_attack)
    miss = int(params.damage_miss)
    rec = int(params.recovery_life)

    rank_collapsed = jc == 0 and j == 0 and atk > 0 and miss > 0

    if jc != 0:
        lines.append(_judgment_damage_line("FFDE00FF", "J-CRITICAL", "判定", jc))
    if j != 0:
        lines.append(_judgment_damage_line("FF6A00FF", "JUSTICE", "判定", j))

    if rank_collapsed:
        lines.append(_judgment_damage_line("00FF00FF", "ATTACK", "以下", atk))
    else:
        if atk != 0:
            lines.append(_judgment_damage_line("00FF00FF", "ATTACK", "判定", atk))
        if miss != 0:
            lines.append(_judgment_damage_line("FFFFFFFF", "MISS", "判定", miss))

    if rec > 0:
        lines.append(f"楽曲終了時にLIFEが$c[00FFFFFF]+{rec}$c")
    elif rec < 0:
        lines.append(f"楽曲終了時にLIFEが$c[FF0000FF]-{-rec}$c")

    return "$n".join(lines)


def write_course_rule_xml(*, acus_root: Path, rule_id: int, params: CourseRuleParams) -> Path:
    rid = int(rule_id)
    explain = build_course_rule_explain(params)
    esc_explain = _xml_esc(explain)
    life = int(params.life) if params.life > 0 else DEFAULT_COURSE_LIFE
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<CourseRuleData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>{course_rule_dir_name(rid)}</dataName>
  <name>
    <id>{rid}</id>
    <str>{rid:04d}</str>
    <data />
  </name>
  <explain>{esc_explain}</explain>
  <life>{life}</life>
  <recovery_life>{int(params.recovery_life)}</recovery_life>
  <clear_life>{DEFAULT_COURSE_CLEAR_LIFE}</clear_life>
  <damage_miss>{int(params.damage_miss)}</damage_miss>
  <damage_attack>{int(params.damage_attack)}</damage_attack>
  <damage_justice>{int(params.damage_justice)}</damage_justice>
  <damage_justice_c>{int(params.damage_justice_c)}</damage_justice_c>
  <skillName>
    <id>0</id>
    <str>スキルなし</str>
    <data />
  </skillName>
  <startFieldWallPos>0</startFieldWallPos>
  <farMaxFieldWallPos>0</farMaxFieldWallPos>
  <nearMaxFieldWallPos>0</nearMaxFieldWallPos>
  <recoveryFieldWallMove>0</recoveryFieldWallMove>
  <damageFieldWallMove>0</damageFieldWallMove>
  <targetDifBasic>0</targetDifBasic>
  <targetDifAdvanced>0</targetDifAdvanced>
  <targetDifExpert>0</targetDifExpert>
  <targetDifMaster>0</targetDifMaster>
  <targetDifUltima>0</targetDifUltima>
</CourseRuleData>
"""
    out = course_rule_xml_path(acus_root, rid)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8", newline="\n")
    return out


def resolve_course_rule_id_for_save(
    acus_root: Path,
    *,
    existing_rule_id: int,
    is_edit: bool,
) -> int:
    """
    编辑时：若 ACUS 已有对应 CourseRule 或 ID≥7001，则复用并覆盖；
    否则（引用官包 rule）分配新的 ≥7001 ID。
    """
    rid = int(existing_rule_id)
    if is_edit and rid >= CUSTOM_COURSE_RULE_ID_MIN:
        return rid
    if is_edit and course_rule_xml_path(acus_root, rid).is_file():
        return rid
    return next_custom_course_rule_id(acus_root)
