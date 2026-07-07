"""
段位组曲（CLASS Ⅰ～Ⅴ）Course.xml 的扫描、读取与写入。

结构参考 A001 ``course00045009`` / ``course00040000``：每套组曲 3 首固定曲目，
``difficulty`` 为 CLASS 段位，``infos`` 内为 ``CourseMusicDataInfo`` 列表。
"""
from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET
from pathlib import Path

from .course_rule import (
    CourseRuleParams,
    resolve_course_rule_id_for_save,
    write_course_rule_xml,
)
from .acus_scan import IdStr, _get_idstr, iter_xml_files
from .course_sort import append_course_sort
from .unlock_challenge import read_music_net_open, read_music_release_tag

RANK_COURSE_SLOT_COUNT = 3
CUSTOM_RANK_COURSE_ID_MIN = 490_000
CUSTOM_RANK_COURSE_ID_MAX = 499_999

# difficulty.id -> (str, data) — 与 A001 CourseDifSort 一致（Ⅰ～Ⅴ + ∞）
RANK_DIFFICULTIES: tuple[tuple[int, str, str], ...] = (
    (10, "ID_10", "CLASS Ⅰ"),
    (11, "ID_11", "CLASS Ⅱ"),
    (12, "ID_12", "CLASS Ⅲ"),
    (13, "ID_13", "CLASS Ⅳ"),
    (14, "ID_14", "CLASS Ⅴ"),
    (20, "ID_20", "CLASS ∞"),
)

_RANK_DIFFICULTY_IDS = frozenset(d[0] for d in RANK_DIFFICULTIES)

_MUSIC_DIFFS: tuple[tuple[int, str, str], ...] = (
    (0, "Basic", "BASIC"),
    (1, "Advanced", "ADVANCED"),
    (2, "Expert", "EXPERT"),
    (3, "Master", "MASTER"),
    (4, "Ultima", "ULTIMA"),
)

DEFAULT_COURSE_REWARD_ID = 10000300
DEFAULT_COURSE_REWARD_STR = "Point 30000"


def _safe_int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# type=1 按等级池随机的等级枚举（id 19-30 对应 Lv10-Lv15+）
# 每项: (level_id, level_label) — level_label 用于 UI 显示，str 字段恒为 ID_{id}
RANDOM_LEVEL_CHOICES: tuple[tuple[int, str], ...] = (
    (19, "Lv10"), (20, "Lv10+"),
    (21, "Lv11"), (22, "Lv11+"),
    (23, "Lv12"), (24, "Lv12+"),
    (25, "Lv13"), (26, "Lv13+"),
    (27, "Lv14"), (28, "Lv14+"),
    (29, "Lv15"), (30, "Lv15+"),
)


def _level_label_to_id(label: str) -> int:
    """Lv10 → 19, Lv10+ → 20, ... 找不到返回 -1。"""
    for lid, lstr in RANDOM_LEVEL_CHOICES:
        if lstr == label:
            return lid
    return -1


def _level_id_to_label(lid: int) -> str:
    """19 → Lv10, 20 → Lv10+, ... 找不到返回空串。"""
    for level_id, lstr in RANDOM_LEVEL_CHOICES:
        if level_id == lid:
            return lstr
    return ""


def is_rank_course_root(root: ET.Element) -> bool:
    diff_id = _safe_int(root.findtext("difficulty/id"))
    return diff_id in _RANK_DIFFICULTY_IDS


@dataclass(frozen=True)
class CourseMusicSlot:
    """一个曲目槽位。

    slot_type=0 固定选曲：用 music_id/diff_id/music_str/diff_str/diff_data
    slot_type=1 按等级池随机：用 level_id（19-30），music_id=-1, diff_id=-1
    slot_type=2 按候选池随机：用 candidates（list[CourseMusicCandidate]），music_id=-1, diff_id=-1
    """
    music_id: int = -1
    music_str: str = ""
    diff_id: int = -1
    diff_str: str = ""
    diff_data: str = ""
    slot_type: int = 0          # 0=固定 1=按等级随机 2=按候选池随机
    level_id: int = -1          # slot_type=1 时用（19-30）
    candidates: tuple["CourseMusicCandidate", ...] = ()  # slot_type=2 时用

    @property
    def is_fixed(self) -> bool:
        return self.slot_type == 0

    @property
    def is_level_random(self) -> bool:
        return self.slot_type == 1

    @property
    def is_pool_random(self) -> bool:
        return self.slot_type == 2


