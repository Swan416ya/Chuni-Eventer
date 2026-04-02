from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from . import pjsk_audio_chuni as pjsk_ac
from .dds_convert import convert_to_bc3_dds
from .pjsk_acus_install import (
    append_event_sort,
    append_music_sort,
    build_music_xml,
    next_chuni_music_id,
    next_custom_event_id,
    write_ultima_unlock_event,
)
from ._suspect.c2s_emit import (
    AirHold,
    AirNote,
    BpmSetting,
    ChargeNote,
    FlickNote,
    HoldNote,
    MeterSetting,
    MineNote,
    SlideNote,
    SpeedSetting,
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


def _try_read_ugc_designer_near(mgxc_path: Path) -> str:
    candidates: list[Path] = []
    same = mgxc_path.with_suffix(".ugc")
    if same.exists() and same.is_file():
        candidates.append(same)
    candidates.extend(sorted(p for p in mgxc_path.parent.glob("*.ugc") if p.is_file()))
    seen: set[Path] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for ln in text.splitlines():
            if ln.startswith("@DESIGN\t"):
                v = ln.split("\t", 1)[1].strip()
                if v:
                    return v
    return ""


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


def convert_pgko_chart_pick_to_c2s(pick: PgkoChartPick) -> Path:
    """
    内置转码（第二版）：
    - 支持 mgxc -> c2s（BPM/TAP/HOLD/SLIDE + Air/AirHold 基础映射）
    - ugc 通过同目录/邻近 mgxc 回退
    """
    source_path = pick.path
    source_ext = pick.ext.lower().strip(".")
    if source_ext != "mgxc":
        fallback = _find_fallback_mgxc(source_path)
        if fallback is not None:
            source_path = fallback
            source_ext = "mgxc"
        else:
            nearby = sorted(
                p.name
                for p in source_path.parent.glob("*")
                if p.is_file() and p.suffix.lower() in (".mgxc", ".ugc")
            )
            nearby_tip = ", ".join(nearby) if nearby else "（同目录未找到 mgxc/ugc）"
            raise NotImplementedError(
                f"暂不支持 {pick.ext} 的直接内置转码，且未找到可回退的 mgxc。\n"
                f"源文件：{source_path}\n"
                f"同目录可见谱面文件：{nearby_tip}"
            )

    meta, events, raw_notes = _parse_mgxc(source_path)
    if not events:
        events = [_MgxcEvent(kind="bpm", tick=0, value=120.0)]

    bpm_def = sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick)[0].value
    scale = 384.0 / 480.0

    defs: list[BpmSetting | MeterSetting | SpeedSetting | TimelineSpeedSetting] = []
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
            acc += int(round(480 * prev_num / prev_den * bars))
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
            if end <= start:
                continue
            if abs(float(s.value) - 1.0) < 1e-6:
                continue
            sp = SpeedSetting()
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
                if end <= start:
                    continue
                if abs(float(e.value) - 1.0) < 1e-6:
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

    # pass1: build coarse ground anchors for air linkage decisions
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
                ground_anchors.append(
                    _GroundAnchor(
                        tick=st_t,
                        lane=int(st.x),
                        width=max(1, int(st.width)),
                        linkage="HLD",
                    )
                )
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
                            _GroundAnchor(
                                tick=p_t,
                                lane=int(p.x),
                                width=max(1, int(p.width)),
                                linkage="SLD",
                            )
                        )
                    slide_started = False
                    slide_chain = []

    def _resolve_air_linkage(tick: int, lane: int, width: int, fallback: str = "TAP") -> str:
        # prefer same-tick covering anchor, then nearest previous covering, finally nearest previous any
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
        # Align with PenguinTools ExTap direction mapping
        return {
            2: "UP",  # Up
            3: "DW",  # Down
            4: "CE",  # Center
            5: "LS",  # Left Side
            6: "RS",  # Right Side
            11: "LC",  # RotateLeft
            12: "RC",  # RotateRight
            13: "BS",  # InOut
            14: "CE",  # OutIn -> CE
        }.get(direction, "UP")

    def _map_flick_dir(direction: int) -> str:
        if direction in (6, 8, 10, 12):  # right-ish
            return "R"
        return "L"

    notes_out: list[TapNote | ChargeNote | FlickNote | MineNote | HoldNote | SlideNote | AirNote | AirHold] = []
    active_holds: list[_MgxcNote] = []
    active_air_holds: list[_MgxcNote] = []
    active_air_crash: list[_MgxcNote] = []
    active_slides: list[_MgxcNote] = []
    slide_start: _MgxcNote | None = None
    for n in converted_notes:
        t = max(0, int(round(n.tick * scale)))
        lane = int(n.x)
        width = max(1, int(n.width))
        if n.typ == 0x01:  # tap
            x = TapNote()
            x.measure = t // 384
            x.tick = t % 384
            x.lane = lane
            x.width = width
            notes_out.append(x)
        elif n.typ == 0x02:  # extap -> chr
            x = ChargeNote()
            x.measure = t // 384
            x.tick = t % 384
            x.lane = lane
            x.width = width
            x.effect = _map_extap_effect(int(n.direction))
            notes_out.append(x)
        elif n.typ == 0x03:  # flick
            x = FlickNote()
            x.measure = t // 384
            x.tick = t % 384
            x.lane = lane
            x.width = width
            x.direction_tag = _map_flick_dir(int(n.direction))
            notes_out.append(x)
        elif n.typ == 0x04:  # damage
            x = MineNote()
            x.measure = t // 384
            x.tick = t % 384
            x.lane = lane
            x.width = width
            notes_out.append(x)
        elif n.typ == 0x07:  # air
            x = AirNote()
            x.measure = t // 384
            x.tick = t % 384
            x.lane = lane
            x.width = width
            # mgxc direction -> c2s direction
            if n.direction in (7,):  # UpLeft
                x.direction = -1
                x.isUp = True
            elif n.direction in (8,):  # UpRight
                x.direction = 1
                x.isUp = True
            elif n.direction in (9,):  # DownLeft
                x.direction = -1
                x.isUp = False
            elif n.direction in (10,):  # DownRight
                x.direction = 1
                x.isUp = False
            elif n.direction in (3,):  # Down
                x.direction = 0
                x.isUp = False
            else:  # Up/Auto/others
                x.direction = 0
                x.isUp = True
            x.linkage = _resolve_air_linkage(t, lane, width, fallback="TAP")
            notes_out.append(x)
        elif n.typ == 0x05:  # hold
            if n.long_attr == 0x01:
                active_holds.append(n)
            elif n.long_attr == 0x05 and active_holds:
                st = active_holds.pop(0)
                st_t = max(0, int(round(st.tick * scale)))
                end_t = t
                if end_t <= st_t:
                    continue
                x = HoldNote()
                x.measure = st_t // 384
                x.tick = st_t % 384
                x.lane = int(st.x)
                x.width = max(1, int(st.width))
                x.length = end_t - st_t
                notes_out.append(x)
        elif n.typ in (0x08, 0x09):  # airhold/airslide
            if n.long_attr == 0x01:
                active_air_holds.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_holds:
                st = active_air_holds[-1]
                st_t = max(0, int(round(st.tick * scale)))
                end_t = max(0, int(round(n.tick * scale)))
                if end_t <= st_t:
                    continue
                x = AirHold()
                x.measure = st_t // 384
                x.tick = st_t % 384
                x.lane = int(st.x)
                x.width = max(1, int(st.width))
                x.length = end_t - st_t
                notes_out.append(x)
                active_air_holds[-1] = n
                if n.long_attr in (0x05, 0x06):
                    active_air_holds.pop()
        elif n.typ == 0x0A:  # aircrush -> approximate as chained AHD
            if n.long_attr == 0x01:
                active_air_crash.append(n)
            elif n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06) and active_air_crash:
                st = active_air_crash[-1]
                st_t = max(0, int(round(st.tick * scale)))
                end_t = max(0, int(round(n.tick * scale)))
                if end_t > st_t:
                    x = AirHold()
                    x.measure = st_t // 384
                    x.tick = st_t % 384
                    x.lane = int(st.x)
                    x.width = max(1, int(st.width))
                    x.length = end_t - st_t
                    notes_out.append(x)
                active_air_crash[-1] = n
                if n.long_attr in (0x05, 0x06):
                    active_air_crash.pop()
        elif n.typ == 0x06:  # slide
            if n.long_attr == 0x01:
                slide_start = n
                active_slides = [n]
            elif slide_start is not None and n.long_attr in (0x02, 0x03, 0x04, 0x05, 0x06):
                active_slides.append(n)
                if n.long_attr in (0x05, 0x06):
                    for i in range(len(active_slides) - 1):
                        a = active_slides[i]
                        b = active_slides[i + 1]
                        at = max(0, int(round(a.tick * scale)))
                        bt = max(0, int(round(b.tick * scale)))
                        if bt <= at:
                            continue
                        x = SlideNote()
                        x.measure = at // 384
                        x.tick = at % 384
                        x.lane = int(a.x)
                        x.width = max(1, int(a.width))
                        x.length = bt - at
                        x.end_lane = int(b.x)
                        x.end_width = max(1, int(b.width))
                        x.is_curve = b.long_attr in (0x03, 0x04, 0x06)
                        notes_out.append(x)
                    slide_start = None
                    active_slides = []

    ugc_designer = _try_read_ugc_designer_near(source_path)
    creator_name = (
        ugc_designer
        or (meta.designer or "").strip()
        or (meta.artist or "").strip()
        or "MGXC import"
    )

    text = create_file(
        defs,
        notes_out,
        creator=creator_name,
        bpm_def=float(bpm_def),
    )
    out = source_path.with_suffix(".c2s")
    out.write_text(text, encoding="utf-8")
    return out


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
    level: int
    level_decimal: int
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

    meta, _events, _notes = _parse_mgxc(source_path)
    c2s_out = convert_pgko_chart_pick_to_c2s(PgkoChartPick(path=source_path, ext="mgxc"))

    mid = int(opts.music_id)
    mdir = acus_root / "music" / f"music{mid:04d}"
    if mdir.exists():
        raise FileExistsError(f"乐曲 ID 已存在：{mid}")
    mdir.mkdir(parents=True, exist_ok=True)

    slot = _slot_from_difficulty(int(meta.difficulty))
    slot_idx = _slot_file_index(slot)
    c2s_dst = mdir / f"{mid:04d}_{slot_idx:02d}.c2s"
    c2s_dst.write_bytes(c2s_out.read_bytes())

    jacket_src = source_path.with_suffix(".png")
    if not jacket_src.exists():
        cands = sorted(p for p in source_path.parent.glob("*.png") if p.is_file())
        if not cands:
            raise FileNotFoundError("未找到封面 PNG（需要与 mgxc 同目录）")
        jacket_src = cands[0]
    jacket_name = f"CHU_UI_Jacket_{mid:04d}.dds"
    convert_to_bc3_dds(tool_path=tool_path, input_image=jacket_src, output_dds=mdir / jacket_name)

    title = (meta.title or source_path.stem or str(mid)).strip()
    artist = ((meta.artist or "").strip() or "pgko")
    sort_name = title

    slot_map = {slot: c2s_dst}
    levels_by_type = {slot: (int(opts.level), int(opts.level_decimal))}
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
    if opts.create_unlock_event and slot in ("ULTIMA", "WORLD'S END"):
        created_event_id = next_custom_event_id(acus_root, start=70000)
        if slot == "ULTIMA":
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
        "slot": slot,
        "musicXml": str(mdir / "Music.xml"),
        "c2sFile": str(c2s_dst),
        "cueDir": str(cue_dst),
        "eventId": created_event_id,
    }

