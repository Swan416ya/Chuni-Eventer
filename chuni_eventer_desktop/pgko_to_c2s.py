from __future__ import annotations

import struct
import zlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import pjsk_audio_chuni as pjsk_ac
from .dds_convert import convert_to_bc3_dds
from .music_jacket_replace import JACKET_BC3_EDGE, _prepare_square_jacket_png
from .pgko_cs_bridge import convert_mgxc_with_penguin_bridge
from .pjsk_acus_install import (
    append_event_sort,
    append_music_sort,
    build_music_xml,
    next_chuni_music_id,
    next_custom_event_id,
    write_ultima_unlock_event,
)
PGKO_RELEASE_TAG_ID = -1
PGKO_RELEASE_TAG_STR = "Invalid"
MGXC_TICKS_PER_BAR_4_4 = 1920

from ._suspect.c2s_emit import (
    AldNote,
    AirHold,
    AirNote,
    AscNote,
    AsdNote,
    BpmSetting,
    ChargeNote,
    DcmSetting,
    FlickNote,
    HoldNote,
    HxdNote,
    MeterSetting,
    MineNote,
    SlideNote,
    SxcNote,
    SxdNote,
    SlaNote,
    TimelineSpeedSetting,
    TapNote,
    create_file,
)


@dataclass(frozen=True)
class PgkoChartPick:
    path: Path
    ext: str  # mgxc | ugc


def pick_pgko_chart_for_convert(download_output: Path) -> PgkoChartPick | None:
    """
    从下载产物中挑选用于转码的谱面文件：
    优先级：mgxc > ugc。
    """
    files: list[Path] = []
    if download_output.is_file():
        files.append(download_output)
    elif download_output.is_dir():
        for p in download_output.glob("**/*"):
            if p.is_file():
                files.append(p)
    if not files:
        return None

    by_ext: dict[str, list[Path]] = {"mgxc": [], "ugc": []}
    for p in files:
        ext = p.suffix.lower().lstrip(".")
        if ext in by_ext:
            by_ext[ext].append(p)

    for ext in ("mgxc", "ugc"):
        arr = sorted(by_ext[ext])
        if arr:
            return PgkoChartPick(path=arr[0], ext=ext)
    return None


@dataclass(frozen=True)
class _MgxcEvent:
    kind: str
    tick: int
    value: float
    value2: int = 0


@dataclass(frozen=True)
class _MgxcNote:
    typ: int
    long_attr: int
    direction: int
    ex_attr: int
    x: int
    width: int
    height: int
    tick: int
    timeline: int
    seq: int


@dataclass(frozen=True)
class _GroundAnchor:
    tick: int
    lane: int
    width: int
    linkage: str  # TAP/HLD/SLD


@dataclass(frozen=True)
class _MgxcMeta:
    designer: str = ""
    artist: str = ""
    title: str = ""
    song_id: str = ""
    bgm_file: str = ""
    preview_start_sec: float = 0.0
    preview_stop_sec: float = 30.0
    has_preview_start: bool = False
    has_preview_stop: bool = False
    difficulty: int = 3
    level_const: float | None = None
    soffset: bool = False


def _read_exact(f: BinaryIO, size: int) -> bytes:
    b = f.read(size)
    if len(b) != size:
        raise ValueError("unexpected EOF while reading mgxc")
    return b


def _i16(b: bytes) -> int:
    return struct.unpack("<h", b)[0]


def _i32(b: bytes) -> int:
    return struct.unpack("<i", b)[0]


def _f64(b: bytes) -> float:
    return struct.unpack("<d", b)[0]


def _decode_mgxc_text(raw: bytes) -> str:
    for enc in ("utf-8", "cp932", "shift_jis"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="ignore")


def _read_field(buf: BinaryIO) -> str | int | float:
    typ = _i16(_read_exact(buf, 2))
    attr = _i16(_read_exact(buf, 2))
    if typ == 4:
        return _decode_mgxc_text(_read_exact(buf, attr))
    if typ == 3:
        return _f64(_read_exact(buf, 8))
    if typ == 2:
        return _i32(_read_exact(buf, 4))
    if typ in (0, 1):
        return int(attr)
    raise ValueError(f"unknown mgxc field type: {typ}")


def _parse_mgxc(path: Path) -> tuple[_MgxcMeta, list[_MgxcEvent], list[_MgxcNote]]:
    meta = _MgxcMeta()
    events: list[_MgxcEvent] = []
    notes: list[_MgxcNote] = []
    with path.open("rb") as f:
        if _read_exact(f, 4) != b"MGXC":
            raise ValueError("invalid mgxc header")
        _read_exact(f, 8)  # block size + version
        while True:
            hdr = f.read(4)
            if not hdr:
                break
            if len(hdr) != 4:
                raise ValueError("broken mgxc block header")
            size = _i32(_read_exact(f, 4))
            block = _read_exact(f, size)
            if hdr == b"evnt":
                import io

                br = io.BytesIO(block)
                seq = 0
                while br.tell() < len(block):
                    name = _read_exact(br, 4).decode("utf-8", errors="ignore")
                    if name == "bpm ":
                        tick = int(_read_field(br))
                        bpm = float(_read_field(br))
                        events.append(_MgxcEvent(kind="bpm", tick=tick, value=bpm))
                    elif name == "beat":
                        bar = int(_read_field(br))
                        num = int(_read_field(br))
                        den = int(_read_field(br))
                        events.append(
                            _MgxcEvent(kind="beat", tick=bar, value=float(num), value2=den)
                        )
                    elif name == "til ":
                        timeline = int(_read_field(br))
                        tick = int(_read_field(br))
                        speed = float(_read_field(br))
                        events.append(
                            _MgxcEvent(kind="til", tick=tick, value=speed, value2=timeline)
                        )
                    elif name == "smod":
                        tick = int(_read_field(br))
                        speed = float(_read_field(br))
                        events.append(_MgxcEvent(kind="smod", tick=tick, value=speed))
                    elif name == "mbkm":
                        _read_field(br)
                    elif name == "bmrk":
                        _read_exact(br, 8 + int(_i32(_read_exact(br, 4))))  # skip wide hash
                    elif name == "rimg":
                        _read_field(br)
                        _read_field(br)
                        w_typ = _i32(_read_exact(br, 4))
                        w_len = _i32(_read_exact(br, 4))
                        if w_typ == 4 and w_len > 0:
                            _read_exact(br, w_len)
                        _read_exact(br, 4)
                        continue
                    else:
                        raise ValueError(f"unknown mgxc event tag: {name!r}")
                    _read_exact(br, 4)  # trailing zero
            elif hdr == b"meta":
                import io

                br = io.BytesIO(block)
                designer = meta.designer
                artist = meta.artist
                title = meta.title
                song_id = meta.song_id
                bgm_file = meta.bgm_file
                preview_start_sec = meta.preview_start_sec
                preview_stop_sec = meta.preview_stop_sec
                has_preview_start = meta.has_preview_start
                has_preview_stop = meta.has_preview_stop
                while br.tell() < len(block):
                    name = _read_exact(br, 4).decode("utf-8", errors="ignore")
                    data = _read_field(br)
                    if name == "dsgn" and isinstance(data, str):
                        designer = data.strip()
                    elif name == "arts" and isinstance(data, str):
                        artist = data.strip()
                    elif name == "titl" and isinstance(data, str):
                        title = data.strip()
                    elif name == "sgid" and isinstance(data, str):
                        song_id = data.strip()
                    elif name == "wvfn" and isinstance(data, str):
                        bgm_file = data.strip()
                    elif name == "wvp0":
                        try:
                            preview_start_sec = float(data)
                            has_preview_start = True
                        except Exception:
                            preview_start_sec = 0.0
                    elif name == "wvp1":
                        try:
                            preview_stop_sec = float(data)
                            has_preview_stop = True
                        except Exception:
                            preview_stop_sec = 30.0
                    elif name == "diff":
                        try:
                            difficulty = int(data)
                        except Exception:
                            difficulty = 3
                    elif name == "cnst":
                        try:
                            level_const = float(data)
                        except Exception:
                            level_const = None
                meta = _MgxcMeta(
                    designer=designer,
                    artist=artist,
                    title=title,
                    song_id=song_id,
                    bgm_file=bgm_file,
                    preview_start_sec=preview_start_sec,
                    preview_stop_sec=preview_stop_sec,
                    has_preview_start=has_preview_start,
                    has_preview_stop=has_preview_stop,
                    difficulty=int(locals().get("difficulty", meta.difficulty)),
                    level_const=locals().get("level_const", meta.level_const),
                )
            elif hdr == b"dat2":
                import io

                br = io.BytesIO(block)
                while br.tell() < len(block):
                    typ = struct.unpack("<b", _read_exact(br, 1))[0]
                    long_attr = struct.unpack("<b", _read_exact(br, 1))[0]
                    direction = struct.unpack("<b", _read_exact(br, 1))[0]
                    ex_attr = struct.unpack("<b", _read_exact(br, 1))[0]
                    _read_exact(br, 1)  # variationId
                    x = struct.unpack("<b", _read_exact(br, 1))[0]
                    width = _i16(_read_exact(br, 2))
                    height = _i32(_read_exact(br, 4))
                    tick = _i32(_read_exact(br, 4))
                    timeline = _i32(_read_exact(br, 4))
                    if typ == 0x0A and long_attr == 0x01:
                        _read_exact(br, 4)
                    notes.append(
                        _MgxcNote(
                            typ=typ,
                            long_attr=long_attr,
                            direction=direction,
                            ex_attr=ex_attr,
                            x=x,
                            width=width,
                            height=height,
                            tick=tick,
                            timeline=timeline,
                            seq=seq,
                        )
                    )
                    seq += 1
    return meta, events, notes


