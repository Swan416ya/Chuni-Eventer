from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

# 默认写 Invalid，避免与本地 ACUS/releaseTag 中不存在的条目发生不一致。
CHARA_DEFAULT_RELEASE_TAG_ID = -1
CHARA_DEFAULT_RELEASE_TAG_STR = "Invalid"

# 与 XVERSE `data/A000/chara` 官方样本一致（如 chara000780、chara024680）；曾用 2801/00_1 时易出现与底包解禁轴不一致。
CHARA_DEFAULT_NET_OPEN_ID = 2800
CHARA_DEFAULT_NET_OPEN_STR = "v2_45 00_0"

# 与 A000 `chara024680` 的 ranks 一致；reward 为 Invalid 时部分版本整卡不加载。
CHARA_DEFAULT_RANKS_XML = """  <ranks>
    <CharaRankData>
      <index>1</index>
      <type>1</type>
      <rewardSkillSeed>
        <rewardSkillSeed>
          <id>61030025</id>
          <str>【HARD】ジャッジメント×5</str>
          <data />
        </rewardSkillSeed>
      </rewardSkillSeed>
      <text>
        <flavorTxtFile>
          <path />
        </flavorTxtFile>
      </text>
    </CharaRankData>
    <CharaRankData>
      <index>10</index>
      <type>1</type>
      <rewardSkillSeed>
        <rewardSkillSeed>
          <id>61030025</id>
          <str>【HARD】ジャッジメント×5</str>
          <data />
        </rewardSkillSeed>
      </rewardSkillSeed>
      <text>
        <flavorTxtFile>
          <path />
        </flavorTxtFile>
      </text>
    </CharaRankData>
    <CharaRankData>
      <index>25</index>
      <type>1</type>
      <rewardSkillSeed>
        <rewardSkillSeed>
          <id>61000101</id>
          <str>【OTHER】限界突破の証×1</str>
          <data />
        </rewardSkillSeed>
      </rewardSkillSeed>
      <text>
        <flavorTxtFile>
          <path />
        </flavorTxtFile>
      </text>
    </CharaRankData>
    <CharaRankData>
      <index>50</index>
      <type>1</type>
      <rewardSkillSeed>
        <rewardSkillSeed>
          <id>61000111</id>
          <str>【OTHER】真・限界突破の証×1</str>
          <data />
        </rewardSkillSeed>
      </rewardSkillSeed>
      <text>
        <flavorTxtFile>
          <path />
        </flavorTxtFile>
      </text>
    </CharaRankData>
    <CharaRankData>
      <index>100</index>
      <type>1</type>
      <rewardSkillSeed>
        <rewardSkillSeed>
          <id>61000121</id>
          <str>【OTHER】絆・限界突破の証×1</str>
          <data />
        </rewardSkillSeed>
      </rewardSkillSeed>
      <text>
        <flavorTxtFile>
          <path />
        </flavorTxtFile>
      </text>
    </CharaRankData>
  </ranks>"""

def _works_sort_seed_path(acus_root: Path, filename: str) -> Path | None:
    local_a000 = acus_root.parent / "A000" / "charaWorks" / filename
    if local_a000.is_file():
        return local_a000
    # 兼容用户当前环境给出的 A000 绝对路径
    if filename == "WorksSort.xml":
        cand = Path("D:/Chunithm_XVerseX/data/A000/charaWorks/WorksSort.xml")
        return cand if cand.is_file() else None
    cand = Path("D:/Chunithm_XVerseX/data/A000/charaWorks/WorksNameSort.xml")
    return cand if cand.is_file() else None


def _append_sort_string_id(sort_xml: Path, works_id: int) -> None:
    root = ET.parse(sort_xml).getroot()
    # ElementTree 不会保留 xmlns 声明为普通属性；写回前补齐，避免格式与官方样本偏差。
    root.set("xmlns:xsd", "http://www.w3.org/2001/XMLSchema")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    dn = root.find("dataName")
    if dn is None:
        dn = ET.SubElement(root, "dataName")
    if not (dn.text or "").strip():
        dn.text = "charaWorks"
    sl = root.find("SortList")
    if sl is None:
        sl = ET.SubElement(root, "SortList")
    for n in sl.findall("StringID/id"):
        try:
            if int((n.text or "").strip()) == int(works_id):
                ET.indent(root, space="  ")
                ET.ElementTree(root).write(sort_xml, encoding="utf-8", xml_declaration=True)
                return
        except ValueError:
            continue
    s = ET.SubElement(sl, "StringID")
    ET.SubElement(s, "id").text = str(int(works_id))
    ET.SubElement(s, "str")
    ET.SubElement(s, "data")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(sort_xml, encoding="utf-8", xml_declaration=True)


