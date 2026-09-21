# -*- coding: utf-8 -*-
"""
FreeMote 工具链定位模块。

背景:
- 伴侣(Mate)的 emote*.emtbytes 是 M2 PSB 格式(未加密), 由 FreeMote 工具链
  (PsbDecompile/PsBuild)解包与编译(含平台 port 转换)。
- 本模块负责定位随应用分发的 FreeMote 工具目录; PSB 解析/生成逻辑见
  psb_action_assigner.py。
"""
from __future__ import annotations

from pathlib import Path


def find_freemote_dir() -> Path | None:
    """定位 FreeMote 工具目录(含 PsBuild.exe), 找不到返回 None"""
    from .acus_workspace import app_root_dir
    root = app_root_dir()
    for cand in (
        root / "tools" / "FreeMote",          # 源码: 仓库根 tools/; 打包: exe 同级 tools/
        root / ".tools" / "FreeMote",
        Path(__file__).resolve().parent.parent / "tools" / "FreeMote",
    ):
        if (cand / "PsBuild.exe").is_file():
            return cand
    # 环境变量
    env = Path(__import__("os").environ.get("CHUNI_FREEMOTE_DIR", ""))
    if env and (env / "PsBuild.exe").is_file():
        return env
    return None


def check_freemote_ready() -> tuple[bool, str]:
    """检查 FreeMote 工具是否就绪, 返回 (是否可用, 提示信息)"""
    d = find_freemote_dir()
    if d is None:
        return False, (
            "未找到 FreeMote 工具(tools/FreeMote)。\n"
            "请将 FreeMote v4.7.0 工具包(PsBuild.exe 等)放到 tools/FreeMote/ 目录,"
            "或设置环境变量 CHUNI_FREEMOTE_DIR。")
    return True, str(d)