def _find_fallback_mgxc(source: Path) -> Path | None:
    """
    为 ugc 提供回退：
    1) 同名同目录 *.mgxc
    2) 同目录任意 *.mgxc
    3) 上一级目录递归同 stem *.mgxc
    """
    direct = source.with_suffix(".mgxc")
    if direct.exists() and direct.is_file():
        return direct

    parent = source.parent
    siblings = sorted(p for p in parent.glob("*.mgxc") if p.is_file())
    if siblings:
        return siblings[0]

    root = parent.parent if parent.parent != parent else parent
    same_stem = sorted(
        p for p in root.glob("**/*.mgxc") if p.is_file() and p.stem == source.stem
    )
    if same_stem:
        return same_stem[0]
    return None


def _iter_ugc_paths_near_mgxc(mgxc_path: Path) -> list[Path]:
    """与 mgxc 同目录的 ugc：优先同名，再按名排序的其余 *.ugc。"""
    candidates: list[Path] = []
    same = mgxc_path.with_suffix(".ugc")
    if same.exists() and same.is_file():
        candidates.append(same)
    candidates.extend(sorted(p for p in mgxc_path.parent.glob("*.ugc") if p.is_file()))
    seen: set[Path] = set()
    out: list[Path] = []
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _read_ugc_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="cp932", errors="ignore")
        except Exception:
            return path.read_text(encoding="utf-8", errors="ignore")


def _b36_int(s: str) -> int:
    return int((s or "0").strip().upper(), 36)


def _parse_bar_tick(text: str) -> tuple[int, int]:
    s = text.strip()
    if "'" not in s:
        raise ValueError(f"invalid BarTick: {text!r}")
    a, b = s.split("'", 1)
    return int(a), int(b)


def _build_bar_to_tick(beat_events: list[_MgxcEvent]) -> callable:
    arr = sorted(beat_events, key=lambda x: x.tick)
    if not arr or arr[0].tick != 0:
        arr.insert(0, _MgxcEvent(kind="beat", tick=0, value=4.0, value2=4))
    bar_starts: list[tuple[int, int, int, int]] = []
    acc = 0
    for i, b in enumerate(arr):
        num = max(1, int(round(b.value)))
        den = max(1, int(b.value2))
        if i > 0:
            prev_bar = arr[i - 1].tick
            prev_num = max(1, int(round(arr[i - 1].value)))
            prev_den = max(1, int(arr[i - 1].value2))
            acc += int(round(MGXC_TICKS_PER_BAR_4_4 * prev_num / prev_den * max(0, b.tick - prev_bar)))
        bar_starts.append((b.tick, acc, num, den))

    beat_by_bar = [(b.tick, max(1, int(round(b.value))), max(1, int(b.value2))) for b in arr]

    def _bar_len_at(bar_idx: int) -> int:
        chosen = beat_by_bar[0]
        for bb, num, den in beat_by_bar:
            if bb <= bar_idx:
                chosen = (bb, num, den)
            else:
                break
        _bb, num, den = chosen
        return int(round(MGXC_TICKS_PER_BAR_4_4 * num / den))

    def to_abs(bar: int, tick_in_bar: int) -> int:
        # BarTick offset may exceed current bar length and cross later bars with different signatures.
        chosen = bar_starts[0]
        for item in bar_starts:
            if item[0] <= bar:
                chosen = item
            else:
                break
        start_bar, start_tick, _num, _den = chosen
        abs_tick = int(start_tick)
        # advance full bars from beat-anchor to target bar
        for b in range(start_bar, bar):
            abs_tick += _bar_len_at(b)
        # advance tick within bar, spilling across later bars if needed
        rem = int(tick_in_bar)
        cur_bar = int(bar)
        while rem > 0:
            bl = _bar_len_at(cur_bar)
            take = min(rem, bl)
            abs_tick += take
            rem -= take
            if rem > 0:
                cur_bar += 1
        return abs_tick

    return to_abs


