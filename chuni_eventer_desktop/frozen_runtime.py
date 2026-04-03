"""PyInstaller 单文件 exe 运行时辅助。"""
from __future__ import annotations

import sys


def ensure_pyinstaller_dll_search_path() -> None:
    """
    将 _MEIPASS 加入 DLL 搜索路径，便于加载与 quicktex 同目录的 _quicktex*.pyd 及 VC 运行库。
    在导入任何可能加载该扩展的模块之前调用。
    """
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    import os

    try:
        os.add_dll_directory(meipass)
    except (OSError, AttributeError):
        pass
