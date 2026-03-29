"""
SUS（Sliding Universal Score）→ CHUNITHM c2s。

PJSK 侧固定拉取：normal / hard / expert / master / append（有 append 才有对应 Ultima 槽位）。

映射到 CHUNITHM 五档：BASIC(简)/ADVANCED(普)/EXPERT/MASTER/ULTIMA。
其中 PJSK「normal」对应中二 Basic（常称 Easy），「hard」对应 Advanced（常称 Advanced，勿与 PJSK 的 append 混淆）。

键型与轨位：docs/sus_to_c2s_note_mapping_zh.md；时间与 BPM/MET：docs/sus_c2s_format_zh.md。

参考：PjskSUSPatcher https://github.com/Qrael/PjskSUSPatcher
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

# 下载顺序（不含 PJSK easy）
PJSK_CHUNI_DOWNLOAD_ORDER: tuple[str, ...] = (
    "normal",
    "hard",
    "expert",
    "master",
    "append",
)

# PJSK 难度名（小写） → CHUNITHM MusicFumen type 名
PJSK_TO_CHUNI_SLOT: dict[str, str] = {
    "normal": "BASIC",
    "hard": "ADVANCED",
    "expert": "EXPERT",
    "master": "MASTER",
    "append": "ULTIMA",
}

# 与 PenguinTools / 样本一致的 c2s 时间基
CTS_RESOLUTION = 384

_SUS_LANE_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"

_DIRECTIONAL_TO_C2S: dict[str, str] = {
    "1": "AIR",
    "2": "ADW",
    "3": "AUL",
    "4": "AUR",
    "5": "ADL",
    "6": "ADR",
}

# 同一时间戳：BPM → MET → TAP → HLD → SLC → 天空
_KP_BPM, _KP_MET, _KP_TAP, _KP_HLD, _KP_SLC, _KP_AIR = 0, 1, 2, 3, 4, 5


def chuni_slot_name_for_pjsk(pjsk_difficulty: str) -> str | None:
    return PJSK_TO_CHUNI_SLOT.get((pjsk_difficulty or "").strip().lower())


def _sus_lane_index(ch: str) -> int:
    ch = ch.lower()
    if len(ch) != 1 or ch not in _SUS_LANE_ALPHABET:
        return 0
    return _SUS_LANE_ALPHABET.index(ch)


def _sus_width_units(width_ch: str) -> int:
    """SUS 宽度字符 → 1～35。"""
    return max(1, min(35, _sus_lane_index(width_ch) + 1))


def _pjsk_lane_to_chuni(lane_char: str, width_ch: str) -> tuple[int, int, bool]:
    """
    PJSK 左端轨字符 + 宽度字符 → 中二 lane、width（格数）。
    chuni_left = pjsk_index + 2；越界则钳位 width 并返回 clamped=True。
    """
    p = _sus_lane_index(lane_char)
    w = _sus_width_units(width_ch)
    left = p + 2
    max_w = 14 - left
    if max_w < 1:
        return 2, 1, True
    if w > max_w:
        return left, max_w, True
    return left, w, False


def _parse_measure_field(mmm: str) -> int:
    """
    三字符小节号：全为十进制数字时按十进制（Ched 常见）；否则按十六进制（SUS 规格）。
    """
    mmm = mmm.lower()
    if len(mmm) == 3 and all(c in "0123456789" for c in mmm):
        return int(mmm, 10)
    return int(mmm, 16)


def _strip_sus_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


@dataclass
class _SusParseState:
    ticks_per_beat: int = 480
    beats_from_bar: dict[int, float] = field(default_factory=dict)
    bpm_defs: dict[str, float] = field(default_factory=dict)
    base_bpm: float | None = None
    bpm_from_bar: dict[int, str] = field(default_factory=dict)
    designer: str = ""
    title: str = ""
    artist: str = ""
    max_measure: int = 0


@dataclass(order=True)
class _TimedLine:
    sort_tick: int
    kind_pri: int
    tie: int
    text: str


def _iter_sus_commands(text: str) -> Iterator[tuple[int, str]]:
    for i, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line.startswith("#"):
            continue
        yield i, line


def _parse_request_ticks_per_beat(content: str) -> int | None:
    m = re.search(r"ticks_per_beat\s+(\d+)", content, re.I)
    if m:
        return int(m.group(1))
    return None


def _collect_state(lines: list[tuple[int, str]]) -> _SusParseState:
    st = _SusParseState()
    data_rows: list[tuple[int, str, str, str]] = []

    for _ln, line in lines:
        body = line[1:]
        if not body:
            continue
        if body.startswith("TITLE"):
            m = re.match(r"TITLE\s+(.+)", body, re.I)
            if m:
                st.title = _strip_sus_quotes(m.group(1))
            continue
        if body.startswith("ARTIST"):
            m = re.match(r"ARTIST\s+(.+)", body, re.I)
            if m:
                st.artist = _strip_sus_quotes(m.group(1))
            continue
        if body.startswith("DESIGNER") or body.startswith("DESINGER"):
            m = re.match(r"DES(?:IGNER|INGER)\s+(.+)", body, re.I)
            if m:
                st.designer = _strip_sus_quotes(m.group(1))
            continue
        if body.startswith("REQUEST"):
            m = re.match(r'REQUEST\s+"(.*)"', body, re.I)
            if m:
                tpb = _parse_request_ticks_per_beat(m.group(1))
                if tpb is not None:
                    st.ticks_per_beat = max(1, tpb)
            continue
        if body.startswith("BASEBPM"):
            m = re.match(r"BASEBPM\s+([0-9.]+)", body, re.I)
            if m:
                st.base_bpm = float(m.group(1))
            continue
        m = re.match(r"BPM([0-9a-zA-Z]{2})\s*:\s*([0-9.]+)", body)
        if m:
            st.bpm_defs[m.group(1).lower()] = float(m.group(2))
            continue

        if ":" not in body:
            continue
        head, data_part = body.split(":", 1)
        head = head.strip()
        data_part = data_part.strip()
        if len(head) < 3:
            continue
        mmm, rest = head[:3], head[3:]
        try:
            bar = _parse_measure_field(mmm)
        except ValueError:
            continue
        st.max_measure = max(st.max_measure, bar)
        data_rows.append((bar, rest, data_part, mmm))

    cur_beats = 4.0
    active_beats: dict[int, float] = {}
    for bar, rest, data_part, _mmm in sorted(data_rows, key=lambda x: (x[0], x[1])):
        if rest == "02":
            try:
                cur_beats = float(data_part.split()[0])
            except (ValueError, IndexError):
                pass
            active_beats[bar] = cur_beats
            continue
        if rest == "08":
            key = data_part.strip().lower()[:2]
            if len(key) == 2:
                st.bpm_from_bar[bar] = key
            continue

    st.beats_from_bar = {}
    cb = 4.0
    for b in range(st.max_measure + 2):
        if b in active_beats:
            cb = active_beats[b]
        st.beats_from_bar[b] = cb

    return st


def _bar_start_sus_tick(st: _SusParseState, bar: int) -> int:
    t = 0
    for b in range(max(0, bar)):
        t += int(round(st.beats_from_bar.get(b, 4.0) * st.ticks_per_beat))
    return t


def _bar_length_sus_tick(st: _SusParseState, bar: int) -> int:
    return int(round(st.beats_from_bar.get(bar, 4.0) * st.ticks_per_beat))


def _sus_tick_to_c2s_global(sus_tick: int, tpb: int) -> int:
    return int(round(sus_tick * (CTS_RESOLUTION / float(tpb))))


def _global_c2s_to_bar_offset(st: _SusParseState, g: int) -> tuple[int, int]:
    """全局 c2s tick → (小节, 小节内 offset)。"""
    b = 0
    while b <= st.max_measure + 8:
        bl = _bar_length_c2s(st, b)
        if g < bl:
            return b, max(0, g)
        g -= bl
        b += 1
    return b, max(0, g)


def _bar_length_c2s(st: _SusParseState, bar: int) -> int:
    sus_len = _bar_length_sus_tick(st, bar)
    return _sus_tick_to_c2s_global(sus_len, st.ticks_per_beat)


def _main_bpm(st: _SusParseState) -> float:
    if st.base_bpm is not None:
        return st.base_bpm
    if st.bpm_defs:
        return next(iter(st.bpm_defs.values()))
    return 120.0


def _bpm_value_at_bar(st: _SusParseState, bar: int) -> float:
    cur_key: str | None = None
    for b in sorted(st.bpm_from_bar.keys()):
        if b <= bar:
            cur_key = st.bpm_from_bar[b]
        else:
            break
    if cur_key and cur_key in st.bpm_defs:
        return st.bpm_defs[cur_key]
    return _main_bpm(st)


def _parse_channel_rest(rest: str) -> tuple[str, tuple[str, ...]]:
    if rest == "02":
        return "measure_length", ()
    if rest == "08":
        return "bpm", ()
    if len(rest) == 2 and rest[0] == "1":
        return "tap", (rest[1],)
    if len(rest) == 2 and rest[0] == "5":
        return "directional", (rest[1],)
    if len(rest) == 3 and rest[0] in "234":
        kind = {"2": "hold", "3": "slide", "4": "slide"}[rest[0]]
        return kind, (rest[1], rest[2])
    return "ignore", ()


def _emit_notes_and_slides(
    st: _SusParseState,
    lines: list[tuple[int, str]],
) -> tuple[list[_TimedLine], list[str]]:
    """
    扫描谱面行，生成 TAP / HLD / AIR* / SLC 链。
    返回 (有序事件, 警告)。
    """
    warnings: list[str] = []
    out: list[_TimedLine] = []
    tie = 0

    hold_open: dict[tuple[str, str], list[tuple[int, int, int]]] = {}

    slide_events: dict[
        tuple[str, str], list[tuple[int, str, int, int, int, int]]
    ] = {}

    for _i, line in lines:
        if not line.startswith("#") or ":" not in line:
            continue
        body = line[1:]
        head, data_part = body.split(":", 1)
        head, data_part = head.strip(), data_part.strip()
        if len(head) < 3:
            continue
        mmm, rest = head[:3], head[3:]
        try:
            bar = _parse_measure_field(mmm)
        except ValueError:
            continue
        kind, chans = _parse_channel_rest(rest)
        if kind in ("measure_length", "bpm", "ignore"):
            continue
        if not data_part or len(data_part) % 2 != 0:
            continue

        n_groups = len(data_part) // 2
        if n_groups == 0:
            continue
        sus_len = _bar_length_sus_tick(st, bar)
        step = sus_len / float(n_groups)

        def group_tick(idx: int) -> int:
            return _bar_start_sus_tick(st, bar) + int(round(idx * step))

        if kind == "tap":
            lane_c = chans[0]
            for g in range(n_groups):
                tch, wch = data_part[g * 2], data_part[g * 2 + 1]
                if tch == "0":
                    continue
                gt = group_tick(g)
                gc = _sus_tick_to_c2s_global(gt, st.ticks_per_beat)
                bo = _global_c2s_to_bar_offset(st, gc)
                lane, width, clamped = _pjsk_lane_to_chuni(lane_c, wch)
                if clamped:
                    warnings.append(f"tap width clamped bar={bar} lane={lane_c}")
                tie += 1
                out.append(
                    _TimedLine(
                        gc,
                        _KP_TAP,
                        tie,
                        f"TAP\t{bo[0]}\t{bo[1]}\t{lane}\t{width}",
                    )
                )

        elif kind == "directional":
            lane_c = chans[0]
            for g in range(n_groups):
                tch, wch = data_part[g * 2], data_part[g * 2 + 1]
                if tch == "0":
                    continue
                c2s_air = _DIRECTIONAL_TO_C2S.get(tch.lower())
                if not c2s_air:
                    continue
                gt = group_tick(g)
                gc = _sus_tick_to_c2s_global(gt, st.ticks_per_beat)
                bo = _global_c2s_to_bar_offset(st, gc)
                lane, width, clamped = _pjsk_lane_to_chuni(lane_c, wch)
                if clamped:
                    warnings.append(f"air width clamped bar={bar}")
                tie += 1
                out.append(
                    _TimedLine(
                        gc,
                        _KP_AIR,
                        tie,
                        f"{c2s_air}\t{bo[0]}\t{bo[1]}\t{lane}\t{width}\tTAP\tDEF",
                    )
                )

        elif kind == "hold":
            x, y = chans[0], chans[1]
            key = (x, y)
            stack = hold_open.setdefault(key, [])
            for g in range(n_groups):
                tch, wch = data_part[g * 2], data_part[g * 2 + 1]
                if tch == "0":
                    continue
                gt = group_tick(g)
                gc = _sus_tick_to_c2s_global(gt, st.ticks_per_beat)
                bo = _global_c2s_to_bar_offset(st, gc)
                lane, width, clamped = _pjsk_lane_to_chuni(x, wch)
                if clamped:
                    warnings.append(f"hold width clamped bar={bar}")

                if tch == "1":
                    stack.append((gc, lane, width))
                elif tch == "3":
                    continue
                elif tch == "2":
                    if not stack:
                        warnings.append(f"hold end without start ch={key} bar={bar}")
                        continue
                    gs, slane, swidth = stack.pop()
                    dur = max(1, gc - gs)
                    sb = _global_c2s_to_bar_offset(st, gs)
                    tie += 1
                    out.append(
                        _TimedLine(
                            gs,
                            _KP_HLD,
                            tie,
                            f"HLD\t{sb[0]}\t{sb[1]}\t{slane}\t{swidth}\t{dur}",
                        )
                    )

        elif kind == "slide":
            x, y = chans[0], chans[1]
            key = (x, y)
            bucket = slide_events.setdefault(key, [])
            for g in range(n_groups):
                tch, wch = data_part[g * 2], data_part[g * 2 + 1]
                if tch == "0":
                    continue
                gt = group_tick(g)
                gc = _sus_tick_to_c2s_global(gt, st.ticks_per_beat)
                bo = _global_c2s_to_bar_offset(st, gc)
                lane, width, clamped = _pjsk_lane_to_chuni(x, wch)
                if clamped:
                    warnings.append(f"slide width clamped bar={bar}")
                if tch in ("1", "2", "3", "4", "5"):
                    bucket.append((gc, tch, lane, width, bo[0], bo[1]))

    _s_ord = {"1": 0, "3": 1, "4": 2, "5": 3, "2": 4}
    for key, evs in slide_events.items():
        evs.sort(key=lambda x: (x[0], _s_ord.get(x[1], 9)))
        chain: list[tuple[int, int, int, int, int]] = []

        def flush_chain() -> None:
            nonlocal tie
            if len(chain) < 2:
                return
            for i in range(len(chain) - 1):
                g0, m0, o0, l0, w0 = chain[i]
                g1, m1, o1, l1, w1 = chain[i + 1]
                dur = max(1, g1 - g0)
                tie += 1
                out.append(
                    _TimedLine(
                        g0,
                        _KP_SLC,
                        tie,
                        f"SLC\t{m0}\t{o0}\t{l0}\t{w0}\t{dur}\t{l1}\t{w1}\tSLD",
                    )
                )

        for gc, tch, lane, width, m, o in evs:
            if tch == "1":
                if chain:
                    warnings.append(f"slide chain restart without end ch={key}")
                    chain = []
                chain = [(gc, m, o, lane, width)]
            elif tch in ("3", "4", "5"):
                if not chain:
                    continue
                chain.append((gc, m, o, lane, width))
            elif tch == "2":
                if not chain:
                    continue
                chain.append((gc, m, o, lane, width))
                flush_chain()
                chain = []

        if chain:
            warnings.append(f"slide chain missing end ch={key}")

    return out, warnings


def convert_sus_to_c2s(sus_text: str) -> str:
    lines = list(_iter_sus_commands(sus_text))
    st = _collect_state(lines)

    bpm_main = _main_bpm(st)
    bpm_s = f"{bpm_main:.3f}"
    header = "\n".join(
        [
            "VERSION\t1.13.00\t1.13.00",
            "MUSIC\t0",
            "SEQUENCEID\t0",
            "DIFFICULT\t0",
            "LEVEL\t0.0",
            f"CREATOR\t{st.designer or 'PJSK SUS import'}",
            f"BPM_DEF\t{bpm_s}\t{bpm_s}\t{bpm_s}\t{bpm_s}",
            "MET_DEF\t4\t4",
            f"RESOLUTION\t{CTS_RESOLUTION}",
            f"CLK_DEF\t{CTS_RESOLUTION}",
            "PROGJUDGE_BPM\t240.000",
            "PROGJUDGE_AER\t 0.999",
            "TUTORIAL\t0",
            "",
        ]
    )

    event_lines: list[_TimedLine] = []
    e_tie = 0
    seen_bpm: set[tuple[int, int, float]] = set()
    for bar in sorted(set(st.bpm_from_bar.keys()) | {0}):
        val = _bpm_value_at_bar(st, bar)
        bo = (bar, 0)
        key = (bo[0], bo[1], round(val, 3))
        if key in seen_bpm:
            continue
        seen_bpm.add(key)
        e_tie += 1
        event_lines.append(
            _TimedLine(
                _sus_tick_to_c2s_global(_bar_start_sus_tick(st, bar), st.ticks_per_beat),
                _KP_BPM,
                e_tie,
                f"BPM\t{bar}\t0\t{val:.3f}",
            )
        )

    e_tie += 1
    event_lines.append(
        _TimedLine(0, _KP_MET, e_tie, "MET\t0\t0\t4\t4"),
    )

    note_lines, _warn = _emit_notes_and_slides(st, lines)
    all_sorted = sorted(event_lines + note_lines)
    body = "\n".join(x.text for x in all_sorted)
    return header + body + "\n"


def try_convert_sus_to_c2s_bytes(sus_text: str) -> bytes | None:
    """
    将 SUS 正文转为 c2s UTF-8 文本字节。
    解析或生成失败时返回 None。
    """
    try:
        text = convert_sus_to_c2s(sus_text)
    except Exception:
        return None
    return text.encode("utf-8")


__all__ = [
    "PJSK_CHUNI_DOWNLOAD_ORDER",
    "PJSK_TO_CHUNI_SLOT",
    "CTS_RESOLUTION",
    "chuni_slot_name_for_pjsk",
    "convert_sus_to_c2s",
    "try_convert_sus_to_c2s_bytes",
]
