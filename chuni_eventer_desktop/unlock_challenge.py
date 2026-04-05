"""
A001 解锁挑战（完美挑战）生成：UnlockChallenge + Event(type=16) + 自制课题(31xxxx) + 自制乐曲奖励(2xxxxxxxxx)。
参考：unlockChallenge00010002、course00300005～009、reward040002705、event00016044。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .acus_scan import MusicItem

CUSTOM_COURSE_ID_MIN = 310_000
CUSTOM_COURSE_ID_MAX = 319_999
CUSTOM_REWARD_ID_MIN = 200_000_000
CUSTOM_REWARD_ID_MAX = 299_999_999
PERFECT_CHALLENGE_COURSE_COUNT = 5
COURSE_INFO_SLOTS = 3


def default_music_jacket_reward_id(music_id: int) -> int:
    """官方曲绘类 reward 常见：13*10^6+musicId（自制请用 allocate_custom_unlock_reward_id）。"""
    return 13 * 1_000_000 + int(music_id)


def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_int(text: str | None) -> int | None:
    try:
        return int((text or "").strip())
    except Exception:
        return None


def read_music_net_open(music_xml: Path) -> tuple[int, str]:
    try:
        r = ET.parse(music_xml).getroot()
        ni = (r.findtext("netOpenName/id") or "").strip()
        ns = (r.findtext("netOpenName/str") or "").strip()
        try:
            n_id = int(ni)
        except ValueError:
            n_id = 2801
        n_s = (ns or "").strip() or "v2_45 00_1"
        return n_id, n_s
    except Exception:
        return 2801, "v2_45 00_1"


def read_music_release_tag(music_xml: Path) -> tuple[int, str]:
    try:
        r = ET.parse(music_xml).getroot()
        ri = (r.findtext("releaseTagName/id") or "").strip()
        rs = (r.findtext("releaseTagName/str") or "").strip()
        try:
            r_id = int(ri)
        except ValueError:
            r_id = -1
        return r_id, rs or "Invalid"
    except Exception:
        return -1, "Invalid"


def read_enabled_fumen_diffs(music_xml: Path) -> list[tuple[int, str, str]]:
    """enable=true 的谱面，按 type/id 升序。返回 (diff_id, type/str, type/data)。"""
    try:
        r = ET.parse(music_xml).getroot()
        out: list[tuple[int, str, str]] = []
        for f in r.findall("fumens/MusicFumenData"):
            if (f.findtext("enable") or "").strip().lower() != "true":
                continue
            tr = (f.findtext("type/id") or "").strip()
            if not tr.isdigit():
                continue
            tid = int(tr)
            s = (f.findtext("type/str") or "").strip()
            d = (f.findtext("type/data") or "").strip() or s.upper()
            out.append((tid, s, d))
        out.sort(key=lambda x: x[0])
        return out
    except Exception:
        return []


def pick_diff_for_course_index(
    diffs: list[tuple[int, str, str]], course_index: int
) -> tuple[int, str, str]:
    """course_index: 0..4 对应课题 -1～-5。谱不足时在可用难度间插值。"""
    if not diffs:
        return 3, "Master", "MASTER"
    if len(diffs) >= PERFECT_CHALLENGE_COURSE_COUNT:
        return diffs[min(course_index, len(diffs) - 1)]
    if len(diffs) == 1:
        return diffs[0]
    pos = round(course_index * (len(diffs) - 1) / (PERFECT_CHALLENGE_COURSE_COUNT - 1))
    return diffs[int(pos)]


def _used_course_name_ids(acus_root: Path) -> set[int]:
    used: set[int] = set()
    root = acus_root / "course"
    if not root.is_dir():
        return used
    for p in root.glob("course*/Course.xml"):
        try:
            r = ET.parse(p).getroot()
            id_el = r.find("name/id")
            if id_el is not None and (id_el.text or "").strip().isdigit():
                used.add(int(id_el.text.strip()))
        except Exception:
            continue
    return used


def next_perfect_challenge_course_base_id(acus_root: Path) -> int:
    """
    在 310000～319999 内取连续 5 个未占用的最小起始 ID。
    """
    used = _used_course_name_ids(acus_root)
    hi = CUSTOM_COURSE_ID_MAX - (PERFECT_CHALLENGE_COURSE_COUNT - 1)
    for base in range(CUSTOM_COURSE_ID_MIN, hi + 1):
        if all((base + k) not in used for k in range(PERFECT_CHALLENGE_COURSE_COUNT)):
            return base
    raise ValueError("310000～319999 内已无连续 5 个空闲课题 ID，请清理旧自制课题。")


def _used_custom_reward_ids(acus_root: Path) -> set[int]:
    used: set[int] = set()
    rw = acus_root / "reward"
    if not rw.is_dir():
        return used
    for p in rw.glob("reward*/Reward.xml"):
        try:
            r = ET.parse(p).getroot()
            id_el = r.find("name/id")
            if id_el is not None and (id_el.text or "").strip().isdigit():
                v = int(id_el.text.strip())
                if CUSTOM_REWARD_ID_MIN <= v <= CUSTOM_REWARD_ID_MAX:
                    used.add(v)
        except Exception:
            continue
    return used


def next_custom_unlock_reward_id(acus_root: Path) -> int:
    """自制解锁挑战用乐曲奖励 ID：200000000～299999999（避开官方 07* 等区间）。"""
    used = _used_custom_reward_ids(acus_root)
    cur = CUSTOM_REWARD_ID_MIN
    while cur <= CUSTOM_REWARD_ID_MAX and cur in used:
        cur += 1
    if cur > CUSTOM_REWARD_ID_MAX:
        raise ValueError("自制 reward ID 区间 2xxxxxxxxx 已用尽。")
    return cur


def reward_dir_name(reward_id: int) -> str:
    return f"reward{int(reward_id):09d}"


def write_music_unlock_reward_xml(
    *,
    acus_root: Path,
    reward_id: int,
    music_id: int,
    music_title: str,
) -> Path:
    """与 A001 reward040002705 同结构：substances/type=6，发放乐曲本体。"""
    esc_n = _xml_esc(music_title.strip())
    r9 = reward_dir_name(reward_id)
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<RewardData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>{r9}</dataName>
  <name>
    <id>{int(reward_id)}</id>
    <str>{esc_n}</str>
    <data />
  </name>
  <substances>
    <list>
      <RewardSubstanceData>
        <type>6</type>
        <gamePoint>
          <gamePoint>0</gamePoint>
        </gamePoint>
        <ticket>
          <ticketName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </ticketName>
        </ticket>
        <trophy>
          <trophyName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </trophyName>
        </trophy>
        <chara>
          <charaName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </charaName>
        </chara>
        <skillSeed>
          <skillSeedName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </skillSeedName>
          <skillSeedCount>1</skillSeedCount>
        </skillSeed>
        <namePlate>
          <namePlateName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </namePlateName>
        </namePlate>
        <music>
          <musicName>
            <id>{int(music_id)}</id>
            <str>{esc_n}</str>
            <data />
          </musicName>
        </music>
        <mapIcon>
          <mapIconName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </mapIconName>
        </mapIcon>
        <systemVoice>
          <systemVoiceName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </systemVoiceName>
        </systemVoice>
        <avatarAccessory>
          <avatarAccessoryName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </avatarAccessoryName>
        </avatarAccessory>
        <frame>
          <frameName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </frameName>
        </frame>
        <symbolChat>
          <symbolChatName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </symbolChatName>
        </symbolChat>
        <ultimaScore>
          <musicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicName>
        </ultimaScore>
      </RewardSubstanceData>
    </list>
  </substances>
</RewardData>
"""
    rdir = acus_root / "reward" / r9
    rdir.mkdir(parents=True, exist_ok=True)
    out = rdir / "Reward.xml"
    out.write_text(xml, encoding="utf-8", newline="\n")
    return out


