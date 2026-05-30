from __future__ import annotations

import sys
from pathlib import Path

# 目录直跑 ``python chuni_eventer_desktop`` 或误用 ``python -X -m chuni_eventer_desktop`` 时
# __package__ 为空且项目根不在 sys.path，相对/绝对包导入都会失败。
if __package__ in (None, ""):
    _root = Path(__file__).resolve().parents[1]
    _root_s = str(_root)
    if _root_s not in sys.path:
        sys.path.insert(0, _root_s)

from chuni_eventer_desktop.cli_flags import QUICKTEX_WORKER_ARG
from chuni_eventer_desktop.frozen_runtime import ensure_pyinstaller_dll_search_path
from chuni_eventer_desktop.quicktex_worker import main as quicktex_worker_main
from chuni_eventer_desktop.app import main


if __name__ == "__main__":
    # 兼容两种 PyInstaller 入口（run_desktop.py / __main__.py）：
    # 当同一 exe 被 quicktex 子进程调用时，先分流到 worker，避免误启动 GUI。
    if len(sys.argv) >= 6 and sys.argv[1] == QUICKTEX_WORKER_ARG:
        ensure_pyinstaller_dll_search_path()
        raise SystemExit(quicktex_worker_main(sys.argv[2:6]))
    raise SystemExit(main())
