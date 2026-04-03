"""启动桌面端（开发调试与 PyInstaller 入口，避免相对导入问题）。"""
from __future__ import annotations

import sys

from chuni_eventer_desktop.cli_flags import QUICKTEX_WORKER_ARG

if __name__ == "__main__":
    # PyInstaller 单文件下不能用 ``exe -m quicktex_worker``（会误启 GUI）。
    # 子进程：同一 exe + QUICKTEX_WORKER_ARG，仅跑编码后退出（见 dds_quicktex）。
    if len(sys.argv) >= 6 and sys.argv[1] == QUICKTEX_WORKER_ARG:
        from chuni_eventer_desktop.quicktex_worker import main as quicktex_worker_main

        raise SystemExit(quicktex_worker_main(sys.argv[2:6]))
    from chuni_eventer_desktop.app import main

    raise SystemExit(main())
