"""
将本机 ACUS 下的系统语音模板目录复制到仓库种子路径，供发行版打包内置。

默认复制：
  <acus>/cueFile/cueFile010700/  -> chuni_eventer_desktop/data/system_voice_seed/cueFile/cueFile010700/
  <acus>/systemVoice/systemVoice0700/ -> chuni_eventer_desktop/data/system_voice_seed/systemVoice/systemVoice0700/

用法:
  python scripts/refresh_system_voice_seed.py "E:/path/to/ACUS"
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    dest_root = root / "chuni_eventer_desktop" / "data" / "system_voice_seed"
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "acus_root",
        type=Path,
        help="ACUS 根目录（内含 cueFile/cueFile010700 与 systemVoice/systemVoice0700）",
    )
    args = ap.parse_args()
    src = args.acus_root.expanduser().resolve()
    if not src.is_dir():
        print(f"错误：不是目录：{src}", file=sys.stderr)
        return 1
    pairs: list[tuple[Path, Path]] = [
        (src / "cueFile" / "cueFile010700", dest_root / "cueFile" / "cueFile010700"),
        (src / "systemVoice" / "systemVoice0700", dest_root / "systemVoice" / "systemVoice0700"),
    ]
    for s, d in pairs:
        if not s.is_dir():
            print(f"错误：缺少源目录：{s}", file=sys.stderr)
            return 1
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(s, d)
        print(f"已复制：{s} -> {d}")
    acb = dest_root / "cueFile" / "cueFile010700" / "systemvoice0700.acb"
    awb = dest_root / "cueFile" / "cueFile010700" / "systemvoice0700.awb"
    if not acb.is_file() or not awb.is_file():
        print("警告：种子 cue 目录下未找到 systemvoice0700.acb / .awb，发行版重打包仍会失败。", file=sys.stderr)
        return 2
    print("完成。请提交 chuni_eventer_desktop/data/system_voice_seed/ 下变更以便发行版携带。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
