# Derived from Soyandroid/suspect src/formats/convert.py (SUS objects → c2s objects).

from __future__ import annotations

from . import c2s_emit as c2s
from . import sus_parser as sus


def _sus_ticks_per_measure(ctx: sus.SusContext, measure: int) -> float:
    beats = ctx.beats_from_bar.get(measure, 4.0)
    return float(beats) * float(ctx.ticks_per_beat)


def sus_to_c2s(
    sus_objects: list,
    *,
    timing: sus.SusContext,
) -> tuple[list, list]:
    c2s_definitions: list = []
    c2s_notes: list = []

    def sus_to_c2s_ticks(measure: int, tick: int) -> int:
        tpm = _sus_ticks_per_measure(timing, measure)
        if tpm <= 0:
            return 0
        scaled = int((tick / tpm) * c2s.C2S_TICKS_PER_MEASURE)
        return max(0, min(c2s.C2S_TICKS_PER_MEASURE, scaled))

    for obj in sus_objects:
        if isinstance(obj, sus.ShortNote):
            note = None
            if isinstance(obj.note_type, sus.TapNoteType):
                if obj.note_type == sus.TapNoteType.TAP:
                    note = c2s.TapNote()
                elif obj.note_type == sus.TapNoteType.EXTAP:
                    note = c2s.ChargeNote()
                elif obj.note_type == sus.TapNoteType.FLICK:
                    note = c2s.FlickNote()
                elif obj.note_type == sus.TapNoteType.HELL:
                    note = c2s.MineNote()
            elif isinstance(obj.note_type, sus.AirNoteType):
                if obj.note_type == sus.AirNoteType.UP:
                    note = c2s.AirNote()
                    note.isUp = True
                    note.direction = 0
                elif obj.note_type == sus.AirNoteType.UP_LEFT:
                    note = c2s.AirNote()
                    note.isUp = True
                    note.direction = -1
                elif obj.note_type == sus.AirNoteType.UP_RIGHT:
                    note = c2s.AirNote()
                    note.isUp = True
                    note.direction = 1
                elif obj.note_type == sus.AirNoteType.DOWN:
                    note = c2s.AirNote()
                    note.isUp = False
                    note.direction = 0
                elif obj.note_type == sus.AirNoteType.DOWN_LEFT:
                    note = c2s.AirNote()
                    note.isUp = False
                    note.direction = -1
                elif obj.note_type == sus.AirNoteType.DOWN_RIGHT:
                    note = c2s.AirNote()
                    note.isUp = False
                    note.direction = 1
            if note is None:
                continue
            note.lane = obj.lane
            note.width = obj.width
            note.measure = obj.measure
            note.tick = sus_to_c2s_ticks(obj.measure, obj.tick)
            c2s_notes.append(note)

        elif isinstance(obj, sus.LongNote):
            if obj.note_type == sus.LongNoteType.END:
                continue

            ch = obj.linked
            try:
                next_idx = ch.index(obj) + 1
            except ValueError:
                continue
            if next_idx == len(ch):
                continue

            next_obj = ch[next_idx]
            if next_obj.note_kind != obj.note_kind:
                continue

            start_measure = obj.measure
            start_ticks = sus_to_c2s_ticks(obj.measure, obj.tick)
            end_measure = next_obj.measure
            end_ticks = sus_to_c2s_ticks(next_obj.measure, next_obj.tick)

            diff_ticks = (
                (end_measure - start_measure) * c2s.C2S_TICKS_PER_MEASURE
            ) + (end_ticks - start_ticks)

            if obj.note_kind == sus.LongNoteKind.SLIDE:
                note = c2s.SlideNote()
                note.end_lane = next_obj.lane
                note.end_width = next_obj.width
                note.is_curve = obj.note_type in (
                    sus.LongNoteType.CONTROL,
                    sus.LongNoteType.INVISIBLE,
                )
            elif obj.note_kind == sus.LongNoteKind.HOLD:
                note = c2s.HoldNote()
            elif obj.note_kind == sus.LongNoteKind.AIR_HOLD:
                note = c2s.AirHold()
            else:
                continue

            note.measure = start_measure
            note.tick = start_ticks
            note.lane = obj.lane
            note.width = obj.width
            note.length = max(1, diff_ticks)
            c2s_notes.append(note)

        elif isinstance(obj, sus.BpmChange):
            if obj.definition is None:
                continue
            definition = c2s.BpmSetting()
            definition.measure = obj.measure
            definition.tick = 0
            definition.bpm = float(obj.definition.tempo)
            c2s_definitions.append(definition)

        elif isinstance(obj, sus.BarLength):
            definition = c2s.MeterSetting()
            definition.measure = obj.measure
            definition.tick = 0
            sig_n = int(round(float(obj.length)))
            definition.signature = (max(1, sig_n), 4)
            c2s_definitions.append(definition)

    c2s_notes.sort(
        key=lambda n: n.measure + n.tick / float(c2s.C2S_TICKS_PER_MEASURE)
    )
    return (c2s_definitions, c2s_notes)


