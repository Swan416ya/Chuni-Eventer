"""
在独立 Python 进程内执行 quicktex BC3 编码。

Windows 上 quicktex 原生库偶发 access violation 会直接杀掉进程；通过子进程隔离，
父进程（PyQt GUI）可捕获非零退出码并回退到 compressonatorcli 或提示用户。
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 4:
        print(
            "usage: python -m chuni_eventer_desktop.quicktex_worker <in_img> <out_dds> <quality> <mip_count>",
            file=sys.stderr,
        )
        return 2
    in_p = Path(argv[0])
    out_p = Path(argv[1])
    try:
        quality = int(argv[2])
        mip = int(argv[3])
    except ValueError:
        print("quality 与 mip_count 必须为整数", file=sys.stderr)
        return 2
    try:
        from .dds_quicktex import encode_bc3_inprocess

        encode_bc3_inprocess(
            input_image=in_p,
            output_dds=out_p,
            quality_level=quality,
            mip_count=mip,
        )
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
