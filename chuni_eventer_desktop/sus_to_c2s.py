"""
SUS（Sliding Universal Score）→ CHUNITHM c2s。

PJSK 侧固定拉取：normal / hard / expert / master / append（有 append 才有对应 Ultima 槽位）。

映射到 CHUNITHM 五档：BASIC(简)/ADVANCED(普)/EXPERT/MASTER/ULTIMA。
其中 PJSK「normal」对应中二 Basic（常称 Easy），「hard」对应 Advanced（常称 Advanced，勿与 PJSK 的 append 混淆）。

参考：PjskSUSPatcher https://github.com/Qrael/PjskSUSPatcher

PJSK 原始资源缓存在 ACUS 同级的 pjsk_cache/（见 pjsk_cache_root），
在完成转换前不会写入 ACUS 目录内。
"""

from __future__ import annotations

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


def chuni_slot_name_for_pjsk(pjsk_difficulty: str) -> str | None:
    return PJSK_TO_CHUNI_SLOT.get((pjsk_difficulty or "").strip().lower())


def try_convert_sus_to_c2s_bytes(_sus_text: str) -> bytes | None:
    """
    将 SUS 正文转为 c2s 二进制。

    当前未实现真正的格式转换，返回 None（由调用方只写入 .sus，不写 .c2s）。
    """
    return None


def convert_sus_to_c2s(_sus_text: str) -> str:
    """历史占位接口；请使用 try_convert_sus_to_c2s_bytes。"""
    raise NotImplementedError(
        "SUS → c2s 尚未实现；请使用 try_convert_sus_to_c2s_bytes 或后续版本。"
    )