@dataclass(frozen=True)
class CourseMusicCandidate:
    """type=2 候选池里的一首歌。"""
    music_id: int
    music_str: str
    diff_id: int
    diff_str: str
    diff_data: str


@dataclass(frozen=True)
class RankCourseItem:
    xml_path: Path
    name: IdStr
    difficulty_id: int
    difficulty_label: str
    rule_id: int
    reward: IdStr | None
    rule_params: CourseRuleParams | None
    music_slots: tuple[CourseMusicSlot, ...]
    music_summary: str

    @property
    def slot_count(self) -> int:
        return len(self.music_slots)


@dataclass
class RankCourseDraft:
    """编辑/新建用的可写模型。"""

    course_id: int
    course_name: str
    difficulty_id: int
    rule_id: int
    reward_id: int
    reward_str: str
    rule_params: CourseRuleParams
    release_tag_id: int
    release_tag_str: str
    net_open_id: int
    net_open_str: str
    music_slots: list[CourseMusicSlot]


def _parse_music_slot(info: ET.Element) -> CourseMusicSlot | None:
    slot_type = _safe_int(info.findtext("type")) or 0

    if slot_type == 1:
        # 按等级池随机
        level_id = _safe_int(info.findtext("selectLevel/fromLevel/id")) or -1
        if level_id < 19 or level_id > 30:
            return None
        return CourseMusicSlot(
            slot_type=1,
            level_id=level_id,
            music_str=_level_id_to_label(level_id),  # 用于 _music_summary 显示
        )

    if slot_type == 2:
        # 按候选池随机
        candidates: list[CourseMusicCandidate] = []
        for sub in info.findall("selectMusicList/musicList/list/CourseMusicListSubData"):
            cid = _safe_int(sub.findtext("courseMusicData/name/id"))
            cstr = (sub.findtext("courseMusicData/name/str") or "").strip()
            cdid = _safe_int(sub.findtext("courseMusicData/diff/id"))
            cdstr = (sub.findtext("courseMusicData/diff/str") or "").strip()
            cddata = (sub.findtext("courseMusicData/diff/data") or "").strip()
            if cid is None or cdid is None:
                continue
            if not cdstr:
                cdstr = next((s for i, s, _ in _MUSIC_DIFFS if i == cdid), "Master")
            if not cddata:
                cddata = next((d for i, _, d in _MUSIC_DIFFS if i == cdid), cdstr.upper())
            candidates.append(CourseMusicCandidate(cid, cstr or f"Music{cid}", cdid, cdstr, cddata))
        if not candidates:
            return None
        return CourseMusicSlot(
            slot_type=2,
            candidates=tuple(candidates),
            music_str=f"{len(candidates)}首候选",  # 用于 _music_summary 显示
        )

    # slot_type == 0 固定选曲（现有逻辑）
    if slot_type not in (0, 1, 2):
        return None
    mid = _safe_int(info.findtext("selectMusic/musicName/id"))
    mstr = (info.findtext("selectMusic/musicName/str") or "").strip()
    did = _safe_int(info.findtext("selectMusic/musicDiff/id"))
    dstr = (info.findtext("selectMusic/musicDiff/str") or "").strip()
    ddata = (info.findtext("selectMusic/musicDiff/data") or "").strip()
    if mid is None or did is None:
        return None
    if not dstr:
        dstr = next((s for i, s, _ in _MUSIC_DIFFS if i == did), "Master")
    if not ddata:
        ddata = next((d for i, _, d in _MUSIC_DIFFS if i == did), dstr.upper())
    return CourseMusicSlot(mid, mstr or f"Music{mid}", did, dstr, ddata)


def _music_summary(slots: tuple[CourseMusicSlot, ...]) -> str:
    if not slots:
        return "—"
    parts: list[str] = []
    for s in slots[:3]:
        if s.is_fixed:
            parts.append(f"{s.music_str}({s.diff_str})")
        elif s.is_level_random:
            parts.append(f"{_level_id_to_label(s.level_id)}(随机)")
        elif s.is_pool_random:
            parts.append(f"{len(s.candidates)}首候选(随机)")
        else:
            parts.append("?")
    if len(slots) > 3:
        parts.append(f"+{len(slots) - 3}")
    return " · ".join(parts)


