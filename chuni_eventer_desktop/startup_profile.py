"""启动耗时埋点：写入 ``.cache/logs/startup_profile.log``，并在控制台打印摘要。

默认开启。关闭：``CHUNI_STARTUP_PROFILE=0``。
"""

from __future__ import annotations

import atexit
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_enabled: bool | None = None
_started = False
_t0 = 0.0
_last = 0.0
_log_path: Path | None = None
_marks: list[tuple[str, float, float, float, str]] = []
_summary_written = False


def _is_enabled() -> bool:
    global _enabled
    if _enabled is None:
        raw = os.getenv("CHUNI_STARTUP_PROFILE", "1").strip().lower()
        _enabled = raw not in ("0", "false", "no", "off")
    return _enabled


def _log_line(text: str) -> None:
    if _log_path is None:
        return
    try:
        with open(_log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


def startup_begin() -> None:
    global _started, _t0, _last, _log_path
    if not _is_enabled() or _started:
        return
    _started = True
    _t0 = time.perf_counter()
    _last = _t0
    try:
        from .acus_workspace import app_cache_dir

        log_dir = app_cache_dir() / "logs"
    except Exception:
        log_dir = Path.cwd() / ".cache" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_path = log_dir / "startup_profile.log"
    header = (
        f"# startup profile pid={os.getpid()} "
        f"frozen={getattr(sys, 'frozen', False)} "
        f"exe={getattr(sys, 'executable', '')}\n"
    )
    try:
        _log_path.write_text(header, encoding="utf-8")
    except OSError:
        _log_path = None
    startup_mark("startup_begin")
    atexit.register(lambda: startup_write_summary(tag="exit"))


def startup_mark(label: str, **extra: object) -> None:
    global _last
    if not _is_enabled() or not _started:
        return
    now = time.perf_counter()
    delta_ms = (now - _last) * 1000.0
    total_ms = (now - _t0) * 1000.0
    extra_s = ""
    if extra:
        parts = [f"{k}={v!r}" for k, v in extra.items()]
        extra_s = " " + " ".join(parts)
    _marks.append((label, total_ms, delta_ms, now, extra_s))
    line = f"[{total_ms:8.1f}ms +{delta_ms:7.1f}ms] {label}{extra_s}"
    _log_line(line)
    print(f"[startup-profile] {line}", flush=True)
    _last = now


@contextmanager
def startup_span(label: str, **extra: object) -> Iterator[None]:
    if not _is_enabled() or not _started:
        yield
        return
    startup_mark(f"{label}:begin", **extra)
    try:
        yield
    finally:
        startup_mark(f"{label}:end", **extra)


def startup_write_summary(*, tag: str = "summary") -> None:
    global _summary_written
    if not _is_enabled() or not _started or not _marks:
        return
    ranked = sorted(_marks, key=lambda x: x[2], reverse=True)
    lines = [
        "",
        f"=== startup summary ({tag}) top deltas ===",
    ]
    for i, (label, total_ms, delta_ms, _t, extra_s) in enumerate(ranked[:20], start=1):
        lines.append(f"  {i:2d}. +{delta_ms:8.1f}ms @ {total_ms:8.1f}ms  {label}{extra_s}")
    lines.append(f"=== total {(_marks[-1][1] if _marks else 0):.1f}ms marks={len(_marks)} ===")
    block = "\n".join(lines)
    _log_line(block)
    print(f"[startup-profile]{block}", flush=True)
    if tag == "exit":
        _summary_written = True


def schedule_startup_summaries(scheduler) -> None:
    """``scheduler`` 为可 ``singleShot(ms, callable)`` 的对象（如 QTimer）。"""
    if not _is_enabled():
        return
    scheduler.singleShot(0, lambda: startup_mark("eventloop:first_timer0"))
    scheduler.singleShot(50, lambda: startup_write_summary(tag="50ms"))
    scheduler.singleShot(250, lambda: startup_write_summary(tag="250ms"))
    scheduler.singleShot(1000, lambda: startup_write_summary(tag="1s"))
    scheduler.singleShot(3000, lambda: startup_write_summary(tag="3s-final"))
