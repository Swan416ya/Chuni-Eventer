from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def app_root_dir() -> Path:
    """
    源码运行：仓库根目录（chuni_eventer_desktop 的上一级）。
    PyInstaller 打包：可执行文件所在目录（与 exe 同级的 ACUS/）。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # chuni_eventer_desktop/acus_workspace.py -> 仓库根
    return Path(__file__).resolve().parents[1]


def acus_root_dir() -> Path:
    return app_root_dir() / "ACUS"


def app_cache_dir() -> Path:
    return app_root_dir() / ".cache"


def ensure_acus_layout() -> Path:
    """
    Create ACUS folder and core subfolders (A001-like roots we care about).
    """
    root = acus_root_dir()
    root.mkdir(parents=True, exist_ok=True)
    for d in [
        "chara",
        "ddsImage",
        "ddsMap",
        "music",
        "map",
        "mapArea",
        "mapBonus",
        "event",
        "course",
        "reward",
        "cueFile",
        "namePlate",
        "trophy",
        "stage",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)
    # 缓存不再放在 ACUS 内，统一放应用根 .cache
    (app_cache_dir() / "dds_preview").mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class AcusConfig:
    compressonatorcli_path: str = ""

    @staticmethod
    def path() -> Path:
        return acus_root_dir() / ".config.json"

    @classmethod
    def load(cls) -> "AcusConfig":
        p = cls.path()
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(compressonatorcli_path=str(data.get("compressonatorcli_path", "")))

    def save(self) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"compressonatorcli_path": self.compressonatorcli_path}
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

