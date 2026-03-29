# Derived from Soyandroid/suspect src/formats/sus.py (SUS parse → note objects).

from __future__ import annotations

import re
from abc import ABC
from enum import Enum

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


SUS_DEFAULT_TICKS_PER_BEAT = 480


class TapNoteType(Enum):
    TAP = 1
    EXTAP = 2
    FLICK = 3
    HELL = 4
    RESERVED1 = 5
    RESERVED2 = 6


class AirNoteType(Enum):
    UP = 1
    DOWN = 2
    UP_LEFT = 3
    UP_RIGHT = 4
    DOWN_LEFT = 5
    DOWN_RIGHT = 6


class LongNoteType(Enum):
    START = 1
    END = 2
    STEP = 3
    CONTROL = 4
    INVISIBLE = 5


class LongNoteKind(Enum):
    HOLD = 2
    SLIDE = 3
    AIR_HOLD = 4


_SUS_LANE_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _parse_measure_field(mmm: str) -> int:
    mmm = mmm.lower()
    if len(mmm) == 3 and all(c in "0123456789" for c in mmm):
        return int(mmm, 10)
    return int(mmm, 16)


def _sus_lane_char_index(ch: str) -> int:
    ch = ch.lower()
    if len(ch) != 1 or ch not in _SUS_LANE_ALPHABET:
        return 0
    return _SUS_LANE_ALPHABET.index(ch)


def _strip_sus_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        return s[1:-1]
    return s


def _parse_request_ticks_per_beat(content: str) -> int | None:
    m = re.search(r"ticks_per_beat\s+(\d+)", content, re.I)
    if m:
        return int(m.group(1))
    return None


class SusObject(ABC):
    attribute: Any = None
    speed: Any = None


class BarLength(SusObject):
    measure: int = 0
    length: float = 0.0


class BpmDefinition(SusObject):
    identifier: str = ""
    tempo: float = 0.0


class BpmChange(SusObject):
    measure: int = 0
    definition: BpmDefinition | None = None


class AttributeDefinition(SusObject):
    identifier: str = ""
    roll_speed: float | None = None
    height: float | None = None
    priority: float | None = None


class SpeedDefinition(SusObject):
    identifier: str = ""
    speeds: list = None  # type: ignore[assignment]

    def __init__(self) -> None:
        self.speeds = []

    def add_speed(self, measure: int, tick: int, speed: float) -> None:
        self.speeds.append((measure, tick, speed))


class ShortNote(SusObject):
    measure: int = 0
    tick: int = 0
    lane: int = 0
    width: int = 0
    note_type: TapNoteType | AirNoteType = TapNoteType.TAP


class LongNote(SusObject):
    measure: int = 0
    tick: int = 0
    lane: int = 0
    width: int = 0
    note_kind: LongNoteKind = LongNoteKind.HOLD
    note_type: LongNoteType = LongNoteType.START
    linked: list = None  # type: ignore[assignment]

    def __init__(self) -> None:
        self.linked = []


class SusContext:
    active_attribute: Any = None
    active_speed: Any = None
    base_measure: int = 0
    ticks_per_beat: int = SUS_DEFAULT_TICKS_PER_BEAT

    bpm_definitions: dict[str, BpmDefinition]
    attribute_definitions: dict[str, AttributeDefinition]
    speed_definitions: dict[str, SpeedDefinition]
    channels: dict[str, list[LongNote]]

    designer: str = ""
    title: str = ""
    artist: str = ""
    base_bpm: float | None = None

    beats_from_bar: dict[int, float]
    max_measure: int
    bpm_from_bar: dict[int, str]

    def __init__(self) -> None:
        self.bpm_definitions = {}
        self.attribute_definitions = {}
        self.speed_definitions = {}
        self.channels = {}
        self.beats_from_bar = {}
        self.max_measure = 0
        self.bpm_from_bar = {}

    def ticks_for_measure_row(self, measure_value: int, n_groups: int) -> list[int]:
        """Per-group tick offsets within the measure (0 .. duration_ticks)."""
        beats = self.beats_from_bar.get(measure_value, 4.0)
        dur = int(round(float(beats) * float(self.ticks_per_beat)))
        if n_groups <= 0:
            return []
        step = dur // n_groups
        return [step * i for i in range(n_groups)]

    def fix_channels(self) -> None:
        for key in self.channels:
            channel = self.channels[key]
            for i in range(len(channel) - 1):
                if (
                    channel[i].note_kind != channel[i + 1].note_kind
                    and channel[i].note_type != LongNoteType.END
                ):
                    channel[i].note_type = LongNoteType.END
                if (
                    channel[i].note_type != LongNoteType.END
                    and channel[i + 1].note_type == LongNoteType.START
                ):
                    channel[i].note_type = LongNoteType.END
            if channel and channel[-1].note_type != LongNoteType.END:
                channel[-1].note_type = LongNoteType.END


