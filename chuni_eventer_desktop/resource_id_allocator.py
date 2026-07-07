"""
资源 ID 分配器 — 统一管理 ACUS 侧所有资源类型的新 ID 分配。

本模块为「资源压缩包快捷导入」功能提供 ID 分配服务，核心目标：
- 同一 plan 内多次分配不重复；
- 分配结果不与 ACUS 已有 ID 冲突；
- 覆盖架构文档 §7.2 列出的全部资源类型号段策略。

使用示例
--------
    from pathlib import Path
    from chuni_eventer_desktop.resource_id_allocator import ResourceIdAllocator

    allocator = ResourceIdAllocator(Path("E:/Python Project/Chuni-Eventer/ACUS"))
    music_id = allocator.allocate("music")          # 单个 int
    trophies = allocator.allocate("trophy", count=3) # 连续 tuple
"""
from __future__ import annotations

from pathlib import Path
from typing import overload

from .course_rank import next_custom_rank_course_id
from .course_rule import next_custom_course_rule_id
from .unlock_challenge import next_custom_unlock_reward_id
from .mapbonus_xml import suggest_next_mapbonus_id
from .map_icon_xml import suggest_next_map_icon_id

try:
    import xml.etree.ElementTree as ET
except ImportError:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# 公共异常
# ---------------------------------------------------------------------------

class UnsupportedAllocationError(ValueError):
    """资源类型不支持自动分配 ID 时抛出。"""


# ---------------------------------------------------------------------------
# 通用扫描辅助
# ---------------------------------------------------------------------------

def _safe_int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def _scan_kind_ids(acus_root: Path, kind: str, xml_glob: str, id_xpath: str = "name/id") -> set[int]:
    """
    在 *acus_root* 下扫描所有符合 *xml_glob* 的 XML，
    提取 *id_xpath* 处的整数 ID，返回 ``set[int]``。
    """
    if ET is None:
        return set()
    ids: set[int] = set()
    root_path = acus_root / kind
    if not root_path.is_dir():
        return ids
    for xml_path in root_path.rglob(xml_glob):
        try:
            root = ET.parse(xml_path).getroot()
            v = _safe_int(root.findtext(id_xpath))
            if v is not None and v >= 0:
                ids.add(v)
        except Exception:
            continue
    return ids


def _scan_directory_numeric_names(acus_root: Path, kind: str, prefix: str = "") -> set[int]:
    """
    扫描 *acus_root/kind* 下所有子目录名，提取以 *prefix* 开头
    后跟纯数字的部分，返回整数集合。

    示例：``kind="music"`` → 扫描 ``music/music7001``, ``music/music07001`` → {7001}
    """
    if ET is None:
        return set()
    ids: set[int] = set()
    kind_path = acus_root / kind
    if not kind_path.is_dir():
        return ids
    for d in kind_path.iterdir():
        if not d.is_dir():
            continue
        name = d.name
        if prefix and not name.startswith(prefix):
            continue
        suffix = name[len(prefix):]
        if suffix.isdigit() or (suffix and suffix.lstrip("0").isdigit() and int(suffix) > 0):
            try:
                ids.add(int(suffix))
            except ValueError:
                continue
        elif suffix == "" and prefix == name:
            # 目录名就是前缀本身（无数字），跳过
            continue
    return ids


# ---------------------------------------------------------------------------
# 各类型分配策略
# ---------------------------------------------------------------------------

