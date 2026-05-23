"""
段位组曲在游戏内显示需 ``Event`` type=7（コース開放）登记 courseNames。

参考 A001 ``event00018065``；保存自制段位组曲时维护一条 alwaysOpen 的开锁事件。
"""
from __future__ import annotations

from pathlib import Path

from .course_rank import CUSTOM_RANK_COURSE_ID_MIN, scan_rank_courses

CUSTOM_RANK_COURSE_UNLOCK_EVENT_ID = 70007
CUSTOM_RANK_COURSE_UNLOCK_EVENT_TITLE = "【Custom】段位组曲开放"


def _xml_esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _course_unlock_entries(acus_root: Path) -> list[tuple[int, str]]:
    entries: list[tuple[int, str]] = []
    for item in scan_rank_courses(acus_root):
        if item.name.id < CUSTOM_RANK_COURSE_ID_MIN:
            continue
        entries.append((item.name.id, item.name.str.strip() or f"Course{item.name.id}"))
    entries.sort(key=lambda x: x[0])
    return entries


def _course_name_blocks(entries: list[tuple[int, str]]) -> str:
    blocks: list[str] = []
    for cid, cstr in entries:
        esc = _xml_esc(cstr)
        blocks.append(
            f"""          <StringID>
            <id>{int(cid)}</id>
            <str>{esc}</str>
            <data />
          </StringID>"""
        )
    return "\n".join(blocks)


def write_rank_course_unlock_event(
    *,
    acus_root: Path,
    net_open_id: int = 2801,
    net_open_str: str = "v2_45 00_1",
) -> Path | None:
    """
    写入/更新 type=7 课题开锁 Event。
    若无 ≥490000 的自制段位组曲则跳过。
    """
    entries = _course_unlock_entries(acus_root)
    if not entries:
        return None

    eid = CUSTOM_RANK_COURSE_UNLOCK_EVENT_ID
    e8 = f"{int(eid):08d}"
    esc_title = _xml_esc(CUSTOM_RANK_COURSE_UNLOCK_EVENT_TITLE)
    esc_no = _xml_esc(net_open_str.strip() or "v2_45 00_1")
    courses_xml = _course_name_blocks(entries)

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<EventData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>event{e8}</dataName>
  <netOpenName>
    <id>{int(net_open_id)}</id>
    <str>{esc_no}</str>
    <data />
  </netOpenName>
  <name>
    <id>{int(eid)}</id>
    <str>{esc_title}</str>
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
    <type>7</type>
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
        <list>
{courses_xml}
        </list>
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
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </unlockChallengeName>
    </unlockChallenge>
    <linkedVerse>
      <linkedVerseName>
        <id>-1</id>
        <str>Invalid</str>
        <data />
      </linkedVerseName>
    </linkedVerse>
  </substances>
</EventData>
"""
    edir = acus_root / "event" / f"event{e8}"
    edir.mkdir(parents=True, exist_ok=True)
    out = edir / "Event.xml"
    out.write_text(xml, encoding="utf-8", newline="\n")
    return out


def sync_rank_course_unlock_event(acus_root: Path, *, net_open_id: int, net_open_str: str) -> Path | None:
    return write_rank_course_unlock_event(
        acus_root=acus_root,
        net_open_id=net_open_id,
        net_open_str=net_open_str,
    )