def _course_music_block(
    music_id: int,
    music_title: str,
    diff_id: int,
    diff_str: str,
    diff_data: str,
) -> str:
    esc_m = _xml_esc(music_title.strip())
    esc_ds = _xml_esc(diff_str)
    esc_dd = _xml_esc(diff_data)
    return f"""    <CourseMusicDataInfo>
      <type>0</type>
      <selectMusic>
        <musicName>
          <id>{int(music_id)}</id>
          <str>{esc_m}</str>
          <data />
        </musicName>
        <musicDiff>
          <id>{int(diff_id)}</id>
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


def write_perfect_challenge_course_xml(
    *,
    acus_root: Path,
    course_id: int,
    course_suffix_label: str,
    music_id: int,
    music_title: str,
    release_tag_id: int,
    release_tag_str: str,
    net_open_id: int,
    net_open_str: str,
    reward_id: int,
    reward_title: str,
    diff_id: int,
    diff_str: str,
    diff_data: str,
) -> Path:
    """与 A001 course00300005 一致结构；reward2nd 为无。"""
    esc_cn = _xml_esc(course_suffix_label)
    esc_m = _xml_esc(music_title.strip())
    esc_rt = _xml_esc(release_tag_str.strip() or "Invalid")
    esc_no = _xml_esc(net_open_str.strip() or "v2_45 00_1")
    esc_rw = _xml_esc(reward_title.strip() or music_title.strip())
    c8 = f"{int(course_id):08d}"
    infos_body = "\n".join(
        _course_music_block(music_id, music_title, diff_id, diff_str, diff_data)
        for _ in range(COURSE_INFO_SLOTS)
    )
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<CourseData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>course{c8}</dataName>
  <releaseTagName>
    <id>{int(release_tag_id)}</id>
    <str>{esc_rt}</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>{int(net_open_id)}</id>
    <str>{esc_no}</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{int(course_id)}</id>
    <str>{esc_cn}</str>
    <data />
  </name>
  <difficulty>
    <id>14</id>
    <str>ID_14</str>
    <data>CLASS Ⅴ</data>
  </difficulty>
  <rule>
    <id>2000</id>
    <str>2000</str>
    <data />
  </rule>
  <reward>
    <id>{int(reward_id)}</id>
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
    return out


def append_course_sort(acus_root: Path, course_ids: list[int]) -> None:
    sort_path = acus_root / "course" / "CourseSort.xml"
    if not sort_path.exists():
        sort_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>course</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
""",
            encoding="utf-8",
        )
    root = ET.parse(sort_path).getroot()
    sl = root.find("SortList")
    if sl is None:
        return
    existing: set[int] = set()
    for n in sl.findall("StringID/id"):
        v = _safe_int(n.text)
        if v is not None:
            existing.add(v)
    for cid in course_ids:
        if cid in existing:
            continue
        s = ET.SubElement(sl, "StringID")
        ET.SubElement(s, "id").text = str(int(cid))
        ET.SubElement(s, "str")
        ET.SubElement(s, "data")
        existing.add(cid)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