def parse_rank_course_xml(xml_path: Path, *, acus_root: Path | None = None) -> RankCourseItem | None:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return None
    if not is_rank_course_root(root):
        return None
    name = _get_idstr(root.find("name"))
    if name is None:
        return None
    diff_id = _safe_int(root.findtext("difficulty/id")) or 14
    diff_label = (root.findtext("difficulty/data") or "").strip() or f"CLASS({diff_id})"
    rule_id = _safe_int(root.findtext("rule/id")) or 25
    reward = _get_idstr(root.find("reward"))
    rule_params: CourseRuleParams | None = None
    if acus_root is not None:
        from .course_rule import load_course_rule_params

        rule_params = load_course_rule_params(acus_root, int(rule_id))
    slots: list[CourseMusicSlot] = []
    for info in root.findall("infos/CourseMusicDataInfo"):
        slot = _parse_music_slot(info)
        if slot is not None:
            slots.append(slot)
    slot_t = tuple(slots)
    return RankCourseItem(
        xml_path=xml_path,
        name=name,
        difficulty_id=diff_id,
        difficulty_label=diff_label,
        rule_id=int(rule_id),
        reward=reward,
        rule_params=rule_params,
        music_slots=slot_t,
        music_summary=_music_summary(slot_t),
    )


def scan_rank_courses(acus_root: Path) -> list[RankCourseItem]:
    items: list[RankCourseItem] = []
    for p in iter_xml_files(acus_root, "course/**/Course.xml"):
        it = parse_rank_course_xml(p, acus_root=acus_root)
        if it is not None:
            items.append(it)
    items.sort(key=lambda x: (x.difficulty_id, x.name.id))
    return items


def load_rank_course_draft(acus_root: Path, xml_path: Path) -> RankCourseDraft | None:
    try:
        root = ET.parse(xml_path).getroot()
    except Exception:
        return None
    name = _get_idstr(root.find("name"))
    if name is None:
        return None
    diff_id = _safe_int(root.findtext("difficulty/id")) or 14
    rule_id = _safe_int(root.findtext("rule/id")) or 25
    rt_id = _safe_int(root.findtext("releaseTagName/id")) or 20
    rt_str = (root.findtext("releaseTagName/str") or "").strip() or "v2 2.45.00"
    no_id = _safe_int(root.findtext("netOpenName/id")) or 2801
    no_str = (root.findtext("netOpenName/str") or "").strip() or "v2_45 00_1"
    from .course_rule import load_course_rule_params

    rule_params = load_course_rule_params(acus_root, int(rule_id)) or CourseRuleParams()
    slots: list[CourseMusicSlot] = []
    for info in root.findall("infos/CourseMusicDataInfo"):
        slot = _parse_music_slot(info)
        if slot is not None:
            slots.append(slot)
    while len(slots) < RANK_COURSE_SLOT_COUNT:
        slots.append(CourseMusicSlot(0, "Invalid", 3, "Master", "MASTER"))
    return RankCourseDraft(
        course_id=name.id,
        course_name=name.str,
        difficulty_id=diff_id,
        rule_id=int(rule_id),
        reward_id=DEFAULT_COURSE_REWARD_ID,
        reward_str=DEFAULT_COURSE_REWARD_STR,
        rule_params=rule_params,
        release_tag_id=rt_id,
        release_tag_str=rt_str,
        net_open_id=no_id,
        net_open_str=no_str,
        music_slots=slots[:RANK_COURSE_SLOT_COUNT],
    )


def _used_course_name_ids(acus_root: Path) -> set[int]:
    used: set[int] = set()
    root = acus_root / "course"
    if not root.is_dir():
        return used
    for p in root.glob("course*/Course.xml"):
        try:
            r = ET.parse(p).getroot()
            v = _safe_int(r.findtext("name/id"))
            if v is not None:
                used.add(v)
        except Exception:
            continue
    return used


def next_custom_rank_course_id(acus_root: Path) -> int:
    used = _used_course_name_ids(acus_root)
    for cid in range(CUSTOM_RANK_COURSE_ID_MIN, CUSTOM_RANK_COURSE_ID_MAX + 1):
        if cid not in used:
            return cid
    raise ValueError(
        f"{CUSTOM_RANK_COURSE_ID_MIN}～{CUSTOM_RANK_COURSE_ID_MAX} 内已无空闲课题 ID。"
    )