def _parse_ugc(path: Path) -> tuple[_MgxcMeta, list[_MgxcEvent], list[_MgxcNote]]:
    txt = _read_ugc_text(path)
    lines = txt.splitlines()
    meta = _MgxcMeta()
    events: list[_MgxcEvent] = []
    notes: list[_MgxcNote] = []
    in_body = False
    current_timeline = 0
    seq = 0

    bpm_raw: list[tuple[int, int, float]] = []
    smod_raw: list[tuple[int, int, float]] = []
    til_raw: list[tuple[int, int, int, float]] = []

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("'"):
            continue
        if ln.startswith("@ENDHEAD"):
            in_body = True
            continue
        if ln.startswith("@"):
            parts = ln.split("\t")
            cmd = parts[0][1:].upper()
            args = [p for p in parts[1:] if p != ""]
            if cmd == "TITLE" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "title": args[0].strip()})
            elif cmd == "ARTIST" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "artist": args[0].strip()})
            elif cmd == "DESIGN" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "designer": args[0].strip()})
            elif cmd == "SONGID" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "song_id": args[0].strip()})
            elif cmd == "BGM" and args:
                meta = _MgxcMeta(**{**meta.__dict__, "bgm_file": args[0].strip()})
            elif cmd == "DIFF" and args:
                try:
                    meta = _MgxcMeta(**{**meta.__dict__, "difficulty": int(args[0])})
                except Exception:
                    pass
            elif cmd == "CONST" and args:
                try:
                    meta = _MgxcMeta(**{**meta.__dict__, "level_const": float(args[0])})
                except Exception:
                    pass
            elif cmd == "FLAG" and len(args) >= 2:
                try:
                    k = args[0].strip().upper()
                    v = args[1].strip().upper()
                    if k == "SOFFSET":
                        meta = _MgxcMeta(**{**meta.__dict__, "soffset": v in ("TRUE", "1", "YES")})
                except Exception:
                    pass
            elif cmd == "BPM" and len(args) >= 2:
                try:
                    b, t = _parse_bar_tick(args[0])
                    bpm_raw.append((b, t, float(args[1])))
                except Exception:
                    pass
            elif cmd == "BEAT" and len(args) >= 3:
                try:
                    events.append(
                        _MgxcEvent(kind="beat", tick=int(args[0]), value=float(int(args[1])), value2=int(args[2]))
                    )
                except Exception:
                    pass
            elif cmd == "SPDMOD" and len(args) >= 2:
                try:
                    b, t = _parse_bar_tick(args[0])
                    smod_raw.append((b, t, float(args[1])))
                except Exception:
                    pass
            elif cmd == "TIL" and len(args) >= 3:
                try:
                    tid = int(args[0])
                    b, t = _parse_bar_tick(args[1])
                    til_raw.append((tid, b, t, float(args[2])))
                except Exception:
                    pass
            elif cmd == "USETIL" and args:
                try:
                    current_timeline = int(args[0])
                except Exception:
                    current_timeline = 0
            continue
        if not in_body or not ln.startswith("#"):
            continue

    beats = [e for e in events if e.kind == "beat"]
    to_abs = _build_bar_to_tick(beats)
    for b, t, v in bpm_raw:
        events.append(_MgxcEvent(kind="bpm", tick=to_abs(b, t), value=v))
    for b, t, v in smod_raw:
        events.append(_MgxcEvent(kind="smod", tick=to_abs(b, t), value=v))
    for tid, b, t, v in til_raw:
        events.append(_MgxcEvent(kind="til", tick=to_abs(b, t), value=v, value2=tid))

    parent_re = re.compile(r"^#([^:>]+):([^,]+)(?:,(.*))?$")
    child_re = re.compile(r"^#([0-9]+)>(.+)$")
    parent: dict[str, object] | None = None

    def add_note(
        typ: int,
        long_attr: int,
        direction: int,
        x: int,
        width: int,
        tick: int,
        height: int = 0,
        ex_attr: int = 0,
    ) -> None:
        nonlocal seq
        notes.append(
            _MgxcNote(
                typ=typ,
                long_attr=long_attr,
                direction=direction,
                ex_attr=int(ex_attr),
                x=max(0, int(x)),
                width=max(1, int(width)),
                height=int(height),
                tick=max(0, int(tick)),
                timeline=int(current_timeline),
                seq=seq,
            )
        )
        seq += 1

    def parse_parent_payload(payload: str, suffix: str | None = None) -> dict[str, object]:
        p = payload.strip()
        t = p[:1]
        d: dict[str, object] = {"t": t, "raw": p}
        if t in ("t", "d", "h", "s"):
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3])
        elif t in ("x", "f"):
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3]); d["dir"] = p[3:4]
        elif t == "a":
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3]); d["dd"] = p[3:5]
        elif t == "H":
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3])
        elif t in ("S", "C"):
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3]); d["hh"] = _b36_int(p[3:5])
            if t == "C":
                d["clr"] = p[5:6] if len(p) >= 6 else "0"
                try:
                    d["interval"] = int((suffix or "").strip()) if suffix not in (None, "", "$") else 0
                    if suffix == "$":
                        d["interval"] = -1
                except Exception:
                    d["interval"] = 0
        return d

    def parse_child_payload(payload: str) -> dict[str, object]:
        p = payload.strip()
        t = p[:1]
        d: dict[str, object] = {"t": t, "raw": p}
        if len(p) >= 3:
            d["x"] = _b36_int(p[1:2]); d["w"] = _b36_int(p[2:3])
        if len(p) >= 5:
            d["hh"] = _b36_int(p[3:5])
        return d

    def map_extap_dir(ch: str) -> int:
        return {"U": 2, "D": 3, "C": 4, "L": 6, "R": 5, "A": 11, "W": 12, "I": 13}.get(ch.upper(), 2)

    def map_flick_dir(ch: str) -> int:
        return {"L": 6, "R": 5, "A": 0}.get(ch.upper(), 0)

    def map_air_dir(code: str) -> int:
        u = code.upper()
        # UGC code uses player-perspective labels; align with observed official c2s direction.
        return {"UC": 0, "UL": 7, "UR": 8, "DC": 3, "DL": 10, "DR": 9}.get(u, 0)

    def flush_parent() -> None:
        nonlocal parent
        if not parent:
            return
        p = parent
        t = str(p["t"])
        st = int(p["tick"])
        x = int(p.get("x", 0))
        w = int(p.get("w", 1))
        children = list(p.get("children", []))
        if t == "t":
            add_note(0x01, 0x00, 0, x, w, st)
        elif t == "x":
            add_note(0x02, 0x00, map_extap_dir(str(p.get("dir", "U"))), x, w, st)
        elif t == "f":
            add_note(0x03, 0x00, map_flick_dir(str(p.get("dir", "A"))), x, w, st)
        elif t == "d":
            add_note(0x04, 0x00, 0, x, w, st)
        elif t == "a":
            add_note(0x07, 0x00, map_air_dir(str(p.get("dd", "UC"))), x, w, st)
        elif t == "h":
            add_note(0x05, 0x01, 0, x, w, st)
            if children:
                off, ch = children[-1]
                cx = int(ch.get("x", x)); cw = int(ch.get("w", w))
                add_note(0x05, 0x05, 0, cx, cw, st + int(off))
        elif t == "s":
            add_note(0x06, 0x01, 0, x, w, st)
            for i, (off, ch) in enumerate(children):
                cx = int(ch.get("x", x)); cw = int(ch.get("w", w))
                is_last = i == len(children) - 1
                la = 0x03 if str(ch.get("t", "s")) == "c" else (0x05 if is_last else 0x02)
                add_note(0x06, la, 0, cx, cw, st + int(off))
        elif t == "H":
            add_note(0x08, 0x01, 0, x, w, st)
            for i, (off, ch) in enumerate(children):
                is_last = i == len(children) - 1
                la = 0x05 if is_last else 0x02
                add_note(0x08, la, 0, int(ch.get("x", x)), int(ch.get("w", w)), st + int(off))
        elif t == "S":
            add_note(0x09, 0x01, 0, x, w, st, height=int(p.get("hh", 0)))
            for i, (off, ch) in enumerate(children):
                is_last = i == len(children) - 1
                la = 0x03 if str(ch.get("t", "s")) == "c" else (0x05 if is_last else 0x02)
                add_note(
                    0x09, la, 0, int(ch.get("x", x)), int(ch.get("w", w)), st + int(off), height=int(ch.get("hh", p.get("hh", 0)))
                )
        elif t == "C":
            interval = int(p.get("interval", 0))
            clr = str(p.get("clr", "0") or "0")[:1].upper()
            dir_code = ord(clr) if clr else ord("0")
            # '$' (encoded as -1) is treated as trace-like chain; interval==0 still keeps crash semantics.
            typ = 0x09 if interval < 0 else 0x0A
            add_note(typ, 0x01, dir_code, x, w, st, height=int(p.get("hh", 0)), ex_attr=interval)
            for i, (off, ch) in enumerate(children):
                is_last = i == len(children) - 1
                ch_t = str(ch.get("t", "c"))
                la = 0x03 if ch_t == "c" else (0x05 if is_last else 0x02)
                add_note(
                    typ,
                    la,
                    dir_code,
                    int(ch.get("x", x)),
                    int(ch.get("w", w)),
                    st + int(off),
                    height=int(ch.get("hh", p.get("hh", 0))),
                    ex_attr=interval,
                )
        parent = None

    for raw in lines:
        ln = raw.strip()
        if not ln:
            continue
        if ln.startswith("@USETIL"):
            parts = ln.split("\t")
            if len(parts) >= 2:
                try:
                    current_timeline = int(parts[1].strip())
                except Exception:
                    current_timeline = 0
            continue
        if not ln.startswith("#"):
            continue
        m_child = child_re.match(ln)
        if m_child:
            if parent is None:
                continue
            off = int(m_child.group(1))
            ch = parse_child_payload(m_child.group(2))
            parent.setdefault("children", []).append((off, ch))
            continue
        m_parent = parent_re.match(ln)
        if not m_parent:
            continue
        flush_parent()
        bar, inbar = _parse_bar_tick(m_parent.group(1))
        abs_tick = to_abs(bar, inbar)
        info = parse_parent_payload(m_parent.group(2), m_parent.group(3))
        info["tick"] = abs_tick
        info["children"] = []
        parent = info
    flush_parent()
    return meta, events, notes