def find_courses_for_music(acus_root: Path, music_id: int) -> list[tuple[int, str]]:
    """扫描已有课题是否引用该曲（供只读展示或迁移用）。"""
    found: dict[int, str] = {}
    root = acus_root / "course"
    if not root.is_dir():
        return []
    for p in sorted(root.glob("course*/Course.xml")):
        try:
            r = ET.parse(p).getroot()
            mids = r.findall(".//selectMusic/musicName/id")
            ok = False
            for el in mids:
                t = (el.text or "").strip()
                if t.isdigit() and int(t) == int(music_id):
                    ok = True
                    break
            if not ok:
                continue
            name_el = r.find("name")
            if name_el is None:
                continue
            id_el = name_el.find("id")
            str_el = name_el.find("str")
            if id_el is None or str_el is None:
                continue
            cid = int((id_el.text or "").strip())
            cstr = (str_el.text or "").strip()
            found[cid] = cstr
        except Exception:
            continue
    return sorted(found.items(), key=lambda x: x[0])


def next_unlock_challenge_id(acus_root: Path, *, start: int = 90_001) -> int:
    used: set[int] = set()
    uc_root = acus_root / "unlockChallenge"
    if uc_root.is_dir():
        for p in uc_root.glob("unlockChallenge*"):
            if not p.is_dir():
                continue
            suf = p.name[len("unlockChallenge") :]
            if suf.isdigit():
                used.add(int(suf))
        sort_path = uc_root / "UnlockChallengeSort.xml"
        if sort_path.exists():
            try:
                root = ET.parse(sort_path).getroot()
                for n in root.findall("./SortList/StringID/id"):
                    v = _safe_int(n.text)
                    if v is not None:
                        used.add(v)
            except Exception:
                pass
    cur = max(start, 1)
    while cur in used:
        cur += 1
    return cur


