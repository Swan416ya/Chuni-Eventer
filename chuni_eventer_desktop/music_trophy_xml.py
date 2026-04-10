from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def next_trophy_id(acus_root: Path) -> int:
    # 自制称号号段：50000+
    m = 49_999
    for p in acus_root.glob("trophy/**/Trophy.xml"):
        try:
            raw = ET.parse(p).getroot().findtext("name/id")
            if raw and raw.strip().isdigit():
                m = max(m, int(raw.strip()))
        except Exception:
            continue
    return m + 1


# type=3 子条件：与 A001 trophy009757 第二段一致（ALL JUSTICE）
_COND_TYPE3 = """      <ConditionSubData>
        <type>3</type>
        <eventData>
          <eventNames>
            <list />
          </eventNames>
        </eventData>
        <playMusicData>
          <genreNames>
            <list />
          </genreNames>
          <musicNames>
            <list />
          </musicNames>
          <musicDif>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicDif>
        </playMusicData>
        <playSettingData>
          <playOptionSpeed>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionSpeed>
          <playOptionFieldWallPosition>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionFieldWallPosition>
          <playOptionMirror>false</playOptionMirror>
        </playSettingData>
        <playMusicResultData>
          <memberNum>0</memberNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <matchingResultType>0</matchingResultType>
          <memberRanking>0</memberRanking>
          <gameOver>false</gameOver>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>true</allJustice>
          <memberOtherTrophyName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </memberOtherTrophyName>
          <missNum>0</missNum>
          <maxComboNum>0</maxComboNum>
        </playMusicResultData>
        <playTotalResultData>
          <allPlayedMusicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </allPlayedMusicName>
        </playTotalResultData>
        <personData>
          <playerRebirthCount>0</playerRebirthCount>
          <playerLv>0</playerLv>
          <playerRating>0</playerRating>
          <totalGamePoint>0</totalGamePoint>
          <totalNetBattle>0</totalNetBattle>
          <battleRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </battleRank>
        </personData>
        <charaData>
          <targetRank>0</targetRank>
          <charaName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </charaName>
        </charaData>
        <skillData>
          <lvMax>false</lvMax>
        </skillData>
        <trophyData>
          <haveTrophyNames>
            <list />
          </haveTrophyNames>
        </trophyData>
        <travelData>
          <japanRegionID>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </japanRegionID>
          <japanRegionPlayNum>0</japanRegionPlayNum>
          <playedRegionNum>0</playedRegionNum>
          <lapNum>0</lapNum>
        </travelData>
        <musicData>
          <musicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicName>
          <musicDif>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicDif>
          <masterUnderAll>false</masterUnderAll>
          <totalPlayNum>0</totalPlayNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>false</allJustice>
          <playNum>0</playNum>
        </musicData>
        <completeData>
          <releaseTagName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </releaseTagName>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <allJustice>false</allJustice>
        </completeData>
      </ConditionSubData>"""


def _cond_type1_play_clear(music_id: int, music_name_x: str, dif_id: int, dif_str: str, dif_data: str) -> str:
    return f"""      <ConditionSubData>
        <type>1</type>
        <eventData>
          <eventNames>
            <list />
          </eventNames>
        </eventData>
        <playMusicData>
          <genreNames>
            <list />
          </genreNames>
          <musicNames>
            <list>
              <StringID>
                <id>{music_id}</id>
                <str>{music_name_x}</str>
                <data />
              </StringID>
            </list>
          </musicNames>
          <musicDif>
            <id>{dif_id}</id>
            <str>{dif_str}</str>
            <data>{dif_data}</data>
          </musicDif>
        </playMusicData>
        <playSettingData>
          <playOptionSpeed>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionSpeed>
          <playOptionFieldWallPosition>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionFieldWallPosition>
          <playOptionMirror>false</playOptionMirror>
        </playSettingData>
        <playMusicResultData>
          <memberNum>0</memberNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <matchingResultType>0</matchingResultType>
          <memberRanking>0</memberRanking>
          <gameOver>false</gameOver>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>false</allJustice>
          <memberOtherTrophyName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </memberOtherTrophyName>
          <missNum>0</missNum>
          <maxComboNum>0</maxComboNum>
        </playMusicResultData>
        <playTotalResultData>
          <allPlayedMusicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </allPlayedMusicName>
        </playTotalResultData>
        <personData>
          <playerRebirthCount>0</playerRebirthCount>
          <playerLv>0</playerLv>
          <playerRating>0</playerRating>
          <totalGamePoint>0</totalGamePoint>
          <totalNetBattle>0</totalNetBattle>
          <battleRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </battleRank>
        </personData>
        <charaData>
          <targetRank>0</targetRank>
          <charaName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </charaName>
        </charaData>
        <skillData>
          <lvMax>false</lvMax>
        </skillData>
        <trophyData>
          <haveTrophyNames>
            <list />
          </haveTrophyNames>
        </trophyData>
        <travelData>
          <japanRegionID>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </japanRegionID>
          <japanRegionPlayNum>0</japanRegionPlayNum>
          <playedRegionNum>0</playedRegionNum>
          <lapNum>0</lapNum>
        </travelData>
        <musicData>
          <musicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicName>
          <musicDif>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicDif>
          <masterUnderAll>false</masterUnderAll>
          <totalPlayNum>0</totalPlayNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>false</allJustice>
          <playNum>0</playNum>
        </musicData>
        <completeData>
          <releaseTagName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </releaseTagName>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <allJustice>false</allJustice>
        </completeData>
      </ConditionSubData>"""