def _try_read_ugc_designer_near(mgxc_path: Path) -> str:
    for p in _iter_ugc_paths_near_mgxc(mgxc_path):
        try:
            text = _read_ugc_text(p)
        except Exception:
            continue
        for ln in text.splitlines():
            if ln.startswith("@DESIGN\t"):
                v = ln.split("\t", 1)[1].strip()
                if v:
                    return v
    return ""


def _try_read_ugc_jacket_filename_near(mgxc_path: Path) -> str:
    """
    UGC 文本中的封面文件名，例如：@JACKET<TAB>arghena.jpg（@JACKET 与文件名之间为空白即可）。
    """
    tag = "@jacket"
    for p in _iter_ugc_paths_near_mgxc(mgxc_path):
        try:
            text = _read_ugc_text(p)
        except Exception:
            continue
        for raw in text.splitlines():
            ln = raw.strip()
            if len(ln) <= len(tag) or not ln.lower().startswith(tag):
                continue
            rest = ln[len(tag) :].lstrip()
            if not rest:
                continue
            fn = rest.strip()
            if fn:
                return fn
    return ""


def _resolve_jacket_path_from_ugc_near(mgxc_path: Path) -> Path | None:
    """按 ugc 中 @JACKET 指向的文件名，在 mgxc 同目录查找封面图。"""
    fn = _try_read_ugc_jacket_filename_near(mgxc_path)
    if not fn:
        return None
    safe = Path(fn.replace("\\", "/")).name
    if not safe or safe in (".", ".."):
        return None
    base = mgxc_path.parent.resolve()
    p = (mgxc_path.parent / safe).resolve()
    if not p.is_file():
        return None
    try:
        p.relative_to(base)
    except ValueError:
        return None
    return p