def append_unlock_challenge_sort(acus_root: Path, challenge_id: int) -> None:
    sort_path = acus_root / "unlockChallenge" / "UnlockChallengeSort.xml"
    sort_path.parent.mkdir(parents=True, exist_ok=True)
    if not sort_path.exists():
        sort_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>unlockChallenge</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
""",
            encoding="utf-8",
        )
    root = ET.parse(sort_path).getroot()
    sl = root.find("SortList")
    if sl is None:
        return
    for n in sl.findall("StringID/id"):
        if _safe_int(n.text) == challenge_id:
            ET.indent(root, space="  ")
            ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)
            return
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(challenge_id)
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


def write_unlock_challenge_xml(
    *,
    acus_root: Path,
    challenge_id: int,
    challenge_title: str,
    music_id: int,
    music_title: str,
    net_open_id: int,
    net_open_str: str,
    courses: list[tuple[int, str]],
    reward_id: int,
    reward_title: str,
) -> Path:
    if len(courses) != PERFECT_CHALLENGE_COURSE_COUNT:
        raise ValueError(f"课题列表须为 {PERFECT_CHALLENGE_COURSE_COUNT} 条。")
    esc_title = _xml_esc(challenge_title.strip() or music_title)
    esc_music = _xml_esc(music_title.strip())
    esc_no = _xml_esc(net_open_str.strip() or "v2_45 00_1")
    esc_rw = _xml_esc(reward_title.strip() or music_title.strip())

    course_blocks: list[str] = []
    for cid, cstr in courses:
        cs = _xml_esc(cstr.strip() or str(cid))
        course_blocks.append(
            f"""              <UnlockChallengeCourseListSubData>
                <type>0</type>
                <unlockChallengeCourseData>
                  <courseName>
                    <id>{int(cid)}</id>
                    <str>{cs}</str>
                    <data />
                  </courseName>
                </unlockChallengeCourseData>
              </UnlockChallengeCourseListSubData>"""
        )
    courses_xml = "\n".join(course_blocks)

    row = f"{int(challenge_id):08d}"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<UnlockChallengeData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>unlockChallenge{row}</dataName>
  <netOpenName>
    <id>{int(net_open_id)}</id>
    <str>{esc_no}</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{int(challenge_id)}</id>
    <str>{esc_title}</str>
    <data />
  </name>
  <musicList>
    <list>
      <UnlockChallengeMusicListSubData>
        <type>0</type>
        <unlockChallengeMusicData>
          <name>
            <id>{int(music_id)}</id>
            <str>{esc_music}</str>
            <data />
          </name>
          <rewardList>
            <list>
              <UnlockChallengeRewardListSubData>
                <type>0</type>
                <unlockChallengeRewardData>
                  <rewardName>
                    <id>{int(reward_id)}</id>
                    <str>{esc_rw}</str>
                    <data />
                  </rewardName>
                  <rewardNum>1</rewardNum>
                </unlockChallengeRewardData>
              </UnlockChallengeRewardListSubData>
            </list>
          </rewardList>
          <courseList>
            <list>
{courses_xml}
            </list>
          </courseList>
        </unlockChallengeMusicData>
      </UnlockChallengeMusicListSubData>
    </list>
  </musicList>
</UnlockChallengeData>
"""
    udir = acus_root / "unlockChallenge" / f"unlockChallenge{row}"
    udir.mkdir(parents=True, exist_ok=True)
    out = udir / "UnlockChallenge.xml"
    out.write_text(xml, encoding="utf-8", newline="\n")
    return out


