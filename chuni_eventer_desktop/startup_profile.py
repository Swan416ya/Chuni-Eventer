"""启动耗时埋点（仅 CHUNI_STARTUP_PROFILE=1 时生效）。"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator

_t0 = time.perf_counter()
_last = _t0
_marks: list[tuple[float, float, str]] = []
_enabled: bool | None = None


def _is_enabled() -> bool:
    global _enabled
    if _enabled is None:
        raw = os.getenv("CHUNI_STARTUP_PROFILE", "").strip().lower()
        _enabled = raw in {"1", "true", "yes", "on"}
    return _enabled


def startup_mark(label: str, **extra: object) -> None:
    if not _is_enabled():
        return
    global _last
    now = time.perf_counter()
    delta_ms = (now - _last) * 1000.0
    total_ms = (now - _t0) * 1000.0
    _last = now
    suffix = ""
    if extra:
        parts = " ".join(f"{k}={v!r}" for k, v in extra.items())
        suffix = f" {parts}"
    line = f"[startup-profile] [{total_ms:8.1f}ms +{delta_ms:7.1f}ms] {label}{suffix}"
    _marks.append((delta_ms, total_ms, label))
    print(line, flush=True)


@contextmanager
def startup_span(label: str, **extra: object) -> Iterator[None]:
    startup_mark(f"{label}:begin", **extra)
    try:
        yield
    finally:
        startup_mark(f"{label}:end", **extra)


def startup_summary(top_n: int = 15) -> None:
    if not _is_enabled() or not _marks:
        return
    ranked = sorted(_marks, key=lambda x: x[0], reverse=True)[:top_n]
    print("[startup-profile] === top deltas ===", flush=True)
    for i, (delta_ms, total_ms, label) in enumerate(ranked, 1):
        print(
            f"[startup-profile]   {i:2d}. +{delta_ms:7.1f}ms @ {total_ms:8.1f}ms  {label}",
            flush=True,
        )
    print(f"[startup-profile] === total {_last - _t0:.3f}s marks={len(_marks)} ===", flush=True)
