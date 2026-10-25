"""CHUNITHM Mate action-slot semantics and UI grouping.

The game-facing format always has 18 slots.  This module is the seam that lets
the UI offer either six useful scene groups or all 18 slots without duplicating
the expansion rules in PSB and GIF code paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TypeVar


@dataclass(frozen=True)
class MateActionGroup:
    key: str
    title: str
    description: str
    slots: tuple[int, ...]


ACTION_SLOT_HINTS: dict[int, str] = {
    1: "初始化/复位（默认待机）",
    2: "歌曲结算：D",
    3: "歌曲结算：C",
    4: "歌曲结算：B",
    5: "歌曲结算：BB",
    6: "歌曲结算：BBB",
    7: "歌曲结算：A",
    8: "歌曲结算：AA",
    9: "歌曲结算：AAA",
    10: "歌曲结算：S",
    11: "歌曲结算：S+",
    12: "歌曲结算：SS",
    13: "歌曲结算：SS+",
    14: "歌曲结算：SSS",
    15: "歌曲结算：SSS+",
    16: "Mate ROOM：开场（StartEmote）",
    17: "Mate ROOM：游戏中循环欢呼（CheerGameLoop）",
    18: "Mate ROOM：收尾（EndEmote）",
}


SIMPLE_ACTION_GROUPS: tuple[MateActionGroup, ...] = (
    MateActionGroup(
        "rank_d_bbb",
        "D ～ BBB",
        "歌曲结算低评价：Type 2～6，对应 D、C、B、BB、BBB。",
        (2, 3, 4, 5, 6),
    ),
    MateActionGroup(
        "rank_a_aaa",
        "A ～ AAA",
        "歌曲结算中段评价：Type 7～9，对应 A、AA、AAA。",
        (7, 8, 9),
    ),
    MateActionGroup(
        "rank_s_ss",
        "S ～ SS",
        "歌曲结算高评价：Type 10～12，对应 S、S+、SS。",
        (10, 11, 12),
    ),
    MateActionGroup(
        "rank_ssp_sssp",
        "SS+ ～ SSS+",
        "歌曲结算最高评价：Type 13～15，对应 SS+、SSS、SSS+。",
        (13, 14, 15),
    ),
    MateActionGroup(
        "default_room_edges",
        "默认 / ROOM 开场与收尾",
        "合并 Type 1、16、18：默认复位，以及 Mate ROOM 的 StartEmote / EndEmote。",
        (1, 16, 18),
    ),
    MateActionGroup(
        "room_loop",
        "Mate ROOM 游戏中循环",
        "Type 17：CheerGameLoop 中按 1000 ms 动作窗口与冷却计时反复触发。",
        (17,),
    ),
)


DETAILED_ACTION_GROUPS: tuple[MateActionGroup, ...] = tuple(
    MateActionGroup(
        f"type_{slot}",
        f"Type {slot}",
        ACTION_SLOT_HINTS[slot],
        (slot,),
    )
    for slot in range(1, 19)
)


_SLOT_TO_SIMPLE_KEY = {
    slot: group.key for group in SIMPLE_ACTION_GROUPS for slot in group.slots
}

T = TypeVar("T")


def expand_action_assignments(
    simple_values: Mapping[str, T],
    detailed_values: Mapping[int, T] | None = None,
) -> dict[int, T]:
    """Expand six simple values to 18 slots, with optional per-slot overrides.

    Missing or false-y detailed values inherit their simple group.  All six
    simple groups are required so the generated XML never contains an
    accidental empty action name or path.
    """
    missing = [g.key for g in SIMPLE_ACTION_GROUPS if not simple_values.get(g.key)]
    if missing:
        raise ValueError(f"缺少简略动作组：{', '.join(missing)}")
    detailed_values = detailed_values or {}
    return {
        slot: detailed_values.get(slot) or simple_values[_SLOT_TO_SIMPLE_KEY[slot]]
        for slot in range(1, 19)
    }


def simple_group_for_slot(slot: int) -> MateActionGroup:
    """Return the simple-mode group inherited by one game-facing slot."""
    key = _SLOT_TO_SIMPLE_KEY[slot]
    return next(group for group in SIMPLE_ACTION_GROUPS if group.key == key)