def write_unlock_challenge_event_xml(
    *,
    acus_root: Path,
    event_id: int,
    event_title: str,
    challenge_id: int,
    challenge_str: str,
    net_open_id: int,
    net_open_str: str,
) -> Path:
    esc_ev = _xml_esc(event_title.strip())
    esc_uc = _xml_esc(challenge_str.strip())
    esc_no = _xml_esc(net_open_str.strip() or "v2_45 00_1")
    e8 = f"{int(event_id):08d}"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<EventData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>event{e8}</dataName>
  <netOpenName>
    <id>{int(net_open_id)}</id>
    <str>{esc_no}</str>
    <data />
  </netOpenName>
  <name>
    <id>{int(event_id)}</id>
    <str>{esc_ev}</str>
    <data />
  </name>
  <text />
  <ddsBannerName>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </ddsBannerName>
  <periodDispType>1</periodDispType>
  <alwaysOpen>true</alwaysOpen>
  <teamOnly>false</teamOnly>
  <isKop>false</isKop>
  <priority>0</priority>
  <substances>
    <type>16</type>
    <flag>
      <value>0</value>
    </flag>
    <information>
      <informationType>0</informationType>
      <informationDispType>0</informationDispType>
      <mapFilterID>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </mapFilterID>
      <courseNames>
        <list />
      </courseNames>
      <text />
      <image>
        <path />
      </image>
      <movieName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </movieName>
      <presentNames>
        <list />
      </presentNames>
    </information>
    <map>
      <tagText />
      <mapName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </mapName>
      <musicNames>
        <list />
      </musicNames>
    </map>
    <music>
      <musicType>0</musicType>
      <musicNames>
        <list />
      </musicNames>
    </music>
    <advertiseMovie>
      <firstMovieName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </firstMovieName>
      <secondMovieName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </secondMovieName>
    </advertiseMovie>
    <recommendMusic>
      <musicNames>
        <list />
      </musicNames>
    </recommendMusic>
    <release>
      <value>0</value>
    </release>
    <course>
      <courseNames>
        <list />
      </courseNames>
    </course>
    <quest>
      <questNames>
        <list />
      </questNames>
    </quest>
    <duel>
      <duelName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </duelName>
    </duel>
    <cmission>
      <cmissionName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </cmissionName>
    </cmission>
    <changeSurfBoardUI>
      <value>0</value>
    </changeSurfBoardUI>
    <avatarAccessoryGacha>
      <avatarAccessoryGachaName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </avatarAccessoryGachaName>
    </avatarAccessoryGacha>
    <rightsInfo>
      <rightsNames>
        <list />
      </rightsNames>
    </rightsInfo>
    <playRewardSet>
      <playRewardSetName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </playRewardSetName>
    </playRewardSet>
    <dailyBonusPreset>
      <dailyBonusPresetName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </dailyBonusPresetName>
    </dailyBonusPreset>
    <matchingBonus>
      <timeTableName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </timeTableName>
    </matchingBonus>
    <unlockChallenge>
      <unlockChallengeName>
        <id>{int(challenge_id)}</id>
        <str>{esc_uc}</str>
        <data />
      </unlockChallengeName>
    </unlockChallenge>
  </substances>