def _derive_music_id(meta: _MgxcMeta, mgxc_path: Path) -> int:
    s = (meta.song_id or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if digits:
        try:
            return max(1, int(digits) % 10000)
        except Exception:
            pass
    return (zlib.crc32(mgxc_path.as_posix().encode("utf-8")) % 9999) + 1


def _resolve_mgxc_audio_file(meta: _MgxcMeta, mgxc_path: Path) -> Path | None:
    base = mgxc_path.parent
    if meta.bgm_file:
        p = (base / meta.bgm_file).resolve()
        if p.exists() and p.is_file():
            return p
    for ext in (".ogg", ".wav", ".flac", ".mp3"):
        p = mgxc_path.with_suffix(ext)
        if p.exists() and p.is_file():
            return p
    cands = sorted(
        p for p in base.glob("*") if p.is_file() and p.suffix.lower() in (".ogg", ".wav", ".flac", ".mp3")
    )
    return cands[0] if cands else None


def _emit_c2s_from_semantic(
    *,
    out: Path,
    meta: _MgxcMeta,
    events: list[_MgxcEvent],
    raw_notes: list[_MgxcNote],
    source_path: Path,
    creator_fallback: str,
) -> tuple[Path, str]:
    min_note_tick = min((n.tick for n in raw_notes), default=0)
    base_shift = max(0, MGXC_TICKS_PER_BAR_4_4 - int(min_note_tick))
    if base_shift > 0:
        raw_notes = [
            _MgxcNote(
                typ=n.typ,
                long_attr=n.long_attr,
                direction=n.direction,
                ex_attr=n.ex_attr,
                x=n.x,
                width=n.width,
                height=n.height,
                tick=n.tick + base_shift,
                timeline=n.timeline,
                seq=n.seq,
            )
            for n in raw_notes
        ]

    if meta.soffset:
        shift = MGXC_TICKS_PER_BAR_4_4
        events = [
            _MgxcEvent(kind=e.kind, tick=(e.tick + shift) if e.tick > 0 and e.kind != "beat" else e.tick, value=e.value, value2=e.value2)
            for e in events
        ]
        raw_notes = [
            _MgxcNote(
                typ=n.typ,
                long_attr=n.long_attr,
                direction=n.direction,
                ex_attr=n.ex_attr,
                x=n.x,
                width=n.width,
                height=n.height,
                tick=n.tick + shift,
                timeline=n.timeline,
                seq=n.seq,
            )
            for n in raw_notes
        ]

    if not events:
        events = [_MgxcEvent(kind="bpm", tick=0, value=120.0)]

    bpm_def = sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick)[0].value
    scale = 384.0 / float(MGXC_TICKS_PER_BAR_4_4)

    defs: list[BpmSetting | MeterSetting | DcmSetting | TimelineSpeedSetting] = []
    bpm_events = sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick)
    for e in bpm_events:
        obj = BpmSetting()
        t = max(0, int(round(e.tick * scale)))
        obj.measure = t // 384
        obj.tick = t % 384
        obj.bpm = float(e.value)
        defs.append(obj)

    beat_events = sorted((e for e in events if e.kind == "beat"), key=lambda x: x.tick)
    if not beat_events or beat_events[0].tick != 0:
        beat_events.insert(0, _MgxcEvent(kind="beat", tick=0, value=4.0, value2=4))

    beat_ticks: list[tuple[int, int, int]] = []
    acc = 0
    for i, b in enumerate(beat_events):
        num = max(1, int(round(b.value)))
        den = max(1, int(b.value2))
        if i > 0:
            prev_bar = beat_events[i - 1].tick
            prev_num = max(1, int(round(beat_events[i - 1].value)))
            prev_den = max(1, int(beat_events[i - 1].value2))
            bars = max(0, b.tick - prev_bar)
            acc += int(round(MGXC_TICKS_PER_BAR_4_4 * prev_num / prev_den * bars))
        beat_ticks.append((acc, num, den))

    for bt, num, den in beat_ticks:
        m = MeterSetting()
        t = max(0, int(round(bt * scale)))
        m.measure = t // 384
        m.tick = t % 384
        m.signature = (num, den)
        defs.append(m)

    smod_events = sorted((e for e in events if e.kind == "smod"), key=lambda x: x.tick)
    if smod_events:
        last_note_tick_480 = max((n.tick for n in raw_notes), default=0)
        for i, s in enumerate(smod_events):
            start = max(0, int(round(s.tick * scale)))
            if i + 1 < len(smod_events):
                end = max(0, int(round(smod_events[i + 1].tick * scale)))
            else:
                end = max(start + 1, int(round(last_note_tick_480 * scale)))
            if end <= start or abs(float(s.value) - 1.0) < 1e-6:
                continue
            sp = DcmSetting()
            sp.measure = start // 384
            sp.tick = start % 384
            sp.length = end - start
            sp.speed = float(s.value)
            defs.append(sp)

    til_events = sorted((e for e in events if e.kind == "til"), key=lambda x: (x.value2, x.tick))
    if til_events:
        by_timeline: dict[int, list[_MgxcEvent]] = {}
        for e in til_events:
            by_timeline.setdefault(int(e.value2), []).append(e)
        for tid, arr in by_timeline.items():
            arr = sorted(arr, key=lambda x: x.tick)
            last_timeline_tick_480 = max(
                (n.tick for n in raw_notes if int(n.timeline) == int(tid)),
                default=max((n.tick for n in raw_notes), default=0),
            )
            for i, e in enumerate(arr):
                start = max(0, int(round(e.tick * scale)))
                if i + 1 < len(arr):
                    end = max(0, int(round(arr[i + 1].tick * scale)))
                else:
                    end = max(start + 1, int(round(last_timeline_tick_480 * scale)))
                if end <= start or abs(float(e.value) - 1.0) < 1e-6:
                    continue
                sp = TimelineSpeedSetting()
                sp.measure = start // 384
                sp.tick = start % 384
                sp.length = end - start
                sp.speed = float(e.value)
                sp.timeline = int(tid)
                defs.append(sp)

    converted_notes = sorted(raw_notes, key=lambda x: (x.tick, x.seq))
    ground_anchors: list[_GroundAnchor] = []

    hold_begins: list[_MgxcNote] = []
    slide_chain: list[_MgxcNote] = []
    slide_started = False
    for n in converted_notes:
        t = max(0, int(round(n.tick * scale)))
        lane = int(n.x)
        width = max(1, int(n.width))
        if n.typ in (0x01, 0x02, 0x03):
            ground_anchors.append(_GroundAnchor(tick=t, lane=lane, width=width, linkage="TAP"))
        elif n.typ == 0x05:
            if n.long_attr == 0x01:
                hold_begins.append(n)
            elif n.long_attr == 0x05 and hold_begins:
                st = hold_begins.pop(0)
                st_t = max(0, int(round(st.tick * scale)))
                ground_anchors.append(_GroundAnchor(tick=st_t, lane=int(st.x), width=max(1, int(st.width)), linkage="HLD"))
        elif n.typ == 0x06:
            if n.long_attr == 0x01:
                slide_chain = [n]
                slide_started = True
            elif slide_started and n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06):
                slide_chain.append(n)
                if n.long_attr in (0x05, 0x06):
                    for p in slide_chain[:-1]:
                        p_t = max(0, int(round(p.tick * scale)))
                        ground_anchors.append(
                            _GroundAnchor(tick=p_t, lane=int(p.x), width=max(1, int(p.width)), linkage="SLD")
                        )
                    slide_started = False
                    slide_chain = []

    def _resolve_air_linkage(tick: int, lane: int, width: int, fallback: str = "TAP") -> str:
        same_cover: list[tuple[int, _GroundAnchor]] = []
        prev_cover: list[tuple[int, _GroundAnchor]] = []
        prev_any: list[tuple[int, _GroundAnchor]] = []
        for a in ground_anchors:
            a_l = a.lane
            a_r = a.lane + a.width
            n_l = lane
            n_r = lane + width
            cover = (a_l <= n_l) and (a_r >= n_r)
            dt = tick - a.tick
            if dt == 0 and cover:
                same_cover.append((abs(a.lane - lane), a))
            elif dt >= 0 and cover:
                prev_cover.append((dt * 100 + abs(a.lane - lane), a))
            elif dt >= 0:
                prev_any.append((dt * 100 + abs(a.lane - lane), a))
        if same_cover:
            same_cover.sort(key=lambda x: x[0])
            return same_cover[0][1].linkage
        if prev_cover:
            prev_cover.sort(key=lambda x: x[0])
            return prev_cover[0][1].linkage
        if prev_any:
            prev_any.sort(key=lambda x: x[0])
            return prev_any[0][1].linkage
        return fallback

    def _map_extap_effect(direction: int) -> str:
        return {2: "UP", 3: "DW", 4: "CE", 5: "LS", 6: "RS", 11: "LC", 12: "RC", 13: "BS", 14: "CE"}.get(direction, "UP")

    def _map_flick_dir(direction: int) -> str:
        return "R" if direction in (6, 8, 10, 12) else "L"

    notes_out: list[
        TapNote
        | ChargeNote
        | FlickNote
        | MineNote
        | HoldNote
        | SlideNote
        | AirNote
        | AirHold
        | HxdNote
        | AscNote
        | AsdNote
        | AldNote
        | SxcNote
        | SxdNote
    ] = []
    active_holds: list[_MgxcNote] = []
    active_air_holds: list[_MgxcNote] = []
    active_air_crash: list[_MgxcNote] = []
    active_slides: list[_MgxcNote] = []
    slide_start: _MgxcNote | None = None

    def _emit_ald_segment(st: _MgxcNote, ed: _MgxcNote) -> None:
        st_t = max(0, int(round(st.tick * scale)))
        end_t = max(0, int(round(ed.tick * scale)))
        if end_t <= st_t:
            return
        x = AldNote()
        x.measure = st_t // 384
        x.tick = st_t % 384
        x.lane = int(st.x)
        x.width = max(1, int(st.width))
        x.mode = 0
        x.start_height = max(1.0, float(int(st.height) / 10.0 if int(st.height) else 1.0))
        x.length = end_t - st_t
        x.end_lane = int(ed.x)
        x.end_width = max(1, int(ed.width))
        x.end_height = max(1.0, float(int(ed.height) / 10.0 if int(ed.height) else 1.0))
        clr = chr(int(st.direction)) if int(st.direction) > 0 else "0"
        x.color = {
            "0": "DEF",
            "1": "RED",
            "2": "ORN",
            "3": "YEL",
            "4": "GRN",
            "5": "CYN",
            "6": "AQA",
            "7": "BLU",
            "8": "VLT",
            "9": "PPL",
            "A": "GRY",
            "Y": "PPL",
            "B": "AQA",
            "C": "NON",
            "D": "BLK",
            "Z": "NON",
        }.get(clr.upper(), "DEF")
        notes_out.append(x)
        interval = int(st.ex_attr)
        if interval > 0:
            for tt in range(st_t + interval, end_t, interval):
                s = SlaNote()
                s.measure = tt // 384
                s.tick = tt % 384
                s.lane = int(st.x)
                s.width = max(1, int(st.width))
                s.a = max(1, int(st.width))
                s.b = 1
                s.c = 1
                notes_out.append(s)
    for n in converted_notes:
        t = max(0, int(round(n.tick * scale)))
        lane = int(n.x)
        width = max(1, int(n.width))
        if n.typ == 0x01:
            x = TapNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; notes_out.append(x)
        elif n.typ == 0x02:
            x = ChargeNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; x.effect = _map_extap_effect(int(n.direction)); notes_out.append(x)
        elif n.typ == 0x03:
            x = FlickNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; x.direction_tag = _map_flick_dir(int(n.direction)); notes_out.append(x)
        elif n.typ == 0x04:
            x = MineNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width; notes_out.append(x)
        elif n.typ == 0x07:
            x = AirNote(); x.measure = t // 384; x.tick = t % 384; x.lane = lane; x.width = width
            if n.direction in (7,): x.direction = -1; x.isUp = True
            elif n.direction in (8,): x.direction = 1; x.isUp = True
            elif n.direction in (9,): x.direction = -1; x.isUp = False
            elif n.direction in (10,): x.direction = 1; x.isUp = False
            elif n.direction in (3,): x.direction = 0; x.isUp = False
            else: x.direction = 0; x.isUp = True
            x.linkage = _resolve_air_linkage(t, lane, width, fallback="TAP")
            notes_out.append(x)
        elif n.typ == 0x05:
            if n.long_attr == 0x01:
                active_holds.append(n)
            elif n.long_attr == 0x05 and active_holds:
                st = active_holds.pop(0)
                st_t = max(0, int(round(st.tick * scale))); end_t = t
                if end_t <= st_t: continue
                x = HoldNote(); x.measure = st_t // 384; x.tick = st_t % 384; x.lane = int(st.x); x.width = max(1, int(st.width)); x.length = end_t - st_t; notes_out.append(x)
        elif n.typ == 0x08:
            if n.long_attr == 0x01:
                active_air_holds.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_holds:
                st = active_air_holds[-1]
                st_t = max(0, int(round(st.tick * scale))); end_t = max(0, int(round(n.tick * scale)))
                if end_t <= st_t: continue
                x = HxdNote()
                x.measure = st_t // 384
                x.tick = st_t % 384
                x.lane = int(st.x)
                x.width = max(1, int(st.width))
                x.length = end_t - st_t
                x.direction_tag = "UP"
                notes_out.append(x)
                active_air_holds[-1] = n
                if n.long_attr in (0x05, 0x06): active_air_holds.pop()
        elif n.typ == 0x09:
            if n.long_attr == 0x01:
                active_air_holds.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_holds:
                st = active_air_holds[-1]
                st_t = max(0, int(round(st.tick * scale)))
                end_t = max(0, int(round(n.tick * scale)))
                if end_t <= st_t:
                    continue
                linkage = _resolve_air_linkage(st_t, int(st.x), max(1, int(st.width)), fallback="TAP")
                # UGC compact encoding commonly maps to PenguinTools default air height 5.0 for ASC/ASD chains.
                h0 = 5.0
                h1 = 5.0
                is_final = n.long_attr in (0x05, 0x06)
                prev_is_start = st.long_attr == 0x01
                x = AsdNote() if is_final else AscNote()
                x.measure = st_t // 384
                x.tick = st_t % 384
                x.lane = int(st.x)
                x.width = max(1, int(st.width))
                x.linkage = linkage if prev_is_start else "ASC"
                x.start_height = h0
                x.length = end_t - st_t
                x.end_lane = int(n.x)
                x.end_width = max(1, int(n.width))
                x.end_height = h1
                x.color = "DEF"
                notes_out.append(x)
                active_air_holds[-1] = n
                if n.long_attr in (0x05, 0x06):
                    active_air_holds.pop()
        elif n.typ == 0x0A:
            if n.long_attr == 0x01:
                if active_air_crash:
                    prev = active_air_crash[-1]
                    prev_t = max(0, int(round(prev.tick * scale)))
                    cur_t = max(0, int(round(n.tick * scale)))
                    if (
                        int(prev.x) == int(n.x)
                        and max(1, int(prev.width)) == max(1, int(n.width))
                        and 0 < (cur_t - prev_t) <= 384
                        and int(prev.ex_attr) > 0
                    ):
                        _emit_ald_segment(prev, n)
                active_air_crash.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_crash:
                st = active_air_crash[-1]
                _emit_ald_segment(st, n)
                active_air_crash[-1] = n
                if n.long_attr in (0x05, 0x06): active_air_crash.pop()
        elif n.typ == 0x06:
            if n.long_attr == 0x01:
                slide_start = n
                active_slides = [n]
            elif slide_start is not None and n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06):
                active_slides.append(n)
                if n.long_attr in (0x05, 0x06):
                    for i in range(len(active_slides) - 1):
                        a = active_slides[i]; b = active_slides[i + 1]
                        at = max(0, int(round(a.tick * scale))); bt = max(0, int(round(b.tick * scale)))
                        if bt <= at: continue
                        x = SlideNote(); x.measure = at // 384; x.tick = at % 384; x.lane = int(a.x); x.width = max(1, int(a.width)); x.length = bt - at; x.end_lane = int(b.x); x.end_width = max(1, int(b.width)); x.is_curve = b.long_attr in (0x03, 0x04, 0x06); notes_out.append(x)
                    slide_start = None
                    active_slides = []

    def _note_order_key(obj: object) -> int:
        if isinstance(obj, (SxcNote, SxdNote)):
            return 8
        if isinstance(obj, (AscNote, AsdNote)):
            return 9
        if isinstance(obj, (TapNote, ChargeNote, FlickNote, MineNote)):
            return 10
        if isinstance(obj, HoldNote):
            return 20
        if isinstance(obj, SlideNote):
            return 30
        if isinstance(obj, AirNote):
            return 50
        if isinstance(obj, HxdNote):
            return 60
        if isinstance(obj, AldNote):
            return 70
        if isinstance(obj, SlaNote):
            return 75
        if isinstance(obj, AirHold):
            return 80
        return 999

    notes_out.sort(
        key=lambda o: (
            int(getattr(o, "measure", 0)),
            int(getattr(o, "tick", 0)),
            _note_order_key(o),
            int(getattr(o, "lane", 0)),
            int(getattr(o, "width", 0)),
            str(o),
        )
    )

    creator_name = (meta.designer or "").strip() or (meta.artist or "").strip() or creator_fallback
    b0 = beat_events[0]
    met_def_hdr = (max(1, int(b0.value2)), max(1, int(round(b0.value))))
    text = create_file(defs, notes_out, creator=creator_name, bpm_def=float(bpm_def), met_def=met_def_hdr, include_footer=False)
    out.write_text(text, encoding="utf-8")
    return out, "python"