def _collect_timing_and_meta(text: str, ctx: SusContext) -> None:
    data_rows: list[tuple[int, str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("#"):
            continue
        body = line[1:].strip()
        if body.upper().startswith("TITLE"):
            m = re.match(r"TITLE\s+(.+)", body, re.I)
            if m:
                ctx.title = _strip_sus_quotes(m.group(1))
            continue
        if body.upper().startswith("ARTIST"):
            m = re.match(r"ARTIST\s+(.+)", body, re.I)
            if m:
                ctx.artist = _strip_sus_quotes(m.group(1))
            continue
        if body.upper().startswith("DESIGNER") or body.upper().startswith("DESINGER"):
            m = re.match(r"DES(?:IGNER|INGER)\s+(.+)", body, re.I)
            if m:
                ctx.designer = _strip_sus_quotes(m.group(1))
            continue
        if body.upper().startswith("REQUEST"):
            m = re.match(r'REQUEST\s+"(.*)"', body, re.I)
            if m:
                tpb = _parse_request_ticks_per_beat(m.group(1))
                if tpb is not None:
                    ctx.ticks_per_beat = max(1, tpb)
            continue
        if body.upper().startswith("BASEBPM"):
            m = re.match(r"BASEBPM\s+([0-9.]+)", body, re.I)
            if m:
                ctx.base_bpm = float(m.group(1))
            continue
        m = re.match(r"BPM([0-9a-zA-Z]{2})\s*:\s*([0-9.]+)", body)
        if m:
            bd = BpmDefinition()
            bd.identifier = m.group(1).lower()
            bd.tempo = float(m.group(2))
            ctx.bpm_definitions[bd.identifier] = bd
            continue
        if ":" not in body:
            continue
        head, data_part = body.split(":", 1)
        head, data_part = head.strip(), data_part.strip()
        if len(head) < 3:
            continue
        mmm, rest = head[:3], head[3:]
        try:
            bar = _parse_measure_field(mmm)
        except ValueError:
            continue
        ctx.max_measure = max(ctx.max_measure, bar)
        data_rows.append((bar, rest, data_part))

    cur_beats = 4.0
    active_beats: dict[int, float] = {}
    for bar, rest, data_part in sorted(data_rows, key=lambda x: (x[0], x[1])):
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
                ctx.bpm_from_bar[bar] = key
            continue

    cb = 4.0
    for b in range(ctx.max_measure + 2):
        if b in active_beats:
            cb = active_beats[b]
        ctx.beats_from_bar[b] = cb


def main_bpm_for_context(ctx: SusContext) -> float:
    if ctx.base_bpm is not None:
        return ctx.base_bpm
    if ctx.bpm_definitions:
        return next(iter(ctx.bpm_definitions.values())).tempo
    return 120.0


def parse_sus_document(text: str) -> tuple[list[SusObject], SusContext]:
    ctx = SusContext()
    _collect_timing_and_meta(text, ctx)

    out: list[SusObject] = []
    for raw in text.splitlines():
        out.extend(_parse_sus_line(raw, ctx))

    ctx.fix_channels()
    return out, ctx


def _parse_sus_line(sus_string: str, context: SusContext) -> list[SusObject]:
    sus_string = sus_string.strip()
    if not sus_string or sus_string[0] != "#":
        return []

    sus_string = sus_string[1:]
    split = sus_string.split(":", 2)
    header = split[0].strip()

    if header.startswith("HISPEED") or header.startswith("NOSPEED"):
        return []
    if header.startswith("ATTRIBUTE") or header.startswith("NOATTRIBUTE"):
        return []
    if header.startswith("MEASUREBS"):
        parts = header.split()
        if len(parts) >= 2:
            try:
                context.base_measure = int(parts[1])
            except ValueError:
                pass
        return []

    if len(split) == 1:
        return []

    data = split[1]
    data = "".join(data.split())
    measure = header[:3]

    if measure == "BPM":
        obj = BpmDefinition()
        obj.identifier = header[3:5].lower()
        obj.tempo = float(data)
        context.bpm_definitions[obj.identifier] = obj
        return []

    if measure == "ATR":
        obj = AttributeDefinition()
        obj.identifier = header[3:5].lower()
        defstring = data.replace('"', "").split(",")
        for definition in defstring:
            try:
                attr, val = definition.split(":")
                if attr == "rh":
                    obj.roll_speed = float(val)
                if attr == "h":
                    obj.height = float(val)
                if attr == "pr":
                    obj.priority = float(val)
            except Exception:
                continue
        context.attribute_definitions[obj.identifier] = obj
        return []

    if measure == "TIL":
        obj = SpeedDefinition()
        obj.identifier = header[3:5].lower()
        defstring = data.replace('"', "").replace("'", ":").split(",")
        for definition in defstring:
            try:
                bar, tick, speed = definition.split(":")
                obj.add_speed(int(bar), int(tick), float(speed))
            except Exception:
                continue
        context.speed_definitions[obj.identifier] = obj
        return []

    if len(header) < 4:
        return []

    note_type = header[3]
    try:
        measure_value = _parse_measure_field(measure) + context.base_measure
    except ValueError:
        return []

    if note_type == "0":
        change_type = header[4] if len(header) > 4 else ""
        if change_type == "2":
            obj = BarLength()
            obj.measure = measure_value
            try:
                obj.length = float(data.split()[0])
            except (ValueError, IndexError):
                obj.length = 4.0
            return [obj]
        if change_type == "8":
            key = data.strip().lower()[:2]
            if len(key) != 2 or key not in context.bpm_definitions:
                return []
            obj = BpmChange()
            obj.measure = measure_value
            obj.definition = context.bpm_definitions[key]
            return [obj]
        return []

    if len(data) < 2 or len(data) % 2 != 0:
        return []

    n_groups = len(data) // 2
    tick_offsets = context.ticks_for_measure_row(measure_value, n_groups)

    parsed_data: list[tuple[int, int, int]] = []
    for i in range(0, len(data), 2):
        gi = i // 2
        tick = tick_offsets[gi] if gi < len(tick_offsets) else 0
        try:
            tap_type = int(data[i], 36)
            width = int(data[i + 1], 36)
        except ValueError:
            continue
        parsed_data.append((tick, tap_type, width))

    if note_type == "1" or note_type == "5":
        lane_idx = _sus_lane_char_index(header[4] if len(header) > 4 else "0")
        objects: list[SusObject] = []
        for tick, tap_type, width in parsed_data:
            if tap_type == 0:
                continue
            obj = ShortNote()
            obj.lane = lane_idx
            obj.measure = measure_value
            obj.tick = tick
            if note_type == "1":
                try:
                    obj.note_type = TapNoteType(tap_type)
                except ValueError:
                    continue
            else:
                try:
                    obj.note_type = AirNoteType(tap_type)
                except ValueError:
                    continue
            obj.width = width
            obj.speed = context.active_speed
            obj.attribute = context.active_attribute
            objects.append(obj)
        return objects

    if note_type in ("2", "3", "4"):
        if len(header) < 6:
            return []
        lane_idx = _sus_lane_char_index(header[4])
        channel = header[5]
        try:
            nk = LongNoteKind(int(note_type))
        except ValueError:
            return []
        objects = []
        for tick, long_type, width in parsed_data:
            if long_type == 0:
                continue
            try:
                lnt = LongNoteType(long_type)
            except ValueError:
                continue
            obj = LongNote()
            obj.note_kind = nk
            obj.note_type = lnt
            obj.lane = lane_idx
            obj.measure = measure_value
            obj.tick = tick
            obj.width = width
            obj.speed = context.active_speed
            obj.attribute = context.active_attribute
            if channel not in context.channels:
                context.channels[channel] = []
            obj.linked = context.channels[channel]
            context.channels[channel].append(obj)
            tpb = max(1, int(context.ticks_per_beat))

            def _sort_key(item: LongNote) -> float:
                return item.measure + item.tick / float(
                    context.beats_from_bar.get(item.measure, 4.0) * tpb
                )

            context.channels[channel].sort(key=_sort_key)
            objects.append(obj)
        return objects

    return []