def ensure_chara_works_sorts(*, acus_root: Path, works_id: int) -> None:
    works_root = acus_root / "charaWorks"
    works_root.mkdir(parents=True, exist_ok=True)
    for fn in ("WorksSort.xml", "WorksNameSort.xml"):
        dst = works_root / fn
        if not dst.exists():
            seed = _works_sort_seed_path(acus_root, fn)
            if seed is not None:
                dst.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                dst.write_text(
                    """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>charaWorks</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
""",
                    encoding="utf-8",
                )
        _append_sort_string_id(dst, works_id)


def write_ddsimage_xml(
    *,
    out_dir: Path,
    chara_id: int,
    net_open_id: int = CHARA_DEFAULT_NET_OPEN_ID,
    net_open_str: str = CHARA_DEFAULT_NET_OPEN_STR,
) -> Path:
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
    """
    与 A001 CharaWorks 中 sortName 对齐：
    - 含拉丁字母时：仅保留 A–Z / a–z / 0–9 并转大写、直接拼接（例：charaWorks000184 → BANGDREAMAVEMUJICA）。
    - 纯日文等：用作品显示名全文（例：charaWorks000183 官方为 メタリスト，与 name.str 略异，工具无法自动推断读法）。
    """
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
    release_tag_id: int = CHARA_DEFAULT_RELEASE_TAG_ID,
    release_tag_str: str = CHARA_DEFAULT_RELEASE_TAG_STR,
    net_open_id: int = CHARA_DEFAULT_NET_OPEN_ID,
    net_open_str: str = CHARA_DEFAULT_NET_OPEN_STR,
) -> Path:
    """
    写入作品主数据（与 A000 `charaWorks/charaWorksXXXXXX/CharaWorks.xml` 同结构）。

    客户端会把 **本条 CharaWorks** 与 **引用同一 works.id 的 Chara** 放在同一筛选维度下；因此下列字段须与
    **该批角色各自的 Chara.xml** 一致（见仓库 `docs/CharaWorks与Chara字段对照详解.md`）：

    - **releaseTagName**：必须与 Chara.`releaseTagName` 完全相同（并与 `releaseTag/*/ReleaseTag.xml` 的 `name` 可对上）。
    - **netOpenName**：必须与 Chara.`netOpenName` 完全相同（解禁维度一致时才会一起出现）。
    - **name**：必须与 Chara.`works` 完全相同（id 与 str）。
    """
    def _esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    wid = int(works_id)
    if wid < 0:
        raise ValueError("works_id 须为非负整数")
    row = f"{wid:06d}"
    safe_works = _esc((works_str or "").strip() or f"Works{wid}")
    rt_str = _esc((release_tag_str or "").strip() or CHARA_DEFAULT_RELEASE_TAG_STR)
    no_str = _esc((net_open_str or "").strip() or CHARA_DEFAULT_NET_OPEN_STR)
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
    ensure_chara_works_sorts(acus_root=out_dir, works_id=wid)
    return xml_path