def convert_pgko_chart_pick_to_c2s(pick: PgkoChartPick) -> Path:
    out, _backend = convert_pgko_chart_pick_to_c2s_with_backend(pick)
    return out


def convert_pgko_chart_pick_to_c2s_with_backend(pick: PgkoChartPick) -> tuple[Path, str]:
    """
    内置转码（第二版）：
    - 支持 mgxc -> c2s（BPM/TAP/HOLD/SLIDE + Air/AirHold 基础映射）
    - ugc 通过同目录/邻近 mgxc 回退
    """
    source_path = pick.path
    source_ext = pick.ext.lower().strip(".")

    if source_ext == "ugc":
        out = source_path.with_suffix(".c2s")
        meta, events, raw_notes = _parse_ugc(source_path)
        return _emit_c2s_from_semantic(
            out=out,
            meta=meta,
            events=events,
            raw_notes=raw_notes,
            source_path=source_path,
            creator_fallback="UGC import",
        )

    if source_ext != "mgxc":
        nearby = sorted(
            p.name
            for p in source_path.parent.glob("*")
            if p.is_file() and p.suffix.lower() in (".mgxc", ".ugc")
        )
        nearby_tip = ", ".join(nearby) if nearby else "（同目录未找到 mgxc/ugc）"
        raise NotImplementedError(
            f"暂不支持 {pick.ext} 直转，且未找到可处理的输入。\n"
            f"源文件：{source_path}\n"
            f"同目录可见谱面文件：{nearby_tip}"
        )

    out = source_path.with_suffix(".c2s")
    try:
        convert_mgxc_with_penguin_bridge(input_mgxc=source_path, output_c2s=out)
        return out, "cs"
    except Exception:
        pass

    meta, events, raw_notes = _parse_mgxc(source_path)
    return _emit_c2s_from_semantic(
        out=out,
        meta=meta,
        events=events,
        raw_notes=raw_notes,
        source_path=source_path,
        creator_fallback="MGXC import",
    )