def _alloc_course(acus_root: Path, count: int, _plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """
    course (rank) → next_custom_rank_course_id()
    course (unlockChallenge) → next_perfect_challenge_course_base_id() + 连续 5 个

    统一接口：rank 模式分配单个；unlockChallenge 模式分配 5 个连续。
    对于通用场景（非 unlockChallenge），调用 course_rank 的分配函数。
    """
    if count > 1:
        raise UnsupportedAllocationError(
            f"course 类型不支持 count={count} 的分配，请使用 count=1 或单独处理 unlockChallenge 连续 5 个 ID。"
        )
    return next_custom_rank_course_id(acus_root)


def _alloc_courerule(acus_root: Path, count: int, _plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """courseRule → next_custom_course_rule_id()，号段 7001-7999。"""
    if count != 1:
        raise UnsupportedAllocationError(f"courseRule 不支持 count={count} 的分配。")
    return next_custom_course_rule_id(acus_root)


def _alloc_reward(acus_root: Path, count: int, _plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """
    reward → next_custom_unlock_reward_id()，号段 200000000-299999999。
    """
    if count != 1:
        raise UnsupportedAllocationError(f"reward 不支持 count={count} 的分配。")
    return next_custom_unlock_reward_id(acus_root)


def _alloc_trophy(acus_root: Path, count: int, plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """trophy → max(50000, used_max + count) 起连续分配。"""
    base_min = 50_000
    used = _scan_kind_ids(acus_root, "trophy", "Trophy.xml", "name/id")
    used |= plan_allocated.get("trophy", set())
    candidate = max(base_min, max(used, default=base_min - 1) + 1)
    ids: list[int] = []
    for _ in range(count):
        while candidate in used:
            candidate += 1
        ids.append(candidate)
        candidate += 1
    if count == 1:
        return ids[0]
    return tuple(ids)


def _alloc_system_voice(acus_root: Path, count: int, plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """systemVoice → 扫描目录名 max(700, used_max + count) 起连续分配。"""
    base_min = 700
    used = _scan_directory_numeric_names(acus_root, "systemVoice", "systemVoice")
    used |= plan_allocated.get("systemVoice", set())
    candidate = max(base_min, max(used, default=base_min - 1) + 1)
    ids: list[int] = []
    for _ in range(count):
        while candidate in used:
            candidate += 1
        ids.append(candidate)
        candidate += 1
    if count == 1:
        return ids[0]
    return tuple(ids)


def _alloc_music(acus_root: Path, count: int, plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """music → 扫描目录名 max(7000, used_max + count) 起连续分配。"""
    base_min = 7_000
    used = _scan_directory_numeric_names(acus_root, "music", "music")
    used |= plan_allocated.get("music", set())
    candidate = max(base_min, max(used, default=base_min - 1) + 1)
    ids: list[int] = []
    for _ in range(count):
        while candidate in used:
            candidate += 1
        ids.append(candidate)
        candidate += 1
    if count == 1:
        return ids[0]
    return tuple(ids)


def _alloc_generic(
    acus_root: Path,
    kind: str,
    count: int,
    xml_glob: str,
    id_xpath: str,
    base_min: int,
    plan_allocated: dict[str, set[int]],
) -> int | tuple[int, ...]:
    """
    通用分配器：扫描对应目录 XML 的 name/id，取 max(base_min, used_max + 1) 起连续分配。

    参数
    ----
    kind : 资源类型名（用于构建目录路径）
    xml_glob : 搜索的 XML 文件名 glob
    id_xpath : ID 字段的 XPath
    base_min : 最小 ID 号段起点
    """
    used = _scan_kind_ids(acus_root, kind, xml_glob, id_xpath)
    used |= plan_allocated.get(kind, set())
    candidate = max(base_min, max(used, default=base_min - 1) + 1)
    ids: list[int] = []
    for _ in range(count):
        while candidate in used:
            candidate += 1
        ids.append(candidate)
        candidate += 1
    if count == 1:
        return ids[0]
    return tuple(ids)


def _alloc_cuefile(acus_root: Path, count: int, plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """
    cueFile → 扫描目录名 cueFile*/ 取数字后缀 max(used_max + 1)，无固定下限。
    联动 systemVoice（10000+voice_id）由编排器层处理，不在此分配。
    """
    used = _scan_directory_numeric_names(acus_root, "cueFile", "cueFile")
    used |= plan_allocated.get("cueFile", set())
    if not used:
        candidate = 1
    else:
        candidate = max(used) + 1
    ids: list[int] = []
    for _ in range(count):
        while candidate in used:
            candidate += 1
        ids.append(candidate)
        candidate += 1
    if count == 1:
        return ids[0]
    return tuple(ids)


def _alloc_mapbonus(acus_root: Path, count: int, _plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """mapBonus → suggest_next_mapbonus_id()，号段从 10000000 起。"""
    if count != 1:
        raise UnsupportedAllocationError(f"mapBonus 不支持 count={count} 的分配。")
    return suggest_next_mapbonus_id(acus_root, start=10_000_000)


def _alloc_mapicon(acus_root: Path, count: int, _plan_allocated: dict[str, set[int]]) -> int | tuple[int, ...]:
    """mapIcon → suggest_next_map_icon_id()，扫 ACUS max+1。"""
    if count != 1:
        raise UnsupportedAllocationError(f"mapIcon 不支持 count={count} 的分配。")
    return suggest_next_map_icon_id(acus_root)


# ---------------------------------------------------------------------------
# 策略注册表
# ---------------------------------------------------------------------------

_STRATEGIES: dict[str, callable] = {
    "course":       _alloc_course,
    "courseRule":   _alloc_courerule,
    "reward":       _alloc_reward,
    "trophy":       _alloc_trophy,
    "systemVoice":  _alloc_system_voice,
    "music":        _alloc_music,
    "chara":        lambda ac, c, pa: _alloc_generic(ac, "chara", c, "Chara.xml", "name/id", 70_000, pa),
    "namePlate":    lambda ac, c, pa: _alloc_generic(ac, "namePlate", c, "NamePlate.xml", "name/id", 70_000, pa),
    "stage":        lambda ac, c, pa: _alloc_generic(ac, "stage", c, "Stage.xml", "name/id", 70_000, pa),
    "map":          lambda ac, c, pa: _alloc_generic(ac, "map", c, "Map.xml", "name/id", 70_000_000, pa),
    "mapArea":      lambda ac, c, pa: _alloc_generic(ac, "mapArea", c, "MapArea.xml", "name/id", 70_000_000, pa),
    "mapBonus":     _alloc_mapbonus,
    "mapIcon":      _alloc_mapicon,
    "event":        lambda ac, c, pa: _alloc_generic(ac, "event", c, "Event.xml", "name/id", 70_000, pa),
    "ddsImage":     lambda ac, c, pa: _alloc_generic(ac, "ddsImage", c, "DDSImage.xml", "name/id", 70_000, pa),
    "ddsMap":       lambda ac, c, pa: _alloc_generic(ac, "ddsMap", c, "DDSMap.xml", "name/id", 70_000_000, pa),
    "ddsBanner":    lambda ac, c, pa: _alloc_generic(ac, "ddsBanner", c, "DDSImage.xml", "name/id", 70_000, pa),
    "cueFile":      _alloc_cuefile,
    # 以下类型：通用策略，扫 XML name/id，下限 70000
    "charaWorks":   lambda ac, c, pa: _alloc_generic(ac, "charaWorks", c, "CharaWorks.xml", "name/id", 70_000, pa),
    "skill":        lambda ac, c, pa: _alloc_generic(ac, "skill", c, "Skill.xml", "name/id", 70_000, pa),
    "skillCategory": lambda ac, c, pa: _alloc_generic(ac, "skillCategory", c, "SkillCategory.xml", "name/id", 70_000, pa),
    "musicGenre":   lambda ac, c, pa: _alloc_generic(ac, "musicGenre", c, "MusicGenre.xml", "name/id", 70_000, pa),
    "musicLabel":   lambda ac, c, pa: _alloc_generic(ac, "musicLabel", c, "MusicLabel.xml", "name/id", 70_000, pa),
    "releaseTag":   lambda ac, c, pa: _alloc_generic(ac, "releaseTag", c, "ReleaseTag.xml", "name/id", 70_000, pa),
    "netOpen":      lambda ac, c, pa: _alloc_generic(ac, "netOpen", c, "NetOpen.xml", "name/id", 70_000, pa),
    "gauge":        lambda ac, c, pa: _alloc_generic(ac, "gauge", c, "Gauge.xml", "name/id", 70_000, pa),
    "timeTable":    lambda ac, c, pa: _alloc_generic(ac, "timeTable", c, "TimeTable.xml", "name/id", 70_000, pa),
    "notesFieldLine": lambda ac, c, pa: _alloc_generic(ac, "notesFieldLine", c, "NotesFieldLine.xml", "name/id", 70_000, pa),
    "ticket":       lambda ac, c, pa: _alloc_generic(ac, "ticket", c, "Ticket.xml", "name/id", 70_000, pa),
    "avatarAccessory": lambda ac, c, pa: _alloc_generic(ac, "avatarAccessory", c, "AvatarAccessory.xml", "name/id", 70_000, pa),
    "quest":        lambda ac, c, pa: _alloc_generic(ac, "quest", c, "Quest.xml", "name/id", 70_000, pa),
}


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------

class ResourceIdAllocator:
    """
    统一资源 ID 分配器。

    同一次 plan 内多次分配不会重复，分配的 ID 集合通过 ``used_ids()`` 公开。
    所有策略均覆盖架构文档 §7.2 定义的资源类型。

    用法
    ----
    >>> allocator = ResourceIdAllocator(acus_root)
    >>> music_id = allocator.allocate("music")                     # 返回 int
    >>> ids = allocator.allocate("trophy", count=3)               # 返回 tuple[int, ...]
    >>> all_used = allocator.used_ids("music")                     # 返回 set[int]
    """

    def __init__(self, acus_root: Path) -> None:
        self._acus_root = Path(acus_root).resolve()
        self._plan_allocated: dict[str, set[int]] = {}

    # ------------------------------------------------------------------
    # 公有 API
    # ------------------------------------------------------------------

    @overload
    def allocate(self, kind: str, count: int = 1) -> int: ...

    @overload
    def allocate(self, kind: str, count: int) -> tuple[int, ...]: ...

    def allocate(self, kind: str, count: int = 1) -> int | tuple[int, ...]:
        """
        分配 *count* 个新 ID。

        参数
        ----
        kind : 资源类型名，如 ``"music"``、``"trophy"``、``"course"``
        count : 分配数量，默认为 1。

        返回
        ----
        count == 1 时返回 ``int``；count > 1 时返回 ``tuple[int, ...]``（连续或独立 ID）。

        异常
        ----
        UnsupportedAllocationError : 类型不支持或 count > 1 不支持连续分配时抛出。
        """
        strategy = _STRATEGIES.get(kind)
        if strategy is None:
            raise UnsupportedAllocationError(
                f"资源类型 '{kind}' 不支持自动分配 ID。"
            )
        ids = strategy(self._acus_root, count, self._plan_allocated)
        # 标准化为 list 以便记录
        if isinstance(ids, int):
            id_list: list[int] = [ids]
        else:
            id_list = list(ids)
        self._record_allocated(kind, id_list)
        return ids

    def used_ids(self, kind: str) -> set[int]:
        """
        返回该类型当前已占用 ID 集合（ACUS 已有 + 本 plan 已分配）。

        注意：此方法会实时扫描 ACUS 磁盘，因此可能比实际使用略慢。
        """
        strategy = _STRATEGIES.get(kind)
        if strategy is None:
            return set()
        # 从策略中提取 ACUS 已有 ID（通过通用扫描逻辑）
        acus_ids = self._scan_acus_ids(kind)
        return acus_ids | self._plan_allocated.get(kind, set())

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _scan_acus_ids(self, kind: str) -> set[int]:
        """
        按 kind 分派到对应的扫描方式，返回 ACUS 上该类型已存在的 ID 集合。

        本方法与分配策略的扫描逻辑一致，确保 used_ids() 返回准确的上界。
        """
        match kind:
            case "course":
                # course 使用 Course.xml 的 name/id
                return _scan_kind_ids(self._acus_root, "course", "course*/Course.xml", "name/id")
            case "courseRule":
                return _scan_kind_ids(self._acus_root, "courseRule", "courseRule*/CourseRule.xml", "name/id")
            case "reward":
                return _scan_kind_ids(self._acus_root, "reward", "reward*/Reward.xml", "name/id")
            case "trophy":
                return _scan_kind_ids(self._acus_root, "trophy", "Trophy.xml", "name/id")
            case "systemVoice":
                return _scan_directory_numeric_names(self._acus_root, "systemVoice", "systemVoice")
            case "music":
                return _scan_directory_numeric_names(self._acus_root, "music", "music")
            case "cueFile":
                return _scan_directory_numeric_names(self._acus_root, "cueFile", "cueFile")
            case "chara":
                return _scan_kind_ids(self._acus_root, "chara", "Chara.xml", "name/id")
            case "namePlate":
                return _scan_kind_ids(self._acus_root, "namePlate", "NamePlate.xml", "name/id")
            case "stage":
                return _scan_kind_ids(self._acus_root, "stage", "Stage.xml", "name/id")
            case "map":
                return _scan_kind_ids(self._acus_root, "map", "Map.xml", "name/id")
            case "mapArea":
                return _scan_kind_ids(self._acus_root, "mapArea", "MapArea.xml", "name/id")
            case "mapBonus":
                return _scan_kind_ids(self._acus_root, "mapBonus", "MapBonus.xml", "name/id")
            case "mapIcon":
                return _scan_kind_ids(self._acus_root, "mapIcon", "MapIcon.xml", "name/id")
            case "event":
                return _scan_kind_ids(self._acus_root, "event", "Event.xml", "name/id")
            case "ddsImage":
                return _scan_kind_ids(self._acus_root, "ddsImage", "DDSImage.xml", "name/id")
            case "ddsMap":
                return _scan_kind_ids(self._acus_root, "ddsMap", "DDSMap.xml", "name/id")
            case "ddsBanner":
                return _scan_kind_ids(self._acus_root, "ddsBanner", "DDSImage.xml", "name/id")
            case "charaWorks":
                return _scan_kind_ids(self._acus_root, "charaWorks", "CharaWorks.xml", "name/id")
            case "skill":
                return _scan_kind_ids(self._acus_root, "skill", "Skill.xml", "name/id")
            case "skillCategory":
                return _scan_kind_ids(self._acus_root, "skillCategory", "SkillCategory.xml", "name/id")
            case "musicGenre":
                return _scan_kind_ids(self._acus_root, "musicGenre", "MusicGenre.xml", "name/id")
            case "musicLabel":
                return _scan_kind_ids(self._acus_root, "musicLabel", "MusicLabel.xml", "name/id")
            case "releaseTag":
                return _scan_kind_ids(self._acus_root, "releaseTag", "ReleaseTag.xml", "name/id")
            case "netOpen":
                return _scan_kind_ids(self._acus_root, "netOpen", "NetOpen.xml", "name/id")
            case "gauge":
                return _scan_kind_ids(self._acus_root, "gauge", "Gauge.xml", "name/id")
            case "timeTable":
                return _scan_kind_ids(self._acus_root, "timeTable", "TimeTable.xml", "name/id")
            case "notesFieldLine":
                return _scan_kind_ids(self._acus_root, "notesFieldLine", "NotesFieldLine.xml", "name/id")
            case "ticket":
                return _scan_kind_ids(self._acus_root, "ticket", "Ticket.xml", "name/id")
            case "avatarAccessory":
                return _scan_kind_ids(self._acus_root, "avatarAccessory", "AvatarAccessory.xml", "name/id")
            case "quest":
                return _scan_kind_ids(self._acus_root, "quest", "Quest.xml", "name/id")
            case _:
                return set()

    def _record_allocated(self, kind: str, ids: int | tuple[int, ...] | list[int]) -> None:
        """
        记录本 plan 已分配的 ID，避免后续重复分配。
        """
        if kind not in self._plan_allocated:
            self._plan_allocated[kind] = set()
        if isinstance(ids, int):
            self._plan_allocated[kind].add(ids)
        elif isinstance(ids, tuple):
            self._plan_allocated[kind].update(ids)
        elif isinstance(ids, list):
            self._plan_allocated[kind].update(ids)