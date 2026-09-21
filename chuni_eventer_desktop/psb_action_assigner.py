"""PSB 动作分配器：解包 PSB，列出 timeline，供用户分配到 CHUNITHM 动作槽。"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass
class TimelineInfo:
    """单个 timeline 的元数据。"""
    label: str
    diff: int  # 0=主动作, 1=差动作


@dataclass
class PsbActionData:
    """PSB 解包后的动作数据。"""
    psb_path: Path
    timelines: list[TimelineInfo] = field(default_factory=list)
    platform: str = ""

    @property
    def main_timelines(self) -> list[TimelineInfo]:
        return [t for t in self.timelines if t.diff == 0]

    @property
    def diff_timelines(self) -> list[TimelineInfo]:
        return [t for t in self.timelines if t.diff == 1]


class PsbActionAssigner:
    """PSB 解包 + timeline 提取。"""

    def __init__(self, freemote_dir: Path) -> None:
        self._freemote = freemote_dir
        self._psb_decompile = freemote_dir / "PsbDecompile.exe"
        self._psbuild = freemote_dir / "PsBuild.exe"

    def decompile(self, psb_path: Path, work_dir: Path) -> PsbActionData:
        """解包 PSB，提取 timeline 列表。

        Args:
            psb_path: PSB 文件路径
            work_dir: 临时工作目录（解包产物放这里）

        Returns:
            PsbActionData 对象，包含所有 timeline
        """
        work_dir.mkdir(parents=True, exist_ok=True)

        # 1. 解包 PSB（大模型可能超过 1 分钟, 给足余量）
        out_dir = work_dir / "decompiled"
        try:
            proc = subprocess.run(
                [str(self._psb_decompile), str(psb_path), "-o", str(out_dir)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=600,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("PsbDecompile 解包超时（10 分钟），模型可能过大或损坏") from e
        if proc.returncode != 0:
            raise RuntimeError(f"PsbDecompile 失败:\n{proc.stdout}\n{proc.stderr}")

        # 2. 找到解包后的 JSON
        json_files = list(out_dir.glob("*.json"))
        json_files = [f for f in json_files if not f.name.endswith(".resx.json")]
        if not json_files:
            raise RuntimeError(f"解包后未找到 JSON 文件: {out_dir}")
        json_path = json_files[0]

        # 3. 读取 timeline
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        metadata = data.get("metadata", {})
        timeline_control = metadata.get("timelineControl", [])

        timelines = []
        for tl in timeline_control:
            if not isinstance(tl, dict):
                continue
            label = tl.get("label", "")
            diff = tl.get("diff", 0)
            timelines.append(TimelineInfo(label=label, diff=diff))

        # 4. 检测平台
        platform = data.get("spec", "unknown")

        return PsbActionData(
            psb_path=psb_path,
            timelines=timelines,
            platform=platform,
        )

    def extract_preview_texture(self, work_dir: Path) -> Path | None:
        """从解包目录里挑一张最大的纹理 PNG 作为预览立绘。

        Args:
            work_dir: 之前 decompile() 用的工作目录（里面应有 decompiled/）

        Returns:
            PNG 路径；找不到返回 None
        """
        pngs = list((work_dir / "decompiled").rglob("*.png"))
        if not pngs:
            return None
        return max(pngs, key=lambda p: p.stat().st_size)

    def port_to_common(self, psb_path: Path, output_emtbytes: Path) -> None:
        """将 PSB port 成 common 平台，输出 emtbytes。

        Args:
            psb_path: 原始 PSB 路径
            output_emtbytes: 输出 emtbytes 路径
        """
        proc = subprocess.run(
            [
                str(self._psbuild), "port",
                "-p", "common",
                "-o", str(output_emtbytes),
                str(psb_path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=600,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"PsBuild port 失败:\n{proc.stdout}\n{proc.stderr}")

        if not output_emtbytes.exists():
            raise RuntimeError(f"port 后未生成文件: {output_emtbytes}")


# CHUNITHM 动作槽语义说明（对照 mate000101 官方规范）
ACTION_SLOT_HINTS: dict[int, str] = {
    1: "初始化/待机（idle 循环）",
    2: "生气",
    3: "悲伤",
    4: "开心（基础版）",
    5: "开心（基础版）",
    6: "开心（基础版）",
    7: "开心（基础版）",
    8: "开心（基础版）",
    9: "开心（基础版）",
    10: "开心（强化版）",
    11: "开心（强化版）",
    12: "开心（强化版）",
    13: "开心（强化版）",
    14: "开心（特殊版，isSpecialMotion=true）",
    15: "开心（特殊版，isSpecialMotion=true）",
    16: "开心（语音版，但我们 isVoice=false）",
    17: "开心（语音版，但我们 isVoice=false）",
    18: "开心（语音特殊版，但我们 isVoice=false）",
}


def generate_mate_xml(
    mate_id: int,
    name: str,
    chara_id: int,
    chara_name: str,
    emote_filename: str,
    dds_filename: str,
    slot_assignments: dict[int, str],  # {actionType: timeline_label}
    dds_illust_key: str = "",
    system_voice_id: int = 0,
    pos_x: int = 1,
    pos_y: int = -50,
    scale_x10000: int = 6000,
) -> str:
    """生成 Mate.xml 字符串。

    Args:
        mate_id: Mate ID（如 31004）
        name: Mate 显示名
        chara_id: 关联的 Chara ID
        chara_name: 关联的 Chara 显示名
        emote_filename: emtbytes 文件名
        dds_filename: DDS 图标文件名
        slot_assignments: 动作槽分配 {actionType: timeline_label}
        pos_x: X 位置
        pos_y: Y 位置
        scale_x10000: 缩放（万分之一）

    Returns:
        Mate.xml 字符串
    """
    if not dds_illust_key:
        dds_illust_key = f"chara{chara_id // 1000:04d}_00"
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<MateData xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
        f'  <dataName>mate{mate_id:06d}</dataName>',
        '  <disableFlag>false</disableFlag>',
        f'  <name><id>{mate_id}</id><str>{name}</str><data /></name>',
        '  <defaultHave>true</defaultHave>',
        f'  <emoteFile><path>{emote_filename}</path></emoteFile>',
        f'  <image><path>{dds_filename}</path></image>',
        f'  <chara><id>{chara_id}</id><str>{chara_name}</str><data /></chara>',
        f'  <ddsIllust><id>{chara_id}</id><str>{dds_illust_key}</str><data /></ddsIllust>',
        f'  <systemVoiceId>{system_voice_id}</systemVoiceId>',
        '  <texSizeX>1024</texSizeX>',
        '  <texSizeY>1024</texSizeY>',
        f'  <posX>{pos_x}</posX>',
        f'  <posY>{pos_y}</posY>',
        f'  <scaleX10000>{scale_x10000}</scaleX10000>',
        '  <rewards />',
        '  <actions>',
    ]

    for action_type in range(1, 19):
        emote_label = slot_assignments.get(action_type, "平常")
        lines.extend([
            '    <MateActionData>',
            f'      <mateActionId>{mate_id:06d}{action_type:02d}</mateActionId>',
            f'      <mate><id>{mate_id}</id><str>{name}</str><data /></mate>',
            f'      <actionType>{action_type}</actionType>',
            f'      <emote>{emote_label}</emote>',
            '      <isVoice>false</isVoice>',
            '      <isLipSync>false</isLipSync>',
            '      <isSpecialMotion>false</isSpecialMotion>',
            '      <isEmoteEndReset>false</isEmoteEndReset>',
            '      <msecEmoteEnd>0</msecEmoteEnd>',
            '      <cueId>0</cueId>',
            '    </MateActionData>',
        ])

    lines.extend([
        '  </actions>',
        '</MateData>',
    ])

    return "\n".join(lines)
