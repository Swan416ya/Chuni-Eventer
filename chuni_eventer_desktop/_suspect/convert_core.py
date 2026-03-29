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
