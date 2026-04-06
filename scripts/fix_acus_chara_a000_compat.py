"""
将 ACUS 下自制角色相关 XML 与 XVERSE `data/A000` 官方样本对齐：
- 根元素补全 xmlns:xsd / xmlns:xsi（Chara / CharaWorks）
- netOpenName：2801 / v2_45 00_1 → 2800 / v2_45 00_0
- Chara：illustratorName -1 → 50 + 空 str；ranks 替换为与 A000 chara024680 一致的奖励段

用法（仓库根目录）:
  python scripts/fix_acus_chara_a000_compat.py
  python scripts/fix_acus_chara_a000_compat.py "D:/path/to/ACUS"
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from chuni_eventer_desktop.xml_writer import CHARA_DEFAULT_RANKS_XML  # noqa: E402

_NS = 'xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'

_NET_OLD = "    <id>2801</id>\n    <str>v2_45 00_1</str>"
_NET_NEW = "    <id>2800</id>\n    <str>v2_45 00_0</str>"


def _fix_netopen_block(text: str) -> str:
    return text.replace(_NET_OLD, _NET_NEW)


def _ensure_chara_data_ns(text: str) -> str:
    if "<CharaData " in text[:800] and "xmlns:xsd" in text[:800]:
        return text
    if text.startswith("<?xml"):
        rest = text.split("\n", 1)[1] if "\n" in text else text
    else:
        rest = text
    if rest.lstrip().startswith("<CharaData>"):
        return text.replace("<CharaData>", f"<CharaData {_NS}>", 1)
    return text


def _ensure_chara_works_ns(text: str) -> str:
    if "<CharaWorksData " in text[:800] and "xmlns:xsd" in text[:800]:
        return text
    if "<CharaWorksData>" in text:
        return text.replace("<CharaWorksData>", f"<CharaWorksData {_NS}>", 1)
    return text


def _fix_chara(path: Path) -> bool:
    t = path.read_text(encoding="utf-8")
    orig = t
    t = t.replace("<?xml version='1.0'", '<?xml version="1.0"')
    t = t.replace("encoding='utf-8'", 'encoding="utf-8"')
    t = _ensure_chara_data_ns(t)
    t = _fix_netopen_block(t)
    t = re.sub(
        r"  <illustratorName>\s*\n\s*<id>-1</id>\s*\n\s*<str>.*?</str>\s*\n\s*<data />\s*\n\s*</illustratorName>",
        "  <illustratorName>\n    <id>50</id>\n    <str />\n    <data />\n  </illustratorName>",
        t,
        count=1,
        flags=re.DOTALL,
    )
    t = re.sub(
        r"  <ranks>.*?</ranks>",
        CHARA_DEFAULT_RANKS_XML.rstrip("\n"),
        t,
        count=1,
        flags=re.DOTALL,
    )
    if t != orig:
        path.write_text(t, encoding="utf-8")
        return True
    return False


def _fix_chara_works(path: Path) -> bool:
    t = path.read_text(encoding="utf-8")
    orig = t
    t = t.replace("<?xml version='1.0'", '<?xml version="1.0"')
    t = t.replace("encoding='utf-8'", 'encoding="utf-8"')
    t = _ensure_chara_works_ns(t)
    t = _fix_netopen_block(t)
    if t != orig:
        path.write_text(t, encoding="utf-8")
        return True
    return False


def _fix_dds_image(path: Path) -> bool:
    t = path.read_text(encoding="utf-8")
    orig = t
    t = t.replace("encoding='utf-8'", 'encoding="utf-8"')
    t = _fix_netopen_block(t)
    if t != orig:
        path.write_text(t, encoding="utf-8")
        return True
    return False


def main() -> int:
    acus = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _REPO / "ACUS"
    if not acus.is_dir():
        print(f"not a directory: {acus}", file=sys.stderr)
        return 1
    n = 0
    for p in sorted((acus / "chara").glob("chara*/Chara.xml")):
        if _fix_chara(p):
            print("chara", p.relative_to(acus))
            n += 1
    for p in sorted((acus / "charaWorks").glob("charaWorks*/CharaWorks.xml")):
        if _fix_chara_works(p):
            print("charaWorks", p.relative_to(acus))
            n += 1
    for p in sorted((acus / "ddsImage").glob("ddsImage*/DDSImage.xml")):
        if _fix_dds_image(p):
            print("ddsImage", p.relative_to(acus))
            n += 1
    print(f"updated {n} file(s) under {acus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
