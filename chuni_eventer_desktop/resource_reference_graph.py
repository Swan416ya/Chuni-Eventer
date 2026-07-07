"""
声明式引用规则表 + 资源引用图构建与查询。

供 ``resource_pack_import.py`` 编排器导入，是"资源压缩包快捷导入"功能的 Phase 1 组件。

引用规则来源于 ``map_export_bundle._expand_*_xml_closure`` 的"反向声明式镜像"。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Iterable

from .map_export_bundle import _safe_int


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

_RESOURCE_KINDS = (
    "map", "mapArea", "mapBonus", "event", "reward",
    "music", "cueFile", "stage", "chara", "ddsImage", "ddsMap",
    "namePlate", "trophy", "mapIcon", "systemVoice",
    "avatarAccessory", "ticket", "quest", "course",
    "charaWorks", "skill", "skillCategory", "musicGenre", "musicLabel",
    "releaseTag", "netOpen", "gauge", "timeTable", "notesFieldLine",
    "ddsBanner",
)


class PackageResource:
    """包内一个资源的描述。"""

    __slots__ = ("kind", "resource_id", "xml_path", "dir_path", "extra")

    kind: str
    resource_id: int
    xml_path: Path
    dir_path: Path
    extra: dict

    def __init__(
        self,
        kind: str,
        resource_id: int,
        xml_path: Path,
        dir_path: Path,
        extra: dict | None = None,
    ) -> None:
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "resource_id", resource_id)
        object.__setattr__(self, "xml_path", xml_path)
        object.__setattr__(self, "dir_path", dir_path)
        object.__setattr__(self, "extra", extra or {})

    def __repr__(self) -> str:
        return f"PackageResource({self.kind!r}, {self.resource_id!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PackageResource):
            return NotImplemented
        return (
            self.kind == other.kind
            and self.resource_id == other.resource_id
            and self.xml_path == other.xml_path
            and self.dir_path == other.dir_path
        )

    def __hash__(self) -> int:
        return hash((self.kind, self.resource_id))


class RefRule:
    """一条引用规则：某类 XML 的某 xpath 指向某类资源。"""

    __slots__ = ("source_kind", "xpath", "target_kind", "condition")

    source_kind: str
    xpath: str
    target_kind: str
    condition: str | None

    def __init__(
        self,
        source_kind: str,
        xpath: str,
        target_kind: str,
        condition: str | None = None,
    ) -> None:
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "xpath", xpath)
        object.__setattr__(self, "target_kind", target_kind)
        object.__setattr__(self, "condition", condition)

    def __repr__(self) -> str:
        return f"RefRule({self.source_kind!r} -> {self.target_kind!r}, xpath={self.xpath!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RefRule):
            return NotImplemented
        return (
            self.source_kind == other.source_kind
            and self.xpath == other.xpath
            and self.target_kind == other.target_kind
            and self.condition == other.condition
        )

    def __hash__(self) -> int:
        return hash((self.source_kind, self.xpath, self.target_kind, self.condition))


class RefEdge:
    """一条引用边。"""

    __slots__ = (
        "source_file", "source_kind", "xpath",
        "target_kind", "target_id", "in_package",
    )

    source_file: Path
    source_kind: str
    xpath: str
    target_kind: str
    target_id: int
    in_package: bool

    def __init__(
        self,
        source_file: Path,
        source_kind: str,
        xpath: str,
        target_kind: str,
        target_id: int,
        in_package: bool,
    ) -> None:
        object.__setattr__(self, "source_file", source_file)
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "xpath", xpath)
        object.__setattr__(self, "target_kind", target_kind)
        object.__setattr__(self, "target_id", target_id)
        object.__setattr__(self, "in_package", in_package)

    def __repr__(self) -> str:
        return (
            f"RefEdge({self.source_file.name!r}, {self.source_kind!r} -> "
            f"{self.target_kind!r}:{self.target_id!r}, pkg={self.in_package})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RefEdge):
            return NotImplemented
        return (
            self.source_file == other.source_file
            and self.source_kind == other.source_kind
            and self.xpath == other.xpath
            and self.target_kind == other.target_kind
            and self.target_id == other.target_id
            and self.in_package == other.in_package
        )

    def __hash__(self) -> int:
        return hash((
            self.source_file, self.source_kind, self.xpath,
            self.target_kind, self.target_id, self.in_package,
        ))


class ReferenceGraph:
    """资源引用有向图。

    Attributes
        nodes:  ``(kind, id) -> PackageResource``
        edges:  所有引用边
        _by_source:    按引用方文件索引
        _by_target:    按被引用方索引
    """

    __slots__ = ("nodes", "edges", "_by_source", "_by_target")

    def __init__(
        self,
        nodes: dict[tuple[str, int], PackageResource],
        edges: list[RefEdge],
    ) -> None:
        self.nodes: dict[tuple[str, int], PackageResource] = nodes
        self.edges = edges
        self._by_source: dict[Path, list[RefEdge]] = {}
        self._by_target: dict[tuple[str, int], list[RefEdge]] = {}
        # Build indexes
        for edge in self.edges:
            self._by_source.setdefault(edge.source_file, []).append(edge)
            self._by_target.setdefault(
                (edge.target_kind, edge.target_id), []
            ).append(edge)

    def referencers_of(self, kind: str, resource_id: int) -> list[RefEdge]:
        """查询：谁引用了 ``(kind, id)``？用于重映射传播。"""
        return list(self._by_target.get((kind, resource_id), []))

    def references_of(self, file_path: Path) -> list[RefEdge]:
        """单个文件引用了哪些资源。"""
        return list(self._by_source.get(file_path, []))

    def dangling_references(
        self, acus_used_ids: dict[str, set[int]] | None = None
    ) -> list[RefEdge]:
        """悬空引用：``in_package`` 为 ``False`` 且 target 不在 ACUS。"""
        result: list[RefEdge] = []
        for edge in self.edges:
            if not edge.in_package:
                if acus_used_ids is not None:
                    used = acus_used_ids.get(edge.target_kind)
                    if used is not None and edge.target_id in used:
                        continue
                result.append(edge)
        return result


# ---------------------------------------------------------------------------
# 声明式引用规则表（单一真相源）
# ---------------------------------------------------------------------------

REF_RULES: tuple[RefRule, ...] = (
    # --- Music.xml ---
    RefRule("music", "releaseTagName/id", "releaseTag", None),
    RefRule("music", "netOpenName/id", "netOpen", None),
    RefRule("music", "stageName/id", "stage", None),
    RefRule("music", "cueFileName/id", "cueFile", None),
    # --- Map.xml ---
    RefRule(
        "map",
        "infos/MapDataAreaInfo/mapAreaName/id",
        "mapArea",
        None,
    ),
    RefRule(
        "map",
        "infos/MapDataAreaInfo/rewardName/id",
        "reward",
        None,
    ),
    RefRule(
        "map",
        "infos/MapDataAreaInfo/musicName/id",
        "music",
        None,
    ),
    RefRule(
        "map",
        "infos/MapDataAreaInfo/ddsMapName/id",
        "ddsMap",
        None,
    ),
    RefRule("map", "timeTableName/id", "timeTable", None),
    RefRule("map", "stopReleaseEventName/id", "event", None),
    RefRule(
        "map",
        "infos/MapDataAreaInfo/gaugeName/id",
        "gauge",
        None,
    ),
    # --- MapArea.xml ---
    RefRule("mapArea", "mapBonusName/id", "mapBonus", None),
    RefRule(
        "mapArea",
        "grids/MapAreaGridData/reward/rewardName/id",
        "reward",
        None,
    ),
    # --- MapBonus.xml ---
    RefRule(
        "mapBonus",
        "substances/list/MapBonusSubstanceData/chara/charaName/id",
        "chara",
        None,
    ),
    RefRule(
        "mapBonus",
        "substances/list/MapBonusSubstanceData/music/musicName/id",
        "music",
        None,
    ),
    RefRule(
        "mapBonus",
        "substances/list/MapBonusSubstanceData/charaWorks/charaWorksName/id",
        "charaWorks",
        None,
    ),
    RefRule(
        "mapBonus",
        "substances/list/MapBonusSubstanceData/skill/skillName/id",
        "skill",
        None,
    ),
    RefRule(
        "mapBonus",
        "substances/list/MapBonusSubstanceData/musicGenre/musicGenreName/id",
        "musicGenre",
        None,
    ),
    # --- Reward.xml (按 substance type 分发) ---
    RefRule(
        "reward",
        ".//RewardSubstanceData/ticket/ticketName/id",
        "ticket",
        "type=1",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/trophy/trophyName/id",
        "trophy",
        "type=2",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/chara/charaName/id",
        "chara",
        "type=3",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/namePlate/namePlateName/id",
        "namePlate",
        "type=5",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/music/musicName/id",
        "music",
        "type=6",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/mapIcon/mapIconName/id",
        "mapIcon",
        "type=7",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/systemVoice/systemVoiceName/id",
        "systemVoice",
        "type=8",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/avatarAccessory/avatarAccessoryName/id",
        "avatarAccessory",
        "type=9",
    ),
    RefRule(
        "reward",
        ".//RewardSubstanceData/stage/stageName/id",
        "stage",
        "type=13",
    ),
    # --- Event.xml ---
    RefRule("event", "netOpenName/id", "netOpen", None),
    RefRule("event", "ddsBannerName/id", "ddsBanner", None),
    RefRule("event", "substances/map/mapName/id", "map", None),
    RefRule("event", ".//musicNames/list/StringID/id", "music", None),
    # --- Chara.xml ---
    RefRule("chara", "addImages1/charaName/id", "chara", None),
    RefRule("chara", "addImages2/charaName/id", "chara", None),
    RefRule("chara", "addImages3/charaName/id", "chara", None),
    RefRule("chara", "addImages4/charaName/id", "chara", None),
    RefRule("chara", "addImages5/charaName/id", "chara", None),
    RefRule("chara", "addImages6/charaName/id", "chara", None),
    RefRule("chara", "addImages7/charaName/id", "chara", None),
    RefRule("chara", "addImages8/charaName/id", "chara", None),
    RefRule("chara", "addImages9/charaName/id", "chara", None),
    # addImages{n}/image/id → ddsImage (chara variant image → ddsImage)
    RefRule("chara", "addImages1/image/id", "ddsImage", None),
    RefRule("chara", "addImages2/image/id", "ddsImage", None),
    RefRule("chara", "addImages3/image/id", "ddsImage", None),
    RefRule("chara", "addImages4/image/id", "ddsImage", None),
    RefRule("chara", "addImages5/image/id", "ddsImage", None),
    RefRule("chara", "addImages6/image/id", "ddsImage", None),
    RefRule("chara", "addImages7/image/id", "ddsImage", None),
    RefRule("chara", "addImages8/image/id", "ddsImage", None),
    RefRule("chara", "addImages9/image/id", "ddsImage", None),
    RefRule("chara", "works/id", "charaWorks", None),
    RefRule("chara", "releaseTagName/id", "releaseTag", None),
    RefRule("chara", "netOpenName/id", "netOpen", None),
    RefRule(
        "chara",
        "ranks/CharaRankData/rewardSkillSeed/rewardSkillSeed/id",
        "reward",
        None,
    ),
    # --- Stage.xml ---
    RefRule("stage", "releaseTagName/id", "releaseTag", None),
    RefRule("stage", "netOpenName/id", "netOpen", None),
    RefRule("stage", "notesFieldLine/id", "notesFieldLine", None),
    # --- Course.xml ---
    RefRule("course", "selectMusic/musicName/id", "music", None),
    # --- Quest.xml ---
    RefRule("quest", "charas/list/StringID/id", "chara", None),
    RefRule(
        "quest",
        "info/QuestRewardDataInfo/keyTrophyName/id",
        "trophy",
        None,
    ),
    RefRule(
        "quest",
        "info/QuestRewardDataInfo/keyNamePlateName/id",
        "namePlate",
        None,
    ),
    RefRule(
        "quest",
        "info/QuestRewardDataInfo/keyCharaName/id",
        "chara",
        None,
    ),
)


# ---------------------------------------------------------------------------
# XML filename -> source_kind mapping
# ---------------------------------------------------------------------------

import re

# Exact name mapping (covers all single-file resource types)
_XML_KIND_EXACT: dict[str, str] = {
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

# Pattern mapping (compiled once, checked if exact match fails)
_XML_KIND_PATTERN: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^DDSGlobalImage(\d+)\.xml$"), "ddsImage"),
]


def infer_kind_from_xml(xml_path: Path) -> str | None:
    """按 XML 文件名推断 source_kind。

    若文件名不在预定义映射中，返回 ``None``（该 XML 不会被处理）。
    """
    name = xml_path.name
    exact = _XML_KIND_EXACT.get(name)
    if exact is not None:
        return exact
    for pat, kind in _XML_KIND_PATTERN:
        if pat.fullmatch(name):
            return kind
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match_condition(el: "ET.Element", condition: str) -> bool:
    """检查 ``condition`` 如 ``"type=2"`` 是否成立。

    对于 Reward.xml 的子物质（RewardSubstanceData），查找其 ``type``
    子元素的文本是否等于指定值。
    """
    # 解析条件： "type=N"
    eq_pos = condition.find("=")
    if eq_pos < 0:
        return False
    tag_name = condition[:eq_pos].strip()
    expected = condition[eq_pos + 1:].strip()

    # 从 el 向上找到最近的包含 type 的子元素的祖先（即 substance 节点本身）
    # condition 是在 xpath 路径上的判断 —— xpath 形如
    # ".//RewardSubstanceData/trophy/trophyName/id"
    # type 就在 TrophyName 的兄弟 / 祖先上
    # 策略：检查 el 的父元素（即 <trophyName> 的父，即 <trophy> 的父，
    # 即 RewardSubstanceData）的 type 子元素
    current = el.getparent() if hasattr(el, "getparent") else el
    while current is not None:
        type_el = current.find(tag_name)
        if type_el is not None and type_el.text:
            return type_el.text.strip() == expected
        current = current.getparent() if hasattr(current, "getparent") else None
    return False


# ---------------------------------------------------------------------------
# 构建函数
# ---------------------------------------------------------------------------

def build_reference_graph(
    staging_root: Path,
    resources: list[PackageResource],
) -> ReferenceGraph:
    """解析 ``staging_root`` 下所有 XML，按 ``REF_RULES`` 提取引用边。

    Parameters
        staging_root:  解压后的暂存区根目录
        resources:     ``scan_package_resources`` 返回的资源列表

    Returns
        完整的 ``ReferenceGraph``，包含 ``nodes`` 和 ``edges``。
    """
    nodes: dict[tuple[str, int], PackageResource] = {
        (r.kind, r.resource_id): r for r in resources
    }

    # Pre-index rules by source_kind for performance
    _rules_by_kind: dict[str, list[RefRule]] = {}
    for rule in REF_RULES:
        _rules_by_kind.setdefault(rule.source_kind, []).append(rule)

    edges: list[RefEdge] = []
    visited_paths: set[Path] = set()

    for xml_path in staging_root.rglob("*.xml"):
        # Avoid processing the same physical file twice (symlinks, hard links)
        resolved = xml_path.resolve()
        if resolved in visited_paths:
            continue
        visited_paths.add(resolved)

        source_kind = infer_kind_from_xml(xml_path)
        if source_kind is None:
            continue

        rules = _rules_by_kind.get(source_kind)
        if not rules:
            continue

        try:
            tree = ET.parse(str(xml_path))
        except ET.ParseError:
            # Malformed XML — skip silently; caller can report later.
            continue

        root = tree.getroot()
        # Register namespace for .// xpath support
        # (ElementTree doesn't auto-handle namespaces in .//,
        #  but Chuni XMLs don't typically use them.)

        for rule in rules:
            try:
                matches = root.findall(rule.xpath)
            except ET.XPathError:
                # Invalid xpath — skip.
                continue

            for el in matches:
                target_id = _safe_int(el.text)
                if target_id is None or target_id < 0:
                    continue

                # Evaluate condition (e.g., type=2 for Reward)
                if rule.condition and not _match_condition(el, rule.condition):
                    continue

                in_package = (rule.target_kind, target_id) in nodes

                edges.append(
                    RefEdge(
                        source_file=xml_path,
                        source_kind=source_kind,
                        xpath=rule.xpath,
                        target_kind=rule.target_kind,
                        target_id=target_id,
                        in_package=in_package,
                    )
                )

    return ReferenceGraph(nodes, edges)