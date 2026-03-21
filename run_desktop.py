"""启动桌面端（开发调试与 PyInstaller 入口，避免相对导入问题）。"""
from __future__ import annotations

from chuni_eventer_desktop.app import main

if __name__ == "__main__":
    raise SystemExit(main())