def remap_lanes_pjsk_to_chuni(notes: list) -> None:
    """PJSK/Seaurchin SUS lane index → CHUNITHM ground lane (offset + width clamp)."""

    def lw(sus_lane: int, width: int) -> tuple[int, int]:
        w = max(1, min(35, int(width)))
        left = int(sus_lane) + 2
        max_w = 14 - left
        if max_w < 1:
            return 2, 1
        if w > max_w:
            return left, max_w
        return left, w

    for n in notes:
        if isinstance(n, c2s.SlideNote):
            n.lane, n.width = lw(n.lane, n.width)
            n.end_lane, n.end_width = lw(n.end_lane, n.end_width)
        elif isinstance(n, c2s.C2sNote):
            n.lane, n.width = lw(n.lane, n.width)


# 与 remap 后 c2s 的 lane 一致：PJSK 最左列映射后最小为 2，此处 2～6 共五条地面轨。
_PLAY_LEFTMOST_LANE_MIN = 2
_PLAY_LEFTMOST_LANE_MAX = 6


def apply_playability_filters(notes: list) -> list:
    """
    可玩性后处理（在 PJSK→中二轨映射之后执行）：

    1. 删除所有 Air-down（ADW/ADL/ADR），以及与其同 (measure, tick, lane, width) 的 TAP。
    2. 删除与 HLD 或 Slide（SLD/SLC）**末尾时刻**重合的 CHR（EXTAP）；末尾取 length 的
       最后一拍与紧随其后的下一拍两种可能，lane/width 与长条结束端一致。
    3. 删除宽度为 1 且落在最左五条地面轨上的 TAP / MNE / CHR / FLK / HLD / Slide（任一端满足即删整条 Slide）。
    """
    R = c2s.C2S_TICKS_PER_MEASURE
    lo, hi = _PLAY_LEFTMOST_LANE_MIN, _PLAY_LEFTMOST_LANE_MAX

    def lin(m: int, t: int) -> int:
        return int(m) * R + int(t)

    def in_left_five(lane: int) -> bool:
        return lo <= int(lane) <= hi

    res = list(notes)

    air_down_keys = {
        (n.measure, n.tick, n.lane, n.width)
        for n in res
        if isinstance(n, c2s.AirNote) and not n.isUp
    }
    res = [
        n
        for n in res
        if not (
            isinstance(n, c2s.AirNote)
            and (not n.isUp)
            or (
                isinstance(n, c2s.TapNote)
                and (n.measure, n.tick, n.lane, n.width) in air_down_keys
            )
        )
    ]

    end_chr_keys: set[tuple[int, int, int]] = set()
    for n in res:
        if isinstance(n, c2s.HoldNote):
            s = lin(n.measure, n.tick)
            ln = int(n.length)
            last_t = s + ln - 1
            rel_t = s + ln
            end_chr_keys.add((last_t, int(n.lane), int(n.width)))
            end_chr_keys.add((rel_t, int(n.lane), int(n.width)))
        elif isinstance(n, c2s.SlideNote):
            s = lin(n.measure, n.tick)
            ln = int(n.length)
            last_t = s + ln - 1
            rel_t = s + ln
            end_chr_keys.add((last_t, int(n.end_lane), int(n.end_width)))
            end_chr_keys.add((rel_t, int(n.end_lane), int(n.end_width)))

    res = [
        n
        for n in res
        if not (
            isinstance(n, c2s.ChargeNote)
            and (lin(n.measure, n.tick), int(n.lane), int(n.width)) in end_chr_keys
        )
    ]

    def strip_left_narrow(n: c2s.C2sNote) -> bool:
        if isinstance(n, c2s.SlideNote):
            if int(n.width) == 1 and in_left_five(n.lane):
                return True
            if int(n.end_width) == 1 and in_left_five(n.end_lane):
                return True
            return False
        if isinstance(
            n,
            (c2s.TapNote, c2s.MineNote, c2s.ChargeNote, c2s.FlickNote, c2s.HoldNote),
        ):
            return int(n.width) == 1 and in_left_five(n.lane)
        return False

    res = [n for n in res if not strip_left_narrow(n)]
    return res
