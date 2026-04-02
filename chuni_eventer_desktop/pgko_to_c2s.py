from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from ._suspect.c2s_emit import AirHold, AirNote, BpmSetting, HoldNote, SlideNote, TapNote, create_file


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
    seq: int


@dataclass(frozen=True)
class _GroundAnchor:
    tick: int
    lane: int
    width: int
    linkage: str  # TAP/HLD/SLD


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


def _read_field(buf: BinaryIO) -> str | int | float:
    typ = _i16(_read_exact(buf, 2))
    attr = _i16(_read_exact(buf, 2))
    if typ == 4:
        return _read_exact(buf, attr).decode("utf-8", errors="ignore")
    if typ == 3:
        return _f64(_read_exact(buf, 8))
    if typ == 2:
        return _i32(_read_exact(buf, 4))
    if typ in (0, 1):
        return int(attr)
    raise ValueError(f"unknown mgxc field type: {typ}")


def _parse_mgxc(path: Path) -> tuple[list[_MgxcEvent], list[_MgxcNote]]:
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
                        _read_field(br)
                        _read_field(br)
                        _read_field(br)
                    elif name == "til ":
                        _read_field(br)
                        _read_field(br)
                        _read_field(br)
                    elif name == "smod":
                        _read_field(br)
                        _read_field(br)
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
                    _read_exact(br, 4)  # timelineId
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
                            seq=seq,
                        )
                    )
                    seq += 1
    return events, notes


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

    events, raw_notes = _parse_mgxc(source_path)
    if not events:
        events = [_MgxcEvent(kind="bpm", tick=0, value=120.0)]

    bpm_def = sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick)[0].value
    scale = 384.0 / 480.0

    defs: list[BpmSetting] = []
    for e in sorted((e for e in events if e.kind == "bpm"), key=lambda x: x.tick):
        obj = BpmSetting()
        t = max(0, int(round(e.tick * scale)))
        obj.measure = t // 384
        obj.tick = t % 384
        obj.bpm = float(e.value)
        defs.append(obj)

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

    notes_out: list[TapNote | HoldNote | SlideNote | AirNote | AirHold] = []
    active_holds: list[_MgxcNote] = []
    active_air_holds: list[_MgxcNote] = []
    active_air_crash: list[_MgxcNote] = []
    active_slides: list[_MgxcNote] = []
    slide_start: _MgxcNote | None = None
    for n in converted_notes:
        t = max(0, int(round(n.tick * scale)))
        lane = int(n.x)
        width = max(1, int(n.width))
        if n.typ in (0x01, 0x02, 0x03):  # tap/extap/flick
            x = TapNote()
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

    text = create_file(
        defs,
        notes_out,
        creator="pgko mgxc import",
        bpm_def=float(bpm_def),
    )
    out = source_path.with_suffix(".c2s")
    out.write_text(text, encoding="utf-8")
    return out

