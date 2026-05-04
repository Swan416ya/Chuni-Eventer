"""
将 **与模板 Waveform 条数一致** 的 WAV（顺序对应 AWB 槽位 0～N-1）重新编码为加密 HCA，
生成新的 ``.awb``，并在**原版 ACB 二进制**上就地修补流式引用：

- ``StreamAwbHash``：**MD5**（16 字节）整库校验，与 SEGA/CRI 流式 AWB 一致；
- ``StreamAwbAfs2Header``：与新版 ``.awb`` 文件头前缀对齐。

Cue / Sequence / Track / Waveform 元数据仍来自模板 **不作重写**
（PyCriCodecsEx 的 UTF 写出器无法无损回写该官方 ACB）。若你更换为**时长差异很大**
的素材，游戏内可能出现提前截断或计时偏差，需要 AtomCraft 等专业工具改表。

常见模板：60 条（如 ``systemvoice0054``）或 42 条（如 ``systemvoice0062``，省略 id 25～34）。
原版 ``systemvoice0054``：Cue ``0100``～``0113`` 与 ``0011``～``0024`` 共用波形，
模板里已配置好，无需在此脚本维护别名映射。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import wave
from pathlib import Path

from PyCriCodecsEx.acb import ACB
from PyCriCodecsEx.awb import AWB, AWBBuilder
from PyCriCodecsEx.chunk import CriHcaQuality
from PyCriCodecsEx.hca import HCACodec

from chuni_eventer_desktop.pjsk_audio_chuni import CHUNITHM_HCA_KEY


def _wav_frames_rate_ch(path: Path) -> tuple[int, int, int]:
    with wave.open(str(path), "rb") as w:
        return w.getnframes(), w.getframerate(), w.getnchannels()


def _natural_wav_sort(paths: list[Path]) -> list[Path]:
    def stem_num(p: Path) -> tuple[int, str]:
        m = re.search(r"_(\d+)\.wav$", p.name, flags=re.IGNORECASE)
        if m:
            return (int(m.group(1)), p.name.lower())
        m2 = re.match(r"^(\d+)\.wav$", p.name, flags=re.IGNORECASE)
        if m2:
            return (int(m2.group(1)), p.name.lower())
        return (10**9, p.name.lower())

    return sorted(paths, key=stem_num)


def repack_streaming_voice_bank(
    *,
    template_acb: Path,
    wav_paths: list[Path],
    out_acb: Path,
    out_awb: Path,
) -> None:
    template_awb = template_acb.with_suffix(".awb")
    if not template_awb.is_file():
        raise FileNotFoundError(f"缺少与模板同名的 AWB：{template_awb}")

    ref_awb = AWB(str(template_awb))
    parsed = ACB(str(template_acb))
    n_slots = len(parsed.payload["WaveformTable"][1])
    if len(wav_paths) != n_slots:
        raise ValueError(
            f"需要恰好 {n_slots} 个 WAV（与模板 WaveformTable 一致），当前为 {len(wav_paths)}"
        )

    encoded: list[bytes] = []
    for p in wav_paths:
        _nf, rate, _ch = _wav_frames_rate_ch(p)
        if rate != 48000:
            raise ValueError(f"采样率须为 48000 Hz（CHUNITHM 常用）：{p}")
        hc = HCACodec(str(p), key=CHUNITHM_HCA_KEY, quality=CriHcaQuality.Highest)
        encoded.append(hc.get_hca())

    sk = ref_awb.subkey
    if isinstance(sk, bytes):
        sk = int.from_bytes(sk, "little")

    awb_bytes = AWBBuilder(
        encoded,
        subkey=int(sk),
        version=int(ref_awb.version),
        id_intsize=int(ref_awb.id_intsize),
        align=int(ref_awb.align),
    ).build()

    template_awb_bytes = template_awb.read_bytes()
    old_md5 = hashlib.md5(template_awb_bytes).digest()
    new_md5 = hashlib.md5(awb_bytes).digest()

    acb_bin = bytearray(template_acb.read_bytes())
    if acb_bin.count(old_md5) != 1:
        raise RuntimeError(
            "无法在模板 ACB 中唯一标识 StreamAwbHash（MD5），请确认使用的是原版配对文件。"
        )
    idx_md5 = acb_bin.index(old_md5)
    acb_bin[idx_md5 : idx_md5 + 16] = new_md5

    old_hdr = parsed.payload["StreamAwbAfs2Header"][1][0]["Header"][1]
    if acb_bin.count(old_hdr) != 1:
        raise RuntimeError(
            "无法在模板 ACB 中唯一标识 StreamAwbAfs2Header 前缀，请勿混用不同版本的 ACB/AWB。"
        )
    idx_hdr = acb_bin.index(old_hdr)
    new_hdr = awb_bytes[: len(old_hdr)]
    if len(new_hdr) < len(old_hdr):
        new_hdr = new_hdr.ljust(len(old_hdr), b"\x00")
    elif len(new_hdr) > len(old_hdr):
        raise RuntimeError("新生成的 AWB 头前缀长于模板预留区，AWB 布局与模板不兼容。")
    acb_bin[idx_hdr : idx_hdr + len(old_hdr)] = new_hdr

    out_acb.parent.mkdir(parents=True, exist_ok=True)
    out_awb.parent.mkdir(parents=True, exist_ok=True)
    out_acb.write_bytes(bytes(acb_bin))
    out_awb.write_bytes(awb_bytes)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="N×WAV -> 流式 system voice ACB + AWB（二进制修补原版 ACB，N 由模板决定）"
    )
    ap.add_argument(
        "--template-acb",
        type=Path,
        required=True,
        help="原版 .acb（与同 stem 的 .awb 放在同一目录）",
    )
    ap.add_argument(
        "--wav-dir",
        type=Path,
        required=True,
        help="含 N 个 .wav 的目录（与模板槽位数一致；支持 1.wav 或 stem_N.wav，按数字排序）",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="输出目录（写入与模板同文件名的 .acb / .awb）",
    )
    args = ap.parse_args()

    wavs = sorted(args.wav_dir.glob("*.wav"))
    wavs = _natural_wav_sort(wavs)
    out_acb = args.out_dir / args.template_acb.name
    out_awb = args.out_dir / args.template_acb.with_suffix(".awb").name

    repack_streaming_voice_bank(
        template_acb=args.template_acb.resolve(),
        wav_paths=[p.resolve() for p in wavs],
        out_acb=out_acb.resolve(),
        out_awb=out_awb.resolve(),
    )
    print(f"已写入：\n  {out_acb}\n  {out_awb}")


if __name__ == "__main__":
    main()
