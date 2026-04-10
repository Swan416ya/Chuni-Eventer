from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class MapBonusRule:
    # 支持的业务类型：
    # - music: 指定乐曲
    # - musicGenre: 指定流派乐曲
    # - releaseTag: 指定版本乐曲（在 XML 中落到 musicWorks）
    # - chara: 指定角色
    # - charaRankGE: 角色等级 >= N
    kind: str
    point: int
    target_id: int
    target_str: str
    chara_rank: int = 1
    explain_text: str = ""


@dataclass(frozen=True)
class MapBonusData:
    name_id: int
    name_str: str
    rules: tuple[MapBonusRule, ...]
    xml_path: Path | None = None


FIELD_PATHS: dict[str, tuple[str, str]] = {
    "chara": ("chara", "charaName"),
    "charaWorks": ("charaWorks", "charaWorksName"),
    "skill": ("skill", "skillName"),
    "skillCategory": ("skillCategory", "skillCategory"),
    "music": ("music", "musicName"),
    "musicGenre": ("musicGenre", "genreName"),
    "musicWorks": ("musicWorks", "worksName"),
    "musicLabel": ("musicLabel", "labelName"),
    "musicDif": ("musicDif", "musicDif"),
    "musicLv": ("musicLv", "filterLv"),
}
KIND_TO_FIELD: dict[str, str] = {
    "music": "music",
    "musicGenre": "musicGenre",
    "releaseTag": "musicWorks",
    "chara": "chara",
    "charaRankGE": "chara",
}
KIND_TO_TYPE: dict[str, int] = {
    "music": 6,
    "musicGenre": 5,
    "releaseTag": 6,
    "chara": 1,
    "charaRankGE": 9,
}
ALLOWED_KINDS = tuple(KIND_TO_FIELD.keys())
MAX_RULES = 4
DEFAULT_KIND = "music"


def _esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_int(s: str, default: int) -> int:
    try:
        return int((s or "").strip())
    except Exception:
        return default


def suggest_next_mapbonus_id(acus_root: Path, *, start: int = 10_000_000) -> int:
    used: set[int] = set()
    for p in (acus_root / "mapBonus").glob("mapBonus*/MapBonus.xml"):
        try:
            root = ET.parse(p).getroot()
            v = (root.findtext("name/id") or "").strip()
            if v.isdigit():
                used.add(int(v))
        except Exception:
            continue
    out = max(start, 1)
    while out in used:
        out += 1
    return out


def load_mapbonus_xml(xml_path: Path) -> MapBonusData:
    root = ET.parse(xml_path).getroot()
    nid = _safe_int(root.findtext("name/id") or "", -1)
    nstr = (root.findtext("name/str") or "").strip() or f"MapBonus{nid}"
    rules: list[MapBonusRule] = []
    for sub in root.findall("substances/list/MapBonusSubstanceData"):
        type_code = _safe_int(sub.findtext("type") or "", 6)
        chosen_field = KIND_TO_FIELD[DEFAULT_KIND]
        point = 1
        target_id = -1
        target_str = "Invalid"
        # pick first non-invalid field as主要匹配维度
        for fld, (outer, leaf) in FIELD_PATHS.items():
            tid = _safe_int(sub.findtext(f"{outer}/{leaf}/id") or "", -1)
            tstr = (sub.findtext(f"{outer}/{leaf}/str") or "").strip() or "Invalid"
            pt = _safe_int(sub.findtext(f"{outer}/point") or "", 1)
            if tid != -1 or tstr != "Invalid":
                chosen_field = fld
                point = pt
                target_id = tid
                target_str = tstr
                break
        cr = _safe_int(sub.findtext("charaRank/charaRank") or "", 1)
        ex = (sub.findtext("charaRank/explainText") or "").strip()
        # 反推业务 kind（仅支持限定的 5 类）
        if cr > 1 and type_code == KIND_TO_TYPE["charaRankGE"]:
            kind = "charaRankGE"
            target_id = -1
            target_str = "Invalid"
        elif chosen_field == "music":
            kind = "music"
        elif chosen_field == "musicGenre":
            kind = "musicGenre"
        elif chosen_field == "musicWorks":
            kind = "releaseTag"
        elif chosen_field == "chara":
            kind = "chara"
        else:
            # 不支持的历史条目，按 releaseTag 兼容落地，避免读崩
            kind = "releaseTag"
        rules.append(
            MapBonusRule(
                kind=kind,
                point=point,
                target_id=target_id,
                target_str=target_str,
                chara_rank=cr,
                explain_text=ex,
            )
        )
    return MapBonusData(name_id=nid, name_str=nstr, rules=tuple(rules[:MAX_RULES]), xml_path=xml_path)


def save_mapbonus_xml(acus_root: Path, data: MapBonusData) -> Path:
    mid = int(data.name_id)
    mstr = (data.name_str or "").strip() or f"MapBonus{mid}"
    rules = list(data.rules) if data.rules else [
        MapBonusRule(kind=DEFAULT_KIND, point=1, target_id=-1, target_str="Invalid", chara_rank=1, explain_text="")
    ]
    rules = rules[:MAX_RULES]

    subs_xml: list[str] = []
    for r in rules:
        chunks: list[str] = []
        kind = r.kind if r.kind in ALLOWED_KINDS else DEFAULT_KIND
        chosen_field = KIND_TO_FIELD[kind]
        for fld, (outer, leaf) in FIELD_PATHS.items():
            pt = int(r.point) if fld == chosen_field else 1
            tid = int(r.target_id) if fld == chosen_field else -1
            tstr = _esc((r.target_str or "").strip() or "Invalid") if fld == chosen_field else "Invalid"
            # 角色等级>=N：不需要具体角色目标，固定 Invalid
            if kind == "charaRankGE" and fld == chosen_field:
                tid = -1
                tstr = "Invalid"
            chunks.append(
                f"""        <{outer}>
          <point>{pt}</point>
          <{leaf}>
            <id>{tid}</id>
            <str>{tstr}</str>
            <data />
          </{leaf}>
        </{outer}>"""
            )
        cr = int(r.chara_rank) if int(r.chara_rank) > 0 else 1
        if kind != "charaRankGE":
            cr = 1
        ex = _esc((r.explain_text or "").strip())
        subs_xml.append(
            f"""      <MapBonusSubstanceData>
        <type>{KIND_TO_TYPE[kind]}</type>
{chr(10).join(chunks)}
        <charaRank>
          <point>1</point>
          <charaRank>{cr}</charaRank>
          <explainText>{ex}</explainText>
        </charaRank>
      </MapBonusSubstanceData>"""
        )

    out_dir = acus_root / "mapBonus" / f"mapBonus{mid:08d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "MapBonus.xml"
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<MapBonusData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>mapBonus{mid:08d}</dataName>
  <name>
    <id>{mid}</id>
    <str>{_esc(mstr)}</str>
    <data />
  </name>
  <substances>
    <list>
{chr(10).join(subs_xml)}
    </list>
  </substances>
</MapBonusData>
"""
    out.write_text(xml, encoding="utf-8")
    return out