def convert_pgko_audio_to_chuni_from_pick(
    pick: PgkoChartPick, *, music_id_override: int | None = None
) -> dict[str, object]:
    """
    Reuse pjsk audio pipeline for pgko:
    - decode to 48k wav by ffmpeg (no forced 9s trim)
    - build chuni cueFile/musicXXXX.acb/.awb
    - preview window uses mgxc meta wvp0/wvp1
    """
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise RuntimeError("音频转码需要 mgxc（或可回退到同目录 mgxc）")
        source_path = fb

    meta, _events, _notes = _parse_mgxc(source_path)
    src_audio = _resolve_mgxc_audio_file(meta, source_path)
    if src_audio is None:
        raise FileNotFoundError(f"未找到可用音频文件（mgxc={source_path.name}）")

    music_id = int(music_id_override) if music_id_override is not None else _derive_music_id(meta, source_path)
    # 仅当作者在 mgxc 中明确填写了 wvp0/wvp1 时才使用；否则统一默认 0-30 秒
    if meta.has_preview_start and meta.has_preview_stop:
        preview_start = max(0.0, float(meta.preview_start_sec))
        preview_stop = float(meta.preview_stop_sec)
        if preview_stop <= preview_start + 0.05:
            preview_start, preview_stop = 0.0, 30.0
    else:
        preview_start, preview_stop = 0.0, 30.0

    cache_root = source_path.parent
    result = pjsk_ac.try_pipeline_pjsk_audio_to_chuni(
        src_audio=src_audio,
        music_id=music_id,
        cache_root=cache_root,
        trim_leading_sec=0.0,
        preview_start_sec=preview_start,
        preview_stop_sec=preview_stop,
    )
    if result is None:
        raise RuntimeError("音频转码失败：缺少 PyCriCodecsEx 或打包阶段失败")
    result["musicId"] = music_id
    result["audioSource"] = str(src_audio)
    result["previewStartSec"] = preview_start
    result["previewStopSec"] = preview_stop
    return result


@dataclass(frozen=True)
class PgkoInstallOptions:
    music_id: int
    stage_id: int
    stage_str: str
    create_unlock_event: bool = True


def suggest_next_pgko_music_id(acus_root: Path, *, start: int = 6000) -> int:
    return next_chuni_music_id(acus_root, start=start)


def read_pgko_meta_for_pick(pick: PgkoChartPick) -> dict[str, object]:
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise RuntimeError("读取元数据需要 mgxc（或可回退到同目录 mgxc）")
        source_path = fb
    meta, _events, _notes = _parse_mgxc(source_path)
    return {
        "sourcePath": str(source_path),
        "title": meta.title,
        "artist": meta.artist,
        "designer": meta.designer,
        "difficulty": int(meta.difficulty),
        "levelConst": meta.level_const,
    }


def _slot_from_difficulty(diff: int) -> str:
    return {
        0: "BASIC",
        1: "ADVANCED",
        2: "EXPERT",
        3: "MASTER",
        4: "WORLD'S END",
        5: "ULTIMA",
    }.get(int(diff), "MASTER")


def _slot_file_index(slot: str) -> int:
    mapping = {
        "BASIC": 0,
        "ADVANCED": 1,
        "EXPERT": 2,
        "MASTER": 3,
        "ULTIMA": 4,
        "WORLD'S END": 5,
    }
    return mapping.get(slot, 3)


def _const_to_level_pair(v: float | None) -> tuple[int, int]:
    if v is None:
        return (13, 0)
    lv = int(max(1, min(15, int(v))))
    dec = int(max(0, min(99, round((float(v) - int(v)) * 100))))
    return lv, dec


def _collect_bundle_mgxc_files(primary_mgxc: Path) -> list[Path]:
    root = primary_mgxc.parent
    files = sorted(p.resolve() for p in root.glob("**/*.mgxc") if p.is_file())
    if not files:
        return [primary_mgxc.resolve()]
    return files