</EventData>
"""
    edir = acus_root / "event" / f"event{e8}"
    edir.mkdir(parents=True, exist_ok=True)
    out = edir / "Event.xml"
    out.write_text(xml, encoding="utf-8", newline="\n")
    return out


def _append_event_sort(acus_root: Path, event_id: int) -> None:
    sort_path = acus_root / "event" / "EventSort.xml"
    if not sort_path.exists():
        sort_path.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>event</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
""",
            encoding="utf-8",
        )
    root = ET.parse(sort_path).getroot()
    sl = root.find("SortList")
    if sl is None:
        return
    for n in sl.findall("StringID/id"):
        if _safe_int(n.text) == event_id:
            ET.indent(root, space="  ")
            ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)
            return
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(event_id)
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(sort_path, encoding="utf-8", xml_declaration=True)


def create_unlock_challenge_bundle(
    *,
    acus_root: Path,
    item: MusicItem,
    challenge_title: str,
    event_title: str,
    event_id: int | None,
    next_event_id_fn,
) -> tuple[Path, Path, int, int, int]:
    """
    写入 Reward(2xxxxxxxxx) + 5×Course(31xxxx) + CourseSort + UnlockChallenge + Event。
    返回 (challenge_xml, event_xml, challenge_id, event_id, reward_id)。
    """
    no_id, no_s = read_music_net_open(item.xml_path)
    rt_id, rt_s = read_music_release_tag(item.xml_path)
    diffs = read_enabled_fumen_diffs(item.xml_path)

    reward_id = next_custom_unlock_reward_id(acus_root)
    write_music_unlock_reward_xml(
        acus_root=acus_root,
        reward_id=reward_id,
        music_id=item.name.id,
        music_title=item.name.str,
    )

    base_course = next_perfect_challenge_course_base_id(acus_root)
    courses: list[tuple[int, str]] = []
    ch_name = challenge_title.strip() or item.name.str
    for i in range(PERFECT_CHALLENGE_COURSE_COUNT):
        cid = base_course + i
        suffix = f"{ch_name}-{i + 1}"
        d_id, d_s, d_d = pick_diff_for_course_index(diffs, i)
        write_perfect_challenge_course_xml(
            acus_root=acus_root,
            course_id=cid,
            course_suffix_label=suffix,
            music_id=item.name.id,
            music_title=item.name.str,
            release_tag_id=rt_id,
            release_tag_str=rt_s,
            net_open_id=no_id,
            net_open_str=no_s,
            reward_id=reward_id,
            reward_title=item.name.str,
            diff_id=d_id,
            diff_str=d_s,
            diff_data=d_d,
        )
        courses.append((cid, suffix))

    append_course_sort(acus_root, [c[0] for c in courses])

    ch_id = next_unlock_challenge_id(acus_root)
    write_unlock_challenge_xml(
        acus_root=acus_root,
        challenge_id=ch_id,
        challenge_title=ch_name,
        music_id=item.name.id,
        music_title=item.name.str,
        net_open_id=no_id,
        net_open_str=no_s,
        courses=courses,
        reward_id=reward_id,
        reward_title=item.name.str,
    )
    append_unlock_challenge_sort(acus_root, ch_id)

    eid = int(event_id) if event_id is not None else int(next_event_id_fn(acus_root))
    ev_title = event_title.strip() or f"【Unlock】{item.name.str}"
    ev_path = write_unlock_challenge_event_xml(
        acus_root=acus_root,
        event_id=eid,
        event_title=ev_title,
        challenge_id=ch_id,
        challenge_str=ch_name,
        net_open_id=no_id,
        net_open_str=no_s,
    )
    _append_event_sort(acus_root, eid)
    c8 = f"{ch_id:08d}"
    return (
        acus_root / "unlockChallenge" / f"unlockChallenge{c8}" / "UnlockChallenge.xml",
        ev_path,
        ch_id,
        eid,
        reward_id,
    )
