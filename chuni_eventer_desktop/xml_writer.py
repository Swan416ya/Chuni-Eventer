from __future__ import annotations

from pathlib import Path


def write_ddsimage_xml(*, out_dir: Path, chara_id: int, net_open_id: int = 2801, net_open_str: str = "v2_45 00_1") -> Path:
    """
    Writes:
      out_dir/ddsImage/ddsImage{ID6}/DDSImage.xml

    Matches A001 schema:
      <DDSImageData> with name.id = chara_id, name.str = chara{base4}_{variant2}
      ddsFile0/1/2 = 全身/半身/大头 → CHU_UI_Character_{base4}_{variant2}_{00..02}.dds
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


def _works_sort_name(works_str: str, works_id: int) -> str:
    """与 A001 CharaWorks 中 sortName 类似：优先拉丁/数字大写拼接，否则用显示名原文。"""
    raw = (works_str or "").strip()
    if not raw:
        return f"WORKS{works_id}"
    ascii_part = "".join(c.upper() for c in raw if ("A" <= c <= "Z") or ("a" <= c <= "z") or c.isdigit())
    return ascii_part if ascii_part else raw


def write_chara_works_xml(
    *,
    out_dir: Path,
    works_id: int,
    works_str: str,
    release_tag_id: int = -1,
    release_tag_str: str = "Invalid",
    net_open_id: int = 2801,
    net_open_str: str = "v2_45 00_1",
) -> Path:
    """
    写入游戏可识别的作品主数据（与 A001 charaWorks/charaWorksXXXXXX/CharaWorks.xml 一致）。
    Chara.xml 的 works/id 须与本文件 name/id 一致。
    """
    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    wid = int(works_id)
    if wid < 0:
        raise ValueError("works_id 须为非负整数")
    row = f"{wid:06d}"
    safe_works = _esc((works_str or "").strip() or f"Works{wid}")
    rt_str = _esc((release_tag_str or "").strip() or "Invalid")
    no_str = _esc((net_open_str or "").strip() or "v2_45 00_1")
    sort_sn = _esc(_works_sort_name(works_str, wid))

    wdir = out_dir / "charaWorks" / f"charaWorks{row}"
    wdir.mkdir(parents=True, exist_ok=True)
    xml_path = wdir / "CharaWorks.xml"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<CharaWorksData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>charaWorks{row}</dataName>
  <releaseTagName>
    <id>{int(release_tag_id)}</id>
    <str>{rt_str}</str>
    <data />
  </releaseTagName>
  <netOpenName>
    <id>{int(net_open_id)}</id>
    <str>{no_str}</str>
    <data />
  </netOpenName>
  <name>
    <id>{wid}</id>
    <str>{safe_works}</str>
    <data />
  </name>
  <sortName>{sort_sn}</sortName>
  <priority>0</priority>
  <ranks />
</CharaWorksData>
"""
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path


def ensure_chara_works_xml(
    *,
    out_dir: Path,
    works_id: int,
    works_str: str,
    release_tag_id: int = -1,
    release_tag_str: str = "Invalid",
    net_open_id: int = 2801,
    net_open_str: str = "v2_45 00_1",
) -> Path | None:
    """
    若 works 有效则写入/覆盖 charaWorks；否则跳过（与 Chara 中 -1/Invalid 一致）。
    """
    if int(works_id) < 0:
        return None
    ws = (works_str or "").strip()
    if not ws or ws == "Invalid":
        return None
    return write_chara_works_xml(
        out_dir=out_dir,
        works_id=int(works_id),
        works_str=ws,
        release_tag_id=release_tag_id,
        release_tag_str=release_tag_str,
        net_open_id=net_open_id,
        net_open_str=net_open_str,
    )


def write_chara_xml(
    *,
    out_dir: Path,
    chara_id: int,
    chara_name: str,
    illustrator_name: str | None = None,
    illustrator_id: int = -1,
    release_tag_id: int = -1,
    release_tag_str: str = "Invalid",
    works_id: int = -1,
    works_str: str = "Invalid",
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

    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    safe_name = _esc((chara_name or "").strip() or f"EX_CHARA_{cid.raw}")
    ill_raw = (illustrator_name or "").strip()
    ill_str = _esc(ill_raw) if ill_raw else "Invalid"
    ill_id = illustrator_id if ill_raw else -1
    rt_str = _esc((release_tag_str or "").strip() or "Invalid")
    w_id = int(works_id)
    w_raw = (works_str or "").strip()
    if w_id == -1 or not w_raw or w_raw == "Invalid":
        w_id = -1
        w_str = "Invalid"
    else:
        w_str = _esc(w_raw)

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<CharaData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>chara{cid.raw6}</dataName>
  <releaseTagName>
    <id>{release_tag_id}</id>
    <str>{rt_str}</str>
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
    <id>{w_id}</id>
    <str>{w_str}</str>
    <data />
  </works>
  <illustratorName>
    <id>{ill_id}</id>
    <str>{ill_str}</str>
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


def write_ddsmap_xml(*, out_dir: Path, dds_map_id: int, name_str: str, dds_basename: str) -> Path:
    """
    Writes:
      out_dir/ddsMap/ddsMap{ID8}/DDSMap.xml

    Matches A001: DDSMapData + name + ddsFile/path（与 .dds 同目录）。
    """
    ddir = out_dir / "ddsMap" / f"ddsMap{dds_map_id:08d}"
    ddir.mkdir(parents=True, exist_ok=True)
    xml_path = ddir / "DDSMap.xml"

    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    safe_name = _esc((name_str or "").strip() or f"DdsMap{dds_map_id}")
    base = f"ddsMap{dds_map_id:08d}"

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<DDSMapData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>{base}</dataName>
  <name>
    <id>{dds_map_id}</id>
    <str>{safe_name}</str>
    <data />
  </name>
  <ddsFile>
    <path>{_esc(dds_basename)}</path>
  </ddsFile>
</DDSMapData>
"""
    xml_path.write_text(xml, encoding="utf-8")
    return xml_path

