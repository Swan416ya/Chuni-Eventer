"""
SUS（Sliding Universal Score）→ CHUNITHM c2s。

PJSK 侧固定拉取：normal / hard / expert / master / append（有 append 才有对应 Ultima 槽位）。

映射到 CHUNITHM 五档：BASIC(简)/ADVANCED(普)/EXPERT/MASTER/ULTIMA。
其中 PJSK「normal」对应中二 Basic（常称 Easy），「hard」对应 Advanced。

当前实现委托给 `PenguinTools.CLI chart convert`，不再维护本仓库内的自定义 SUS→c2s 生成逻辑。
"""

from __future__ import annotations

from .penguin_tools_cli import convert_chart_text_with_penguin_tools_cli

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

CTS_RESOLUTION = 384


def chuni_slot_name_for_pjsk(pjsk_difficulty: str) -> str | None:
    return PJSK_TO_CHUNI_SLOT.get((pjsk_difficulty or "").strip().lower())


def convert_sus_to_c2s(sus_text: str) -> str:
    return convert_chart_text_with_penguin_tools_cli(text=sus_text, suffix=".sus")


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