def ensure_chara_works_xml(
    *,
    out_dir: Path,
    works_id: int,
    works_str: str,
    release_tag_id: int = CHARA_DEFAULT_RELEASE_TAG_ID,
    release_tag_str: str = CHARA_DEFAULT_RELEASE_TAG_STR,
    net_open_id: int = CHARA_DEFAULT_NET_OPEN_ID,
    net_open_str: str = CHARA_DEFAULT_NET_OPEN_STR,
) -> Path | None:
    """
    若 works 有效则写入/覆盖 charaWorks；否则跳过（works 仍为 -1/Invalid 时不写）。
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


def read_chara_xml_works_release_netopen(xml_path: Path) -> tuple[int, str, int, str, int, str] | None:
    """
    从 Chara.xml 读出与 CharaWorks 对齐所需的五元组：
    (works_id, works_str, release_tag_id, release_tag_str, net_open_id, net_open_str)。
    works 无效（id < 0、str 空或 Invalid）时返回 None。
    """
    try:
        root = ET.parse(xml_path).getroot()
        if (root.tag or "") != "CharaData":
            return None
        wi = (root.findtext("works/id") or "").strip()
        ws = (root.findtext("works/str") or "").strip()
        try:
            w_id = int(wi)
        except ValueError:
            return None
        if w_id < 0:
            return None
        if not ws or ws == "Invalid":
            return None
        ri = (root.findtext("releaseTagName/id") or "").strip()
        rs = (root.findtext("releaseTagName/str") or "").strip()
        try:
            r_id = int(ri)
        except ValueError:
            r_id = CHARA_DEFAULT_RELEASE_TAG_ID
        r_s = rs or CHARA_DEFAULT_RELEASE_TAG_STR
        ni = (root.findtext("netOpenName/id") or "").strip()
        ns = (root.findtext("netOpenName/str") or "").strip()
        try:
            n_id = int(ni)
        except ValueError:
            n_id = CHARA_DEFAULT_NET_OPEN_ID
        n_s = (ns or "").strip() or CHARA_DEFAULT_NET_OPEN_STR
        return w_id, ws, r_id, r_s, n_id, n_s
    except Exception:
        return None


def ensure_chara_works_for_chara_xml(chara_xml_path: Path) -> Path | None:
    """
    根据单份 Chara.xml 写入/覆盖对应 charaWorks（ACUS 根 = chara_xml 上三级目录）。
    """
    data = read_chara_xml_works_release_netopen(chara_xml_path)
    if data is None:
        return None
    w_id, w_s, r_id, r_s, n_id, n_s = data
    acus_root = chara_xml_path.parent.parent.parent
    return ensure_chara_works_xml(
        out_dir=acus_root,
        works_id=w_id,
        works_str=w_s,
        release_tag_id=r_id,
        release_tag_str=r_s,
        net_open_id=n_id,
        net_open_str=n_s,
    )


def sync_all_chara_works_masters(acus_root: Path) -> tuple[list[Path], list[str]]:
    """
    扫描 `acus_root/chara/chara*/Chara.xml`，按 **works.id** 聚合，为每个 id 写一条 CharaWorks。
    若多个角色共用同一 works.id 但 releaseTagName / netOpenName / works.str 不一致，只保留**按路径排序最先**
    出现的一套，并在 warnings 中说明（需手工统一 Chara 或拆分 works.id）。
    """
    chara_glob = sorted((acus_root / "chara").glob("chara*/Chara.xml"))
    chosen: dict[int, tuple[str, int, str, int, str, str]] = {}
    # works_id -> (works_str, rt_id, rt_str, no_id, no_str, source_path)
    warnings: list[str] = []
    for xp in chara_glob:
        data = read_chara_xml_works_release_netopen(xp)
        if data is None:
            continue
        w_id, w_s, r_id, r_s, n_id, n_s = data
        tup = (w_s, r_id, r_s, n_id, n_s)
        if w_id not in chosen:
            chosen[w_id] = (*tup, str(xp))
            continue
        prev_w_s, prev_ri, prev_rs, prev_ni, prev_ns, prev_src = chosen[w_id]
        if (prev_w_s, prev_ri, prev_rs, prev_ni, prev_ns) != tup:
            warnings.append(
                f"works id={w_id}：{xp} 与 {prev_src} 的 releaseTagName/netOpenName/works.str 不一致，"
                "已保留先出现的一套；请统一 Chara 或改用不同 works.id。"
            )
            continue
    written: list[Path] = []
    for w_id, (w_s, r_id, r_s, n_id, n_s, _) in chosen.items():
        p = ensure_chara_works_xml(
            out_dir=acus_root,
            works_id=w_id,
            works_str=w_s,
            release_tag_id=r_id,
            release_tag_str=r_s,
            net_open_id=n_id,
            net_open_str=n_s,
        )
        if p is not None:
            written.append(p)
    return written, warnings


def write_chara_xml(
    *,
    out_dir: Path,
    chara_id: int,
    chara_name: str,
    illustrator_name: str | None = None,
    illustrator_id: int = -1,
    release_tag_id: int = CHARA_DEFAULT_RELEASE_TAG_ID,
    release_tag_str: str = CHARA_DEFAULT_RELEASE_TAG_STR,
    works_id: int = -1,
    works_str: str = "Invalid",
    net_open_id: int = CHARA_DEFAULT_NET_OPEN_ID,
    net_open_str: str = CHARA_DEFAULT_NET_OPEN_STR,
) -> Path:
    """
    Writes:
      out_dir/chara/chara{ID6}/Chara.xml

    Minimal-ish CharaData for tooling purposes（字段与 `data/A000/chara` 官方对齐）。
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
    if ill_raw:
        ill_block = (
            f"  <illustratorName>\n    <id>{int(illustrator_id)}</id>\n"
            f"    <str>{_esc(ill_raw)}</str>\n    <data />\n  </illustratorName>"
        )
    else:
        ill_block = """  <illustratorName>
    <id>50</id>
    <str />
    <data />
  </illustratorName>"""
    rt_str = _esc((release_tag_str or "").strip() or CHARA_DEFAULT_RELEASE_TAG_STR)
    w_id = int(works_id)
    w_raw = (works_str or "").strip()
    if w_id == -1 or not w_raw or w_raw == "Invalid":
        w_id = -1
        w_str = "Invalid"
    else:
        w_str = _esc(w_raw)

    xml = (
        f"""<?xml version="1.0" encoding="utf-8"?>
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
{ill_block}
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
"""
        + CHARA_DEFAULT_RANKS_XML
        + """
</CharaData>
"""
    )
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

