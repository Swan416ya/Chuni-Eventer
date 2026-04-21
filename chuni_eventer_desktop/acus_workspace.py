from __future__ import annotations

import json
import shutil
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


def _acus_seed_source_dir() -> Path:
    return Path(__file__).resolve().parent / "data" / "acus_seed"


def bundled_chara_works_sort_path(filename: str) -> Path | None:
    """随包内置的 charaWorks 排序表（WorksSort / WorksNameSort），用于游戏目录中找不到时的回退。"""
    p = Path(__file__).resolve().parent / "data" / "chara_works_seed" / filename
    return p if p.is_file() else None


def resolve_game_chara_works_sort_path(game_root: Path, filename: str) -> Path | None:
    """
    在用户配置的「游戏数据目录」下查找官方 A000 的 charaWorks 排序 XML。
    兼容：…/data/A000/charaWorks、安装根下的 A000、以及索引扫描到的名为 A000 的数据包根。
    """
    try:
        gr = game_root.expanduser().resolve(strict=False)
    except OSError:
        return None
    if not gr.is_dir():
        return None
    bases: list[Path] = [
        gr / "data" / "A000" / "charaWorks",
        gr / "data" / "a000" / "charaWorks",
        gr / "A000" / "charaWorks",
    ]
    # 延迟导入，避免与 game_data_index 的模块级环依赖在初始化阶段触发问题
    from .game_data_index import enumerate_game_data_roots

    try:
        for pack in enumerate_game_data_roots(gr):
            if pack.name.upper() == "A000":
                bases.append(pack / "charaWorks")
    except OSError:
        pass
    seen: set[str] = set()
    for base in bases:
        key = str(base).casefold()
        if key in seen:
            continue
        seen.add(key)
        cand = base / filename
        if cand.is_file():
            return cand
    return None


_CHARA_WORKS_SORT_NAMES = ("WorksSort.xml", "WorksNameSort.xml")

_EMPTY_CHARA_WORKS_SORT_XML = """<?xml version="1.0" encoding="utf-8"?>
<SerializeSortData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dataName>charaWorks</dataName>
  <SortList>
  </SortList>
</SerializeSortData>
"""


def _parse_optional_game_root(game_root: Path | str | None) -> Path | None:
    if game_root is None:
        return None
    raw = str(game_root).strip()
    if not raw:
        return None
    try:
        p = Path(raw).expanduser().resolve(strict=False)
    except OSError:
        return None
    return p if p.is_dir() else None


def sync_chara_works_sort_seeds(acus_root: Path, game_root: Path | str | None = None) -> None:
    """
    若 ACUS/charaWorks 下缺少 WorksSort / WorksNameSort：
    优先从游戏 A000 复制；找不到则使用随包种子；仍无则写入空 Sort 壳。
    已存在的文件不覆盖（保留用户或工具已追加的 StringID）。
    """
    works_root = acus_root / "charaWorks"
    works_root.mkdir(parents=True, exist_ok=True)
    gr = _parse_optional_game_root(game_root)
    for fn in _CHARA_WORKS_SORT_NAMES:
        dst = works_root / fn
        if dst.exists():
            continue
        src: Path | None = resolve_game_chara_works_sort_path(gr, fn) if gr is not None else None
        if src is None:
            bp = bundled_chara_works_sort_path(fn)
            if bp is not None:
                src = bp
        if src is not None and src.is_file():
            try:
                shutil.copy2(src, dst)
            except OSError:
                pass
        if not dst.exists():
            dst.write_text(_EMPTY_CHARA_WORKS_SORT_XML, encoding="utf-8")


def _seed_acus_from_bundled(acus_root: Path) -> None:
    """
    首次创建 ACUS 时从随包数据复制：releaseTag（自制譜 / セカイ 等）、常用点数与功能票 Reward。
    已存在的子目录不覆盖，避免冲掉用户修改。
    """
    seed = _acus_seed_source_dir()
    if not seed.is_dir():
        return
    for sub in ("releaseTag", "reward"):
        src = seed / sub
        if not src.is_dir():
            continue
        dst = acus_root / sub
        dst.mkdir(parents=True, exist_ok=True)
        try:
            for item in sorted(src.iterdir()):
                if not item.is_dir():
                    continue
                dest_item = dst / item.name
                if dest_item.exists():
                    continue
                shutil.copytree(item, dest_item)
        except OSError:
            continue


def ensure_acus_layout(*, game_root: Path | str | None = None) -> Path:
    """
    Create ACUS folder and core subfolders (A001-like roots we care about).
    """
    root = acus_root_dir()
    root.mkdir(parents=True, exist_ok=True)
    for d in [
        "chara",
        "charaWorks",
        "ddsImage",
        "ddsMap",
        "music",
        "map",
        "mapArea",
        "mapBonus",
        "event",
        "unlockChallenge",
        "course",
        "reward",
        "cueFile",
        "namePlate",
        "trophy",
        "stage",
        "releaseTag",
    ]:
        (root / d).mkdir(parents=True, exist_ok=True)
    _seed_acus_from_bundled(root)
    sync_chara_works_sort_seeds(root, game_root)
    # 缓存不再放在 ACUS 内，统一放应用根 .cache
    (app_cache_dir() / "dds_preview").mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class AcusConfig:
    compressonatorcli_path: str = ""
    """游戏安装/数据根目录（用于索引全量 music、stage、ddsImage、ddsMap，供下拉选择）。"""
    game_root: str = ""
    enable_pgko_ugc_experimental: bool = False

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
            enable_pgko_ugc_experimental=bool(data.get("enable_pgko_ugc_experimental", False)),
        )

    def save(self) -> None:
        p = self.path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "compressonatorcli_path": self.compressonatorcli_path,
            "game_root": self.game_root,
            "enable_pgko_ugc_experimental": bool(self.enable_pgko_ugc_experimental),
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

