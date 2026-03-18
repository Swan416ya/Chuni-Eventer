from __future__ import annotations

from pathlib import Path


def write_ddsimage_xml(*, out_dir: Path, chara_id: int, net_open_id: int = 2801, net_open_str: str = "v2_45 00_1") -> Path:
    """
    Writes:
      out_dir/ddsImage/ddsImage{ID6}/DDSImage.xml

    Matches A001 schema:
      <DDSImageData> with name.id = chara_id, name.str = chara{base4}_{variant2}
      ddsFile0/1/2 paths = CHU_UI_Character_{base4}_{variant2}_{00..02}.dds
    """
    from .chuni_formats import ChuniCharaId

    cid = ChuniCharaId(int(chara_id))
    dds_dir = out_dir / "ddsImage" / f"ddsImage{cid.raw6}"
    dds_dir.mkdir(parents=True, exist_ok=True)
    xml_path = dds_dir / "DDSImage.xml"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DDSImageData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>ddsImage{cid.raw6}</dataName>
  <name>
    <id>{cid.raw}</id>
    <str>{cid.chara_key}</str>
    <data />
  </name>
  <ddsFile0>
    <path>{cid.dds_filename(0)}</path>
  </ddsFile0>
  <ddsFile1>
    <path>{cid.dds_filename(1)}</path>
  </ddsFile1>
  <ddsFile2>
    <path>{cid.dds_filename(2)}</path>
  </ddsFile2>
  <netOpenName>
    <id>{net_open_id}</id>
    <str>{net_open_str}</str>
    <data />
  </netOpenName>
</DDSImageData>
"""
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path


def write_chara_xml(
    *,
    out_dir: Path,
    chara_id: int,
    chara_name: str,
    release_tag_id: int = 20,
    release_tag_str: str = "v2 2.45.00",
    net_open_id: int = 2801,
    net_open_str: str = "v2_45 00_1",
) -> Path:
    """
    Writes:
      out_dir/chara/chara{ID6}/Chara.xml

    Minimal-ish CharaData for tooling purposes (mirrors fields used in A001).
    defaultImages references {chara_key} (which in turn maps to ddsImage name.str).
    """
    from .chuni_formats import ChuniCharaId

    cid = ChuniCharaId(int(chara_id))
    chara_dir = out_dir / "chara" / f"chara{cid.raw6}"
    chara_dir.mkdir(parents=True, exist_ok=True)
    xml_path = chara_dir / "Chara.xml"

    safe_name = (chara_name or "").strip() or f"EX_CHARA_{cid.raw}"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<CharaData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>chara{cid.raw6}</dataName>
  <releaseTagName>
    <id>{release_tag_id}</id>
    <str>{release_tag_str}</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>{net_open_id}</id>
    <str>{net_open_str}</str>
    <data />
  </netOpenName>
  <disableFlag>false</disableFlag>
  <name>
    <id>{cid.raw}</id>
    <str>{safe_name}</str>
    <data />
  </name>
  <explainText />
  <sortName>{cid.chara_key}</sortName>
  <works>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </works>
  <illustratorName>
    <id>-1</id>
    <str>Invalid</str>
    <data />
  </illustratorName>
  <defaultHave>false</defaultHave>
  <rareType>0</rareType>
  <normCondition>
    <conditions />
  </normCondition>
  <ranking>false</ranking>
  <defaultImages>
    <id>{cid.raw}</id>
    <str>{cid.chara_key}</str>
    <data />
  </defaultImages>
  <addImages1>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages1>
  <addImages2>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages2>
  <addImages3>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages3>
  <addImages4>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages4>
  <addImages5>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages5>
  <addImages6>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages6>
  <addImages7>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages7>
  <addImages8>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages8>
  <addImages9>
    <changeImg>false</changeImg>
    <charaName>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </charaName>
    <image>
      <id>-1</id>
      <str>Invalid</str>
      <data />
    </image>
    <rank>1</rank>
  </addImages9>
  <priority>0</priority>
  <ranks>
    <CharaRankData>
      <index>1</index>
      <type>1</type>
      <rewardSkillSeed>
        <rewardSkillSeed>
          <id>-1</id>
          <str>Invalid</str>
          <data />
        </rewardSkillSeed>
      </rewardSkillSeed>
      <text>
        <flavorTxtFile>
          <path />
        </flavorTxtFile>
      </text>
    </CharaRankData>
  </ranks>
</CharaData>
"""
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path