def _write_worlds_end_unlock_event(acus_root: Path, *, event_id: int, music_id: int, music_title: str) -> None:
    # Reuse existing writer, then patch musicType/name to WORLD'S END flavor.
    p = write_ultima_unlock_event(
        acus_root,
        event_id=int(event_id),
        music_id=int(music_id),
        music_title=music_title,
    )
    import xml.etree.ElementTree as ET

    root = ET.parse(p).getroot()
    n = root.find("./name/str")
    if n is not None:
        n.text = "WE解禁"
    mt = root.find("./substances/music/musicType")
    if mt is not None:
        mt.text = "3"
    ET.indent(root)  # type: ignore[attr-defined]
    ET.ElementTree(root).write(p, encoding="utf-8", xml_declaration=True)


def install_pgko_pick_to_acus(
    *,
    pick: PgkoChartPick,
    acus_root: Path,
    tool_path: Path | None,
    opts: PgkoInstallOptions,
) -> dict[str, object]:
    source_path = pick.path
    if pick.ext.lower().strip(".") != "mgxc":
        fb = _find_fallback_mgxc(source_path)
        if fb is None:
            raise RuntimeError("安装到 ACUS 需要 mgxc（或可回退到同目录 mgxc）")
        source_path = fb

    base_meta, _events, _notes = _parse_mgxc(source_path)

    mid = int(opts.music_id)
    mdir = acus_root / "music" / f"music{mid:04d}"
    if mdir.exists():
        raise FileExistsError(f"乐曲 ID 已存在：{mid}")
    mdir.mkdir(parents=True, exist_ok=True)

    # Multi-difficulty import: consume all mgxc files in the same bundle root.
    mgxc_files = _collect_bundle_mgxc_files(source_path)
    chosen_by_slot: dict[str, tuple[Path, _MgxcMeta]] = {}
    for mg in mgxc_files:
        try:
            mm, _e2, _n2 = _parse_mgxc(mg)
        except Exception:
            continue
        slot = _slot_from_difficulty(int(mm.difficulty))
        prev = chosen_by_slot.get(slot)
        if prev is None:
            chosen_by_slot[slot] = (mg, mm)
            continue
        prev_const = prev[1].level_const if prev[1].level_const is not None else -1.0
        cur_const = mm.level_const if mm.level_const is not None else -1.0
        if cur_const > prev_const:
            chosen_by_slot[slot] = (mg, mm)

    if not chosen_by_slot:
        raise RuntimeError("未找到可用 mgxc 难度文件。")

    slot_map: dict[str, Path] = {}
    levels_by_type: dict[str, tuple[int, int]] = {}
    for slot, (mg, mm) in chosen_by_slot.items():
        c2s_out = convert_pgko_chart_pick_to_c2s(PgkoChartPick(path=mg, ext="mgxc"))
        slot_idx = _slot_file_index(slot)
        c2s_dst = mdir / f"{mid:04d}_{slot_idx:02d}.c2s"
        c2s_dst.write_bytes(c2s_out.read_bytes())
        slot_map[slot] = c2s_dst
        levels_by_type[slot] = _const_to_level_pair(mm.level_const)

    # 封面一律按邻近 ugc 的 @JACKET 路径选取；与是否走 PenguinBridge 转 c2s 无关，并始终在本步骤重转 DDS（覆盖同名文件）。
    jacket_raw = _resolve_jacket_path_from_ugc_near(source_path)
    if jacket_raw is None:
        declared = _try_read_ugc_jacket_filename_near(source_path)
        if not declared:
            raise FileNotFoundError(
                "导入 pgko：请在邻近 ugc 中声明 @JACKET <封面文件名>，"
                "并把该图片放在与 mgxc 同一目录。"
                "即使已用外部 exe 生成 c2s，封面仍须由此处按 ugc 指定文件重新生成。"
            )
        raise FileNotFoundError(
            f"ugc 中 @JACKET 指向 {declared!r}，但在 mgxc 同目录下未找到该文件。"
        )
    jacket_name = f"CHU_UI_Jacket_{mid:04d}.dds"
    jacket_dds = mdir / jacket_name
    tmp_sq: Path | None = None
    try:
        tmp_sq = _prepare_square_jacket_png(jacket_raw, JACKET_BC3_EDGE, tool_path)
        convert_to_bc3_dds(
            tool_path=tool_path, input_image=tmp_sq, output_dds=jacket_dds
        )
    finally:
        if tmp_sq is not None:
            tmp_sq.unlink(missing_ok=True)

    title = (base_meta.title or source_path.stem or str(mid)).strip()
    artist = ((base_meta.artist or "").strip() or "pgko")
    sort_name = title
    tree = build_music_xml(
        chuni_id=mid,
        title=title,
        artist=artist,
        sort_name=sort_name,
        stage_id=int(opts.stage_id),
        stage_str=opts.stage_str.strip() or "Invalid",
        genre_id=-1,
        genre_str="Invalid",
        jacket_rel=jacket_name,
        slot_map=slot_map,
        levels_by_type=levels_by_type,
    )
    import xml.etree.ElementTree as ET
    rtag = tree.getroot().find("./releaseTagName")
    if rtag is not None:
        rid = rtag.find("id")
        rstr = rtag.find("str")
        if rid is not None:
            rid.text = str(PGKO_RELEASE_TAG_ID)
        if rstr is not None:
            rstr.text = PGKO_RELEASE_TAG_STR

    ET.indent(tree.getroot(), space="  ")  # type: ignore[attr-defined]
    tree.write(mdir / "Music.xml", encoding="utf-8", xml_declaration=True)
    append_music_sort(acus_root, mid)

    audio_ret = convert_pgko_audio_to_chuni_from_pick(
        PgkoChartPick(path=source_path, ext="mgxc"),
        music_id_override=mid,
    )
    cue_src = source_path.parent / str(audio_ret.get("cueDirectory", ""))
    cue_dst = acus_root / "cueFile" / f"cueFile{mid:06d}"
    import shutil

    if cue_dst.exists():
        shutil.rmtree(cue_dst, ignore_errors=True)
    cue_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(cue_src, cue_dst, dirs_exist_ok=True)

    created_event_id: int | None = None
    has_ult = "ULTIMA" in slot_map
    has_we = "WORLD'S END" in slot_map
    if opts.create_unlock_event and (has_ult or has_we):
        created_event_id = next_custom_event_id(acus_root, start=70000)
        if has_ult:
            write_ultima_unlock_event(
                acus_root,
                event_id=created_event_id,
                music_id=mid,
                music_title=title,
            )
        else:
            _write_worlds_end_unlock_event(
                acus_root,
                event_id=created_event_id,
                music_id=mid,
                music_title=title,
            )
        append_event_sort(acus_root, created_event_id)

    return {
        "musicId": mid,
        "slots": ",".join(sorted(slot_map.keys())),
        "musicXml": str(mdir / "Music.xml"),
        "c2sDir": str(mdir),
        "cueDir": str(cue_dst),
        "eventId": created_event_id,
    }