def _cond_type10_ultima_aj(music_id: int, music_name_x: str) -> str:
    return f"""      <ConditionSubData>
        <type>10</type>
        <eventData>
          <eventNames>
            <list />
          </eventNames>
        </eventData>
        <playMusicData>
          <genreNames>
            <list />
          </genreNames>
          <musicNames>
            <list />
          </musicNames>
          <musicDif>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </musicDif>
        </playMusicData>
        <playSettingData>
          <playOptionSpeed>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionSpeed>
          <playOptionFieldWallPosition>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </playOptionFieldWallPosition>
          <playOptionMirror>false</playOptionMirror>
        </playSettingData>
        <playMusicResultData>
          <memberNum>0</memberNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <matchingResultType>0</matchingResultType>
          <memberRanking>0</memberRanking>
          <gameOver>false</gameOver>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>false</allJustice>
          <memberOtherTrophyName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </memberOtherTrophyName>
          <missNum>0</missNum>
          <maxComboNum>0</maxComboNum>
        </playMusicResultData>
        <playTotalResultData>
          <allPlayedMusicName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </allPlayedMusicName>
        </playTotalResultData>
        <personData>
          <playerRebirthCount>0</playerRebirthCount>
          <playerLv>0</playerLv>
          <playerRating>0</playerRating>
          <totalGamePoint>0</totalGamePoint>
          <totalNetBattle>0</totalNetBattle>
          <battleRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </battleRank>
        </personData>
        <charaData>
          <targetRank>0</targetRank>
          <charaName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </charaName>
        </charaData>
        <skillData>
          <lvMax>false</lvMax>
        </skillData>
        <trophyData>
          <haveTrophyNames>
            <list />
          </haveTrophyNames>
        </trophyData>
        <travelData>
          <japanRegionID>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </japanRegionID>
          <japanRegionPlayNum>0</japanRegionPlayNum>
          <playedRegionNum>0</playedRegionNum>
          <lapNum>0</lapNum>
        </travelData>
        <musicData>
          <musicName>
            <id>{music_id}</id>
            <str>{music_name_x}</str>
            <data />
          </musicName>
          <musicDif>
            <id>4</id>
            <str>Ultima</str>
            <data>ULTIMA</data>
          </musicDif>
          <masterUnderAll>false</masterUnderAll>
          <totalPlayNum>0</totalPlayNum>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <fullCombo>false</fullCombo>
          <fullChain>false</fullChain>
          <allJustice>true</allJustice>
          <playNum>0</playNum>
        </musicData>
        <completeData>
          <releaseTagName>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </releaseTagName>
          <scoreRank>
            <id>-1</id>
            <str>Invalid</str>
            <data />
          </scoreRank>
          <allJustice>false</allJustice>
        </completeData>
      </ConditionSubData>"""


def build_expert_gold_trophy_xml(*, trophy_id: int, music_id: int, display_name: str) -> str:
    nx = xml_escape(display_name)
    explain = xml_escape(f"{display_name}/EXPERT/ALL JUSTICE達成")
    c1 = _cond_type1_play_clear(music_id, nx, 2, "Expert", "EXPERT")
    inner = f"{c1}\n{_COND_TYPE3}"
    return _trophy_shell(trophy_id, nx, explain, 4, inner)


def build_master_platinum_trophy_xml(*, trophy_id: int, music_id: int, display_name: str) -> str:
    nx = xml_escape(display_name)
    explain = xml_escape(f"{display_name}/MASTER/ALL JUSTICE達成")
    c1 = _cond_type1_play_clear(music_id, nx, 3, "Master", "MASTER")
    inner = f"{c1}\n{_COND_TYPE3}"
    return _trophy_shell(trophy_id, nx, explain, 6, inner)


def build_ultima_trophy_xml(*, trophy_id: int, music_id: int, display_name: str) -> str:
    nx = xml_escape(display_name)
    explain = xml_escape(f"{display_name}/ULTIMA/ALL JUSTICE達成")
    inner = _cond_type10_ultima_aj(music_id, nx)
    return _trophy_shell(trophy_id, nx, explain, 8, inner)


def _trophy_shell(trophy_id: int, name_x: str, explain_x: str, rare: int, conditions_inner: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<TrophyData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>trophy{trophy_id:06d}</dataName>
  <netOpenName>
    <id>2801</id>
    <str>v2_45 00_1</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{trophy_id}</id>
    <str>{name_x}</str>
    <data />
  </name>
  <explainText>{explain_x}</explainText>
  <defaultHave>false</defaultHave>
  <rareType>{rare}</rareType>
  <image>
    <path />
  </image>
  <normCondition>
    <conditions>
{conditions_inner}
    </conditions>
  </normCondition>
  <priority>0</priority>
</TrophyData>
"""


def write_trophy_file(acus_root: Path, trophy_id: int, xml_body: str) -> Path:
    tdir = acus_root / "trophy" / f"trophy{trophy_id:06d}"
    tdir.mkdir(parents=True, exist_ok=True)
    out = tdir / "Trophy.xml"
    out.write_text(xml_body, encoding="utf-8")
    return out
