from __future__ import annotations

import sys

from .cli_flags import QUICKTEX_WORKER_ARG
from .frozen_runtime import ensure_pyinstaller_dll_search_path
from .quicktex_worker import main as quicktex_worker_main
from .startup_profile import startup_begin, startup_mark

startup_begin()
startup_mark("__main__:before_app_import")
from .app import main

startup_mark("__main__:after_app_import")


if __name__ == "__main__":
    # 兼容两种 PyInstaller 入口（run_desktop.py / __main__.py）：
    # 当同一 exe 被 quicktex 子进程调用时，先分流到 worker，避免误启动 GUI。
    if len(sys.argv) >= 6 and sys.argv[1] == QUICKTEX_WORKER_ARG:
        ensure_pyinstaller_dll_search_path()
        raise SystemExit(quicktex_worker_main(sys.argv[2:6]))
    raise SystemExit(main())

