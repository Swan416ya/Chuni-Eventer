"""
根据 ACUS/chara/*/Chara.xml 批量生成或覆盖 ACUS/charaWorks/*/CharaWorks.xml。

CharaWorks.releaseTagName、netOpenName 必须与引用该 works 的角色一致；本脚本从各 Chara 读取后按 works.id 去重。
若同一 works.id 下出现不一致的 releaseTag / netOpen / works.str，会打印警告并保留路径排序最先的一套。

用法（在仓库根目录）:
  python scripts/sync_acus_chara_works.py
  python scripts/sync_acus_chara_works.py "E:\\path\\to\\ACUS"
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from chuni_eventer_desktop.xml_writer import sync_all_chara_works_masters  # noqa: E402


def main() -> int:
    acus = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else _REPO / "ACUS"
    if not acus.is_dir():
        print(f"不是目录: {acus}", file=sys.stderr)
        return 1
    written, warns = sync_all_chara_works_masters(acus)
    for p in written:
        print(f"OK {p.relative_to(acus)}")
    for w in warns:
        print(f"WARN {w}")
    print(f"共写入 {len(written)} 条 CharaWorks。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
