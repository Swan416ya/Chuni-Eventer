"""
SUS（Sliding Universal Score）→ CHUNITHM c2s。

PJSK 侧固定拉取：normal / hard / expert / master / append（有 append 才有对应 Ultima 槽位）。

映射到 CHUNITHM 五档：BASIC(简)/ADVANCED(普)/EXPERT/MASTER/ULTIMA。
其中 PJSK「normal」对应中二 Basic（常称 Easy），「hard」对应 Advanced。

**转换算法**基于 [Soyandroid/suspect](https://github.com/Soyandroid/suspect)（MIT 式社区工具；见 ``chuni_eventer_desktop/_suspect/`` 内派生代码），
并在此基础上增加：`REQUEST ticks_per_beat`、小节拍长 `#mmm02`、小节号十进制/十六进制、
以及 PJSK/Seaurchin 轨宽到中二地面轨的偏移与宽度钳位。

可玩性后处理（见 ``apply_playability_filters``）：去掉 Air-down 及同位 TAP；去掉与长条末尾重合的 EXTAP（CHR）；
去掉最左五条地面轨上宽度为 1 的 TAP/MNE/CHR/FLK/HLD/Slide。

参考：PjskSUSPatcher https://github.com/Qrael/PjskSUSPatcher
"""

from __future__ import annotations

from ._suspect.c2s_emit import BpmSetting, C2S_TICKS_PER_MEASURE, create_file
from ._suspect.convert_core import apply_playability_filters, remap_lanes_pjsk_to_chuni, sus_to_c2s
from ._suspect.sus_parser import main_bpm_for_context, parse_sus_document

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

CTS_RESOLUTION = C2S_TICKS_PER_MEASURE


def chuni_slot_name_for_pjsk(pjsk_difficulty: str) -> str | None:
    return PJSK_TO_CHUNI_SLOT.get((pjsk_difficulty or "").strip().lower())


def convert_sus_to_c2s(sus_text: str) -> str:
    objs, ctx = parse_sus_document(sus_text)
    definitions, notes = sus_to_c2s(objs, timing=ctx)
    remap_lanes_pjsk_to_chuni(notes)
    notes = apply_playability_filters(notes)

    has_bpm0 = any(
        isinstance(d, BpmSetting) and int(d.measure) == 0 and int(d.tick) == 0
        for d in definitions
    )
    if not has_bpm0:
        b0 = BpmSetting()
        b0.measure = 0
        b0.tick = 0
        b0.bpm = float(main_bpm_for_context(ctx))
        definitions.insert(0, b0)

    definitions.sort(
        key=lambda d: (
            d.measure,
            d.tick,
            0 if isinstance(d, BpmSetting) else 1,
        )
    )

    bpm_def = float(main_bpm_for_context(ctx))
    creator = (ctx.designer or "").strip() or "PJSK SUS import"
    return create_file(
        definitions,
        notes,
        creator=creator,
        bpm_def=bpm_def,
    )


def try_convert_sus_to_c2s_bytes(sus_text: str) -> bytes | None:
    """将 SUS 正文转为 c2s UTF-8 文本字节。解析或生成失败时返回 None。"""
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
