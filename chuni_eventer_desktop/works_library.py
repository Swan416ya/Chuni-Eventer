from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .acus_workspace import app_cache_dir

WORKS_LIB_VERSION = 1
WORKS_LIB_FILENAME = "works_library.json"
# 与官方作品 ID 错开，自定义从 900001 起递增
WORKS_CUSTOM_ID_START = 900_001


@dataclass
class WorkEntry:
    id: int
    str: str


def works_library_path() -> Path:
    return app_cache_dir() / WORKS_LIB_FILENAME


def load_works_library() -> tuple[list[WorkEntry], int]:
    """
    返回 (条目列表按 id 排序, 下一个建议 id)。
    """
    p = works_library_path()
    if not p.is_file():
        return [], WORKS_CUSTOM_ID_START
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return [], WORKS_CUSTOM_ID_START
    if not isinstance(data, dict):
        return [], WORKS_CUSTOM_ID_START
    next_id = int(data.get("next_id") or WORKS_CUSTOM_ID_START)
    raw = data.get("entries") or []
    out: list[WorkEntry] = []
    if isinstance(raw, list):
        for it in raw:
            if not isinstance(it, dict):
                continue
            try:
                iid = int(it.get("id"))
            except Exception:
                continue
            s = str(it.get("str") or "").strip()
            if s:
                out.append(WorkEntry(iid, s))
    out.sort(key=lambda x: x.id)
    # next_id 至少大于已有最大自定义段 id
    max_c = max((e.id for e in out if e.id >= WORKS_CUSTOM_ID_START), default=0)
    next_id = max(next_id, max_c + 1 if max_c >= WORKS_CUSTOM_ID_START else WORKS_CUSTOM_ID_START)
    return out, next_id


def save_works_library(entries: list[WorkEntry], *, next_id: int | None = None) -> None:
    p = works_library_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted({e.id: e for e in entries}.values(), key=lambda x: x.id)
    ni = next_id
    if ni is None:
        max_c = max((e.id for e in entries if e.id >= WORKS_CUSTOM_ID_START), default=0)
        ni = max(WORKS_CUSTOM_ID_START, max_c + 1)
    payload: dict[str, Any] = {
        "version": WORKS_LIB_VERSION,
        "next_id": ni,
        "entries": [{"id": e.id, "str": e.str} for e in entries],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def add_work_entry(*, work_id: int, work_str: str) -> list[WorkEntry]:
    """新增或覆盖同 id 的 str，返回更新后的列表。"""
    s = work_str.strip()
    if not s:
        raise ValueError("作品显示名不能为空")
    entries, next_id = load_works_library()
    merged = {e.id: e for e in entries}
    merged[work_id] = WorkEntry(work_id, s)
    out = sorted(merged.values(), key=lambda x: x.id)
    save_works_library(out, next_id=max(next_id, work_id + 1))
    return out


def remove_work_entry(work_id: int) -> list[WorkEntry]:
    entries, next_id = load_works_library()
    out = [e for e in entries if e.id != work_id]
    save_works_library(out, next_id=next_id)
    return out