def default_rank_course_draft(acus_root: Path) -> RankCourseDraft:
    cid = next_custom_rank_course_id(acus_root)
    empty_slots = [
        CourseMusicSlot(0, "Invalid", 3, "Master", "MASTER") for _ in range(RANK_COURSE_SLOT_COUNT)
    ]
    return RankCourseDraft(
        course_id=cid,
        course_name="自定义段位组曲",
        difficulty_id=14,
        rule_id=0,
        reward_id=DEFAULT_COURSE_REWARD_ID,
        reward_str=DEFAULT_COURSE_REWARD_STR,
        rule_params=CourseRuleParams(),
        release_tag_id=20,
        release_tag_str="v2 2.45.00",
        net_open_id=2801,
        net_open_str="v2_45 00_1",
        music_slots=empty_slots,
    )


def _find_music_xml(acus_root: Path, music_id: int) -> Path | None:
    if music_id <= 0:
        return None
    mid = f"{int(music_id):04d}"
    for pat in (f"music/music{mid}/Music.xml", f"music/music{int(music_id)}/Music.xml"):
        p = acus_root / pat
        if p.is_file():
            return p
    return None


def apply_music_meta_to_draft(acus_root: Path, draft: RankCourseDraft, music_id: int) -> None:
    mx = _find_music_xml(acus_root, music_id)
    if mx is None:
        return
    rt_id, rt_str = read_music_release_tag(mx)
    no_id, no_str = read_music_net_open(mx)
    draft.release_tag_id = rt_id
    draft.release_tag_str = rt_str
    draft.net_open_id = no_id
    draft.net_open_str = no_str


def _course_music_block(slot: CourseMusicSlot) -> str:
    """根据 slot.slot_type 生成对应的 CourseMusicDataInfo XML 块。"""
    if slot.is_level_random:
        return _course_music_block_level(slot)
    if slot.is_pool_random:
        return _course_music_block_pool(slot)
    return _course_music_block_fixed(slot)


def _course_music_block_fixed(slot: CourseMusicSlot) -> str:
    """type=0 固定选曲（保持现有逻辑）。"""
    esc_m = _xml_esc(slot.music_str.strip() or f"Music{slot.music_id}")
    esc_ds = _xml_esc(slot.diff_str)
    esc_dd = _xml_esc(slot.diff_data)
    return f"""    <CourseMusicDataInfo>
      <type>0</type>
      <selectMusic>
        <musicName>
          <id>{int(slot.music_id)}</id>
          <str>{esc_m}</str>
          <data />
        </musicName>
        <musicDiff>
          <id>{int(slot.diff_id)}</id>
          <str>{esc_ds}</str>
          <data>{esc_dd}</data>
        </musicDiff>
      </selectMusic>
      <selectLevel>
        <fromLevel>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </fromLevel>
      </selectLevel>
      <selectMusicList>
        <musicList>
          <list />
        </musicList>
        <panelType>0</panelType>
        <isRecordShown>true</isRecordShown>
      </selectMusicList>
    </CourseMusicDataInfo>"""


def _course_music_block_level(slot: CourseMusicSlot) -> str:
    """type=1 按等级池随机。"""
    lid = int(slot.level_id)
    lstr = _xml_esc(f"ID_{lid}")
    ldata = _xml_esc(_level_id_to_label(lid))
    return f"""    <CourseMusicDataInfo>
      <type>1</type>
      <selectMusic>
        <musicName>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </musicName>
        <musicDiff>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </musicDiff>
      </selectMusic>
      <selectLevel>
        <fromLevel>
          <id>{lid}</id>
          <str>{lstr}</str>
          <data>{ldata}</data>
        </fromLevel>
      </selectLevel>
      <selectMusicList>
        <musicList>
          <list />
        </musicList>
        <panelType>0</panelType>
        <isRecordShown>true</isRecordShown>
      </selectMusicList>
    </CourseMusicDataInfo>"""


