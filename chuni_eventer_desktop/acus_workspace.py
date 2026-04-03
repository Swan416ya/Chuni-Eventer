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
    """游戏安装/数据根目录（用于索引全量 music、stage、ddsImage、ddsMap，供下拉选择）。"""
    game_root: str = ""

    @staticmethod
    def path() -> Path:
        return acus_root_dir() / ".config.json"

    @classmethod
    def load(cls) -> "AcusConfig":
        p = cls.path()
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            compressonatorcli_path=str(data.get("compressonatorcli_path", "")),
            game_root=str(data.get("game_root", "")),
        )

    def save(self) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "compressonatorcli_path": self.compressonatorcli_path,
            "game_root": self.game_root,
        }
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def bundled_compressonatorcli_path() -> Path | None:
    """
    分发 zip 内置于 exe 同级的 .tools/CompressonatorCLI/（由 build_windows.ps1 打入）。
    仅 PyInstaller 打包运行且该文件存在时返回路径。
    """
    if not getattr(sys, "frozen", False):
        return None
    cand = app_root_dir() / ".tools" / "CompressonatorCLI" / "compressonatorcli.exe"
    try:
        cand = cand.resolve(strict=False)
    except OSError:
        return None
    return cand if cand.is_file() else None


def resolve_compressonatorcli_path(cfg: AcusConfig) -> Path | None:
    """用户【设置】优先；未填写、路径无效或文件缺失时回退到打包随附的 compressonatorcli。"""
    raw = (cfg.compressonatorcli_path or "").strip()
    if raw:
        p = Path(raw).expanduser()
        try:
            p = p.resolve(strict=False)
        except OSError:
            return bundled_compressonatorcli_path()
        if p.is_file():
            return p
    return bundled_compressonatorcli_path()