def _course_music_block_pool(slot: CourseMusicSlot) -> str:
    """type=2 按候选池随机。"""
    candidate_blocks: list[str] = []
    for c in slot.candidates:
        esc_cm = _xml_esc(c.music_str.strip() or f"Music{c.music_id}")
        esc_cds = _xml_esc(c.diff_str)
        esc_cdd = _xml_esc(c.diff_data)
        candidate_blocks.append(f"""            <CourseMusicListSubData>
              <type>0</type>
              <courseMusicData>
                <name>
                  <id>{int(c.music_id)}</id>
                  <str>{esc_cm}</str>
                  <data />
                </name>
                <diff>
                  <id>{int(c.diff_id)}</id>
                  <str>{esc_cds}</str>
                  <data>{esc_cdd}</data>
                </diff>
              </courseMusicData>
            </CourseMusicListSubData>""")
    if candidate_blocks:
        list_body = "\n".join(candidate_blocks)
        list_xml = f"          <list>\n{list_body}\n          </list>"
    else:
        list_xml = "          <list />"
    return f"""    <CourseMusicDataInfo>
      <type>2</type>
      <selectMusic>
        <musicName>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </musicName>
        <musicDiff>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </musicDiff>
      </selectMusic>
      <selectLevel>
        <fromLevel>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </fromLevel>
      </selectLevel>
      <selectMusicList>
        <musicList>
{list_xml}
        </musicList>
        <panelType>1</panelType>
        <isRecordShown>false</isRecordShown>
      </selectMusicList>
    </CourseMusicDataInfo>"""


def _difficulty_triple(diff_id: int) -> tuple[int, str, str]:
    for did, ds, dd in RANK_DIFFICULTIES:
        if did == diff_id:
            return did, ds, dd
    return 14, "ID_14", "CLASS Ⅴ"


def write_rank_course_xml(
    *,
    acus_root: Path,
    draft: RankCourseDraft,
    is_edit: bool = False,
    game_root: str | Path | None = None,
) -> Path:
    rule_id = resolve_course_rule_id_for_save(
        acus_root,
        existing_rule_id=int(draft.rule_id),
        is_edit=is_edit,
    )
    write_course_rule_xml(acus_root=acus_root, rule_id=rule_id, params=draft.rule_params)
    draft.rule_id = rule_id
    draft.reward_id = DEFAULT_COURSE_REWARD_ID
    draft.reward_str = DEFAULT_COURSE_REWARD_STR

    diff_id, diff_str, diff_data = _difficulty_triple(draft.difficulty_id)
    c8 = f"{int(draft.course_id):08d}"
    esc_name = _xml_esc(draft.course_name.strip() or f"Course{draft.course_id}")
    esc_rt = _xml_esc(draft.release_tag_str.strip() or "Invalid")
    esc_no = _xml_esc(draft.net_open_str.strip() or "v2_45 00_1")
    esc_rw = _xml_esc(DEFAULT_COURSE_REWARD_STR)
    infos_body = "\n".join(_course_music_block(s) for s in draft.music_slots[:RANK_COURSE_SLOT_COUNT])
    rule_str = f"{rule_id:04d}" if rule_id < 10000 else str(rule_id)
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<CourseData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>course{c8}</dataName>
  <releaseTagName>
    <id>{int(draft.release_tag_id)}</id>
    <str>{esc_rt}</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>{int(draft.net_open_id)}</id>
    <str>{esc_no}</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{int(draft.course_id)}</id>
    <str>{esc_name}</str>
    <data />
  </name>
  <difficulty>
    <id>{diff_id}</id>
    <str>{diff_str}</str>
    <data>{diff_data}</data>
  </difficulty>
  <rule>
    <id>{rule_id}</id>
    <str>{rule_str}</str>
    <data />
  </rule>
  <reward>
    <id>{DEFAULT_COURSE_REWARD_ID}</id>
    <str>{esc_rw}</str>
    <data />
  </reward>
  <reward2nd>
    <id>0</id>
    <str>なし</str>
    <data />
  </reward2nd>
  <teamOnly>false</teamOnly>
  <isMusicDuplicateAllowed>true</isMusicDuplicateAllowed>
  <conditionsCourse>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </conditionsCourse>
  <conditionsText />
  <priority>0</priority>
  <infos>
{infos_body}
  </infos>
</CourseData>
"""
    cdir = acus_root / "course" / f"course{c8}"
    cdir.mkdir(parents=True, exist_ok=True)
    out = cdir / "Course.xml"
    out.write_text(xml, encoding="utf-8", newline="\n")
    append_course_sort(acus_root, [int(draft.course_id)], game_root=game_root)
    from .course_event import sync_rank_course_unlock_event

    sync_rank_course_unlock_event(
        acus_root,
        net_open_id=int(draft.net_open_id),
        net_open_str=draft.net_open_str,
    )
    return out


def music_diff_choices() -> tuple[tuple[int, str, str], ...]:
    return _MUSIC_DIFFS
