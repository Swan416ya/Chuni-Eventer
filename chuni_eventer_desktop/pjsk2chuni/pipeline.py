"""PJSK 官谱 → CHUNITHM 成品包（应用侧接线）。

上游转谱逻辑（``.sus`` → ``.ugc``）原样收录在 :mod:`.core`，本模块只做"产品侧"的四件事：

1. **元数据补全**：``core.write_ugc`` 写出的是"裸"UGC；这里把头部补成可直接交给
   PenguinTools 打包的工程谱面 —— ``@DIFF/@LEVEL/@CONST/@GENRE/@JACKET/@SONGID``
   以及 ``@FLAG SOFFSET TRUE``（用户库惯例，见上游 ``docs/06 §6``）。
2. **音频对齐**：先 ffmpeg 解码成 48 kHz 立体声 WAV（**不裁片头**），再用
   ``core.measure_leading_silence`` 量真实前导静音 → ``@BGMOFS = -前导静音``；
   真实偏移由 PenguinTools 按 ``SOFFSET`` 规则换算（``real = manual + 1 小节``）。
   这是"音频延迟不对"的根因修复：不再硬编任何固定秒数。
3. **打包**：组装 UMIGURI 工程目录（``options.json`` + ``*.ugc`` + 音频 + 封面）并调用官方 CLI
   ``option build`` 出整包（c2s / HCA ACB·AWB / DDS 封面 / Music.xml / CueFile.xml）。
4. **落位**：规范化（c2s→CRLF、XML 去 BOM）后复制进 ACUS，并补 MusicSort / ULT 解锁事件。

上游文档：``pjsk2chuni/docs/01-why.md``（设计裁定）、``03-conversion-logic.md``（代码地图）、
``05-penguintools.md``（CLI 调用与坑）、``06-package-conventions.md``（成品包规范）。
"""

from __future__ import annotations

import json
import shutil
import tempfile
import types
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .. import penguin_tools_cli
from ..pjsk_audio_chuni import CHUNITHM_HCA_KEY, ffmpeg_trim_to_chuni_wav
from . import core

LogFn = Callable[[str], None]
ProgressFn = Callable[[str, float], None]

# CHUNITHM 槽位（与 pjsk_sheet_client 的 PJSK_TO_CHUNI_SLOT 一一对应）
SLOT_ORDER: tuple[str, ...] = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA")

# UGC 头部 @DIFF 取值 → PenguinTools Difficulty。
# 注意 UGC 与 PenguinTools 枚举在末两位是错位的：UGC 4=WORLD'S END、5=Ultima。
SLOT_UGC_DIFF: dict[str, int] = {
    "BASIC": 0,
    "ADVANCED": 1,
    "EXPERT": 2,
    "MASTER": 3,
    "ULTIMA": 5,
}

# --main-difficulty <songId>:<Difficulty> 用的 PenguinTools 枚举名（决定 Music.xml 的 enableUltima 等）
SLOT_PT_MAIN_NAME: dict[str, str] = {
    "BASIC": "Basic",
    "ADVANCED": "Advanced",
    "EXPERT": "Expert",
    "MASTER": "Master",
    "ULTIMA": "Ultima",
}

GENRE_ID = 2
GENRE_NAME = "niconico"
RELEASE_TAG_ID = -2
RELEASE_TAG_NAME = "PJSK"

# PJSK 难度（小写）→ 中二槽位：下载链路沿用原实现（不含 easy）
PJSK_CHUNI_DOWNLOAD_ORDER: tuple[str, ...] = (
    "normal",
    "hard",
    "expert",
    "master",
    "append",
)
PJSK_TO_CHUNI_SLOT: dict[str, str] = {
    "normal": "BASIC",
    "hard": "ADVANCED",
    "expert": "EXPERT",
    "master": "MASTER",
    "append": "ULTIMA",
}


def chuni_slot_name_for_pjsk(pjsk_difficulty: str) -> str | None:
    return PJSK_TO_CHUNI_SLOT.get((pjsk_difficulty or "").strip().lower())


# PJSK 谱面等级（1..38）等比映射到中二定数（1.0..15.5）：
#   const = 1 + (L - 1) * (15.5 - 1) / (38 - 1)
PJSK_LEVEL_RANGE: tuple[float, float] = (1.0, 38.0)
CHUNI_CONST_RANGE: tuple[float, float] = (1.0, 15.5)


def pjsk_level_to_chuni_const(play_level: float) -> float:
    """PJSK 难度等级（1..38）→ 中二定数（1.0..15.5，两位小数）。

    例：12 → 5.31、18 → 7.66、24 → 10.01、30 → 12.36、38 → 15.50。
    """
    lo_l, hi_l = PJSK_LEVEL_RANGE
    lo_c, hi_c = CHUNI_CONST_RANGE
    lv = min(max(float(play_level), lo_l), hi_l)
    return round(lo_c + (lv - lo_l) * (hi_c - lo_c) / (hi_l - lo_l), 2)


def const_to_level_pair(const: float) -> tuple[int, int]:
    """定数 → Music.xml 的 ``(level, levelDecimal)``（12.6 → (12, 60)）。"""
    const = max(0.0, float(const))
    whole = int(const)
    dec = int(round((const - whole) * 100))
    if dec >= 100:
        whole, dec = whole + 1, 0
    return whole, dec

# 与用户库惯例（以及上游 build_option.py 默认）一致
BUILD_BATCH_SIZE = 8
_HEAD_END = "@ENDHEAD"


def _noop(_msg: str) -> None:
    return


# --------------------------------------------------------------------------- UGC 头部


def patch_ugc_header(
    text: str,
    updates: dict[str, str | None],
    *,
    flags: dict[str, str] | None = None,
    insert_order: Sequence[str] = (),
) -> str:
    """在 UGC 头部（``@ENDHEAD`` 之前）就地改写 ``@KEY`` 行；缺失的键/FLAG 追加在头部末尾。

    ``updates`` 的键不含 ``@``；值为 ``None`` 表示删除该键。``flags`` 是 ``@FLAG <KEY> <VALUE>``。
    """
    up = {k.upper(): v for k, v in updates.items()}
    fl = {k.upper(): v for k, v in (flags or {}).items()}
    lines = text.splitlines()
    head: list[str] = []
    tail: list[str] = []
    seen_keys: set[str] = set()
    seen_flags: set[str] = set()
    in_head = True

    for raw in lines:
        if not in_head:
            tail.append(raw)
            continue
        stripped = raw.strip()
        if stripped == _HEAD_END:
            in_head = False
            tail.append(raw)
            continue
        if stripped.startswith("@"):
            key = stripped[1:].split("\t", 1)[0].strip().upper()
            if key == "FLAG":
                parts = stripped.split("\t")
                fkey = parts[1].strip().upper() if len(parts) > 1 else ""
                if fkey and fkey in fl:
                    seen_flags.add(fkey)
                    head.append(f"@FLAG\t{fkey}\t{fl[fkey]}")
                    continue
            elif key in up:
                seen_keys.add(key)
                value = up[key]
                if value is None:
                    continue
                head.append(f"@{key}\t{value}")
                continue
        head.append(raw)

    missing: list[str] = []
    for key in list(insert_order) + list(up):
        upper = key.upper()
        if upper in up and upper not in seen_keys and up[upper] is not None:
            missing.append(f"@{upper}\t{up[upper]}")
            seen_keys.add(upper)
    for fkey in fl:
        if fkey not in seen_flags:
            missing.append(f"@FLAG\t{fkey}\t{fl[fkey]}")

    out = head + missing + tail
    joined = "\n".join(out)
    if text.endswith("\n"):
        joined += "\n"
    return joined


# --------------------------------------------------------------------------- 单难度转换


@dataclass(frozen=True)
class SlotSource:
    """一个目标槽位与其 PJSK 源 SUS。"""

    slot: str
    sus_path: Path


@dataclass
class SlotResult:
    slot: str
    sus_path: Path
    ugc_path: Path
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def summary_line(self) -> str:
        c = self.counts
        return (
            f"{self.slot}: TAP {c.get('tap', 0)}  CHR {c.get('chr', 0)}  "
            f"HOLD {c.get('hold', 0)}  SLIDE {c.get('slide', 0)}（{c.get('slide_segments', 0)} 段）  "
            f"AIR {c.get('air', 0)}  ALD {c.get('ald', 0)}"
        )


def _model_counts(mdl) -> dict[str, int]:
    k = dict(mdl.counts)
    k["tap"] = sum(1 for g in mdl.grounds if not g.crit)
    k["chr"] = sum(1 for g in mdl.grounds if g.crit)
    k["hold"] = len(mdl.holds)
    k["slide"] = len(mdl.slides)
    k["slide_segments"] = int(k.get("slide_segs", 0))
    return k


def convert_sus_to_ugc(
    source: SlotSource,
    out_ugc: Path,
    *,
    title: str,
    artist: str,
    creator: str,
    songid: int,
    level_const: float,
    jacket_name: str,
    bgm_name: str,
    bgm_offset_sec: float,
    preview: tuple[float, float],
    work_dir: Path,
    is_main: bool | None = None,
    decorations: str = "all",
    crush_h: float = 1.0,
) -> SlotResult:
    """单个 PJSK SUS → 可直接打包的 UGC（含头部元数据）。"""
    slot = source.slot.upper()
    if slot not in SLOT_UGC_DIFF:
        raise ValueError(f"未知槽位：{source.slot}")
    sus_path = Path(source.sus_path)
    if not sus_path.is_file():
        raise FileNotFoundError(f"缺少 SUS：{sus_path}")

    sus = core.parse_sus(sus_path)
    # 上游 parse_sus 从文件名推断 songId/难度；本工程的缓存文件名为 normal.sus / master.sus，
    # 无法据此推断，因此元数据一律由调用方显式给全，并在下面打头部补丁。
    sus.songid = str(int(songid))
    sus.title = title or sus.title
    sus.artist = artist or sus.artist
    sus.designer = creator
    sus.diff_name = ""

    opts = types.SimpleNamespace(
        title=title,
        artist=artist,
        level=str(level_const),
        creator=creator,
        songid=str(int(songid)),
        bgm=bgm_name,
        # 数值字符串：绕开 core 里 "auto" 分支的 print()（打包后 sys.stdout 可能为 None）
        bgmofs=f"{float(bgm_offset_sec):.5f}",
        bgmprv=(float(preview[0]), float(preview[1])),
        outdir=str(work_dir),
        decorations=decorations,
        crush_h=float(crush_h),
        no_merge=False,
        formats=["ugc"],
    )

    mdl = core.build_model(sus, opts)
    out_ugc = Path(out_ugc)
    out_ugc.parent.mkdir(parents=True, exist_ok=True)
    core.write_ugc(mdl, sus, opts, out_ugc)

    text = out_ugc.read_text(encoding="utf-8")
    updates: dict[str, str | None] = {
        "TITLE": title,
        "SORT": title,
        "ARTIST": artist,
        "DESIGN": creator,
        "DIFF": str(SLOT_UGC_DIFF[slot]),
        "LEVEL": str(int(level_const)),
        "CONST": f"{float(level_const):.2f}",
        "GENRE": GENRE_NAME,
        "JACKET": jacket_name,
        "SONGID": str(int(songid)),
        "BGM": bgm_name,
        "BGMOFS": f"{float(bgm_offset_sec):.5f}",
        "BGMPRV": f"{float(preview[0]):.2f}\t{float(preview[1]):.2f}",
    }
    if is_main is not None:
        # PenguinTools 默认把每张谱都当"主谱"，主谱决定 Music.xml 的 enableUltima 等字段
        updates["CMT"] = f"#meta main {'true' if is_main else 'false'}"
    text = patch_ugc_header(
        text,
        updates,
        flags={"SOFFSET": "TRUE"},
        insert_order=(
            "TITLE", "SORT", "ARTIST", "GENRE", "DESIGN", "DIFF", "LEVEL", "CONST",
            "JACKET", "SONGID", "CMT",
        ),
    )
    out_ugc.write_text(text, encoding="utf-8")
    return SlotResult(
        slot=slot,
        sus_path=sus_path,
        ugc_path=out_ugc,
        counts=_model_counts(mdl),
        warnings=list(mdl.warn),
    )


# --------------------------------------------------------------------------- 打包


@dataclass
class BuildRequest:
    bundle_root: Path
    slots: Sequence[SlotSource]
    chuni_music_id: int
    title: str
    artist: str
    jacket_png: Path
    audio_src: Path
    creator: str = "chunieventer"
    # 槽位 → 定数（如 12.6）；缺省槽位不参与
    levels: dict[str, float] = field(default_factory=dict)
    preview_start_sec: float = 0.0
    preview_stop_sec: float = 30.0
    work_dir: Path | None = None
    decorations: str = "all"
    crush_h: float = 1.0
    ignore_cache: bool = False
    # 非 None 时改写 Music.xml 的 <stageName>（PT 默认给 8 / レーベル 共通0008_新イエローリング）
    stage_id: int | None = None
    stage_str: str = ""


@dataclass
class BuildResult:
    music_id: int
    package_root: Path
    output_root: Path
    music_dir: Path
    cue_dir: Path
    slots: dict[str, SlotResult]
    audio_wav: Path
    # 从音频实测到的前导静音（秒）与写进 @BGMOFS 的手动偏移（本侧先裁掉前导静音，故为 0）
    measured_leading_silence_sec: float = 0.0
    manual_offset_sec: float = 0.0
    warnings: list[str] = field(default_factory=list)
    option_scan: dict | None = None

    @property
    def has_ultima(self) -> bool:
        return "ULTIMA" in self.slots


def _slot_list(slots: Sequence[SlotSource]) -> list[SlotSource]:
    by_slot = {s.slot.upper(): s for s in slots}
    unknown = sorted(set(by_slot) - set(SLOT_ORDER))
    if unknown:
        raise ValueError(f"未知槽位：{', '.join(unknown)}")
    return [by_slot[s] for s in SLOT_ORDER if s in by_slot]


def prepare_48k_wav(src: Path, dst: Path, *, trim_leading_sec: float = 0.0, log: LogFn = _noop) -> Path:
    """解码为 48 kHz 立体声 16-bit WAV；``trim_leading_sec`` 从头部裁掉（0 = 原样）。

    已存在且比源新的产物会复用（缓存键含裁切量，避免张冠李戴）。
    """
    src = Path(src).resolve()
    dst = Path(dst).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"未找到音频：{src}")
    if dst.is_file() and dst.stat().st_size > 44 and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    trim = float(trim_leading_sec)
    log(f"音频：ffmpeg 解码为 48k WAV{'（裁掉前导静音 %.3fs）' % trim if trim > 1e-4 else ''}…")
    ffmpeg_trim_to_chuni_wav(
        src,
        dst,
        trim_leading_sec=trim,
        on_stderr_line=lambda line: log(line.strip()) if "time=" in line else None,
    )
    return dst


def build_option_package(
    req: BuildRequest,
    *,
    log: LogFn = _noop,
    on_progress: ProgressFn | None = None,
) -> BuildResult:
    """SUS 集合 → PenguinTools ``option build`` 完整包（返回的 ``output_root`` 由调用方清理）。"""
    slots = _slot_list(req.slots)
    if not slots:
        raise ValueError("没有任何可转换的谱面槽位。")
    if not any(s.slot in ("BASIC", "ADVANCED", "EXPERT", "MASTER") for s in slots):
        raise ValueError("至少需要 BASIC～MASTER 中一张谱面。")

    mid = int(req.chuni_music_id)
    bundle_root = Path(req.bundle_root).resolve()
    work = Path(req.work_dir).resolve() if req.work_dir else (bundle_root / "chuni_build")
    work.mkdir(parents=True, exist_ok=True)

    jacket_src = Path(req.jacket_png).resolve()
    if not jacket_src.is_file():
        raise FileNotFoundError(f"缺少封面：{jacket_src}")

    warnings: list[str] = []
    total = 4 + len(slots) * 2
    step = 0

    def bump(msg: str) -> None:
        nonlocal step
        step += 1
        if on_progress:
            on_progress(msg, min(1.0, step / max(1, total)))
        log(msg)

    # ---- 音频对齐 ----
    # 先量真实前导静音（= pjsk fillerSec），再由本侧裁掉它，然后只让 SOFFSET 生效：
    #   @BGMOFS = 0，SOFFSET=TRUE ⇒ PenguinTools 真实偏移 = +1 小节（正数 → mua adelay 插入空白小节）。
    # 为什么不用上游的 @BGMOFS = -前导静音：部分 mua_wav 版本（如 2.3.3 资源）会把
    # `-o -7.19` 里的负号当成选项而报错，导致音频静默转换失败（CLI 仍返回 success）。
    # 两种做法在时间轴上等价，且这里同样是正偏移 → mua 一定会跑 loudnorm（游戏要求响度归一）。
    bump("准备 48k 音频…")
    full_wav = prepare_48k_wav(req.audio_src, work / f"pjsk_{mid:04d}_48k.wav", log=log)
    trim = core.measure_leading_silence(full_wav)
    if trim is None:
        warnings.append("无法测量音频前导静音（非 16bit WAV / 读取失败 / 全程静音），按无前导静音处理。")
        trim = 0.0
    trim = max(0.0, float(trim))
    if trim > 1e-4:
        audio_wav = prepare_48k_wav(
            req.audio_src,
            work / f"pjsk_{mid:04d}_48k_trim{trim:.3f}.wav",
            trim_leading_sec=trim,
            log=log,
        )
    else:
        audio_wav = full_wav
    manual_offset = 0.0
    log(
        f"前导静音 {trim:.3f}s（fillerSec）→ 已裁掉；@BGMOFS {manual_offset:.5f}"
        f" + SOFFSET（+1 小节）交给 PenguinTools"
    )
    bump("已对齐音频…")

    jacket_name = f"jacket_{mid:04d}{jacket_src.suffix.lower() or '.png'}"
    shutil.copy2(jacket_src, work / jacket_name)

    slot_results: dict[str, SlotResult] = {}
    main_slot = "ULTIMA" if any(s.slot == "ULTIMA" for s in slots) else slots[-1].slot
    for source in slots:
        level = float(req.levels.get(source.slot, 0.0))
        result = convert_sus_to_ugc(
            source,
            work / f"{source.slot.lower()}.ugc",
            title=req.title,
            artist=req.artist,
            creator=req.creator,
            songid=mid,
            level_const=level,
            jacket_name=jacket_name,
            bgm_name=audio_wav.name,
            bgm_offset_sec=manual_offset,
            preview=(req.preview_start_sec, req.preview_stop_sec),
            work_dir=work,
            is_main=(source.slot == main_slot),
            decorations=req.decorations,
            crush_h=req.crush_h,
        )
        slot_results[source.slot] = result
        warnings.extend(f"{source.slot}: {w}" for w in result.warnings[:8])
        log(f"已生成 {result.ugc_path.name}（{result.summary_line()}）")
        bump(f"已生成 {source.slot} 谱面…")

    # options.json：键名/类型对齐 PenguinTools 2.3.3 的 OptionDocument（camelCase、大小写敏感）
    options = {
        "optionName": str(mid),
        "optionId": uuid.uuid4().hex,
        "convertChart": True,
        "chartFileDiscovery": ["ugc"],
        "convertAudio": True,
        "convertJacket": True,
        "convertBackground": False,
        "hcaEncryptionKey": int(CHUNITHM_HCA_KEY),
        "generateEventXml": False,
        "customReleaseTagXml": True,
        "customReleaseTagId": int(RELEASE_TAG_ID),
        "customReleaseTagTitleName": RELEASE_TAG_NAME,
        "selectedGenreId": int(GENRE_ID),
        "overrideChartGenre": False,
        "ultimaEventId": 1000001,
        "weEventId": 1000002,
        "batchSize": BUILD_BATCH_SIZE,
    }
    (work / "options.json").write_text(
        json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bump("已写入 options.json…")

    # 主难度 = ULTIMA（若存在）：Music.xml 的 <enableUltima> 取自主谱面
    output_root = Path(tempfile.mkdtemp(prefix=f"chuni-pjsk-{mid:04d}-"))
    log(f"PenguinTools：option build → {output_root.name}")
    payload = penguin_tools_cli.build_option_with_penguin_tools_cli(
        input_dir=work,
        output_dir=output_root,
        genre_id=GENRE_ID,
        release_tag_id=RELEASE_TAG_ID,
        release_tag_name=RELEASE_TAG_NAME,
        main_difficulties=[f"{mid}:{SLOT_PT_MAIN_NAME[main_slot]}"],
        hca_key=int(CHUNITHM_HCA_KEY),
        ignore_cache=req.ignore_cache,
    )
    for msg in penguin_tools_cli.cli_diagnostic_messages(payload, severity="warning"):
        if "more_than_one_chart_marked_main" in msg:  # 多主谱警告：用户旧包同样存在，无害
            continue
        warnings.append(f"PenguinTools: {msg}")
    bump("PenguinTools 打包完成…")

    package_root = _locate_package_root(output_root, mid)
    music_dir = package_root / "music" / f"music{mid:04d}"
    cue_dir = package_root / "cueFile" / f"cueFile{mid:06d}"
    if not music_dir.is_dir():
        raise RuntimeError(f"打包结果缺少谱面目录：{music_dir}")
    if not cue_dir.is_dir():
        raise RuntimeError(f"打包结果缺少音频目录：{cue_dir}")
    normalize_package(package_root, mid)
    if req.stage_id is not None:
        patch_music_xml_stage(music_dir, stage_id=int(req.stage_id), stage_str=req.stage_str)
    _verify_package(package_root, mid, expect_cue=True)
    bump("已规范化输出…")

    return BuildResult(
        music_id=mid,
        package_root=package_root,
        output_root=output_root,
        music_dir=music_dir,
        cue_dir=cue_dir,
        slots=slot_results,
        audio_wav=audio_wav,
        measured_leading_silence_sec=trim,
        manual_offset_sec=manual_offset,
        warnings=warnings,
    )


def _locate_package_root(output_root: Path, music_id: int) -> Path:
    direct = output_root / str(int(music_id))
    if (direct / "music").is_dir():
        return direct
    for cand in sorted(output_root.glob("*/music")):
        if (cand / f"music{int(music_id):04d}").is_dir():
            return cand.parent
    if (output_root / "music").is_dir():
        return output_root
    raise RuntimeError(f"PenguinTools 输出中未找到 music/music{int(music_id):04d}：{output_root}")


def normalize_package(package_root: Path, music_id: int) -> None:
    """c2s → CRLF；XML 去 BOM（对齐用户库惯例，上游 docs/06 §5）。"""
    mid = int(music_id)
    music_dir = package_root / "music" / f"music{mid:04d}"
    for f in sorted(music_dir.glob("*.c2s")):
        data = f.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        f.write_bytes(data)
    xml_files = list(music_dir.glob("*.xml")) + list(
        (package_root / "cueFile" / f"cueFile{mid:06d}").glob("*.xml")
    )
    for f in xml_files:
        data = f.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            f.write_bytes(data[3:])


def patch_music_xml_stage(music_dir: Path, *, stage_id: int, stage_str: str) -> None:
    """改写 Music.xml 的 ``<stageName>``（PT 没有 UGC 侧入口；用户旧包可在「转写」里选舞台）。

    只做定点文本替换，避免 ElementTree 重新序列化改动命名空间/缩进。
    """
    import re

    path = Path(music_dir) / "Music.xml"
    text = path.read_text(encoding="utf-8")
    block = re.search(r"[ \t]*<stageName>.*?</stageName>", text, re.S)
    if block is None:
        raise RuntimeError(f"Music.xml 缺少 <stageName>：{path}")
    safe = (
        (stage_str or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    new_block = (
        "  <stageName>\n"
        f"    <id>{int(stage_id)}</id>\n"
        f"    <str>{safe}</str>\n"
        "    <data></data>\n"
        "  </stageName>"
    )
    path.write_text(text[: block.start()] + new_block + text[block.end() :], encoding="utf-8")


def _verify_package(package_root: Path, music_id: int, *, expect_cue: bool) -> None:
    mid = int(music_id)
    music_dir = package_root / "music" / f"music{mid:04d}"
    missing: list[str] = []
    if not (music_dir / "Music.xml").is_file():
        missing.append("Music.xml")
    if not list(music_dir.glob("*.c2s")):
        missing.append("*.c2s")
    if not list(music_dir.glob("CHU_UI_Jacket_*.dds")):
        missing.append("CHU_UI_Jacket_*.dds")
    if expect_cue:
        cue_dir = package_root / "cueFile" / f"cueFile{mid:06d}"
        for name in ("CueFile.xml", f"music{mid:04d}.acb", f"music{mid:04d}.awb"):
            if not (cue_dir / name).is_file():
                missing.append(f"cueFile/{name}")
    if missing:
        raise RuntimeError("打包结果缺少文件：" + "、".join(missing))


# --------------------------------------------------------------------------- 写入 ACUS


def install_option_package_to_acus(
    acus_root: Path,
    result: BuildResult,
    *,
    log: LogFn = _noop,
    on_progress: ProgressFn | None = None,
    create_ultima_event: bool = True,
    ultima_event_id: int | None = None,
) -> None:
    """把打包结果落位到 ACUS：``music/music<id>/`` + ``cueFile/cueFile00<id>/``（+ MusicSort / ULT 事件）。"""
    from ..pjsk_acus_install import (
        append_music_sort,
        next_custom_event_id,
        write_ultima_unlock_event,
    )

    acus = Path(acus_root).resolve()
    mid = int(result.music_id)
    dest_music = acus / "music" / f"music{mid:04d}"
    dest_cue = acus / "cueFile" / f"cueFile{mid:06d}"
    if dest_music.exists():
        raise FileExistsError(f"已存在乐曲目录：{dest_music}")

    moved: list[str] = []
    dest_music.mkdir(parents=True, exist_ok=True)
    for src in sorted(result.music_dir.rglob("*")):
        if not src.is_file():
            continue
        dst = dest_music / src.relative_to(result.music_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        moved.append(dst.name)
    log(f"已写入 {dest_music.relative_to(acus)}（{len(moved)} 个文件）")
    if on_progress:
        on_progress("已写入谱面与 Music.xml…", 0.6)

    dest_cue.mkdir(parents=True, exist_ok=True)
    for src in sorted(result.cue_dir.rglob("*")):
        if not src.is_file():
            continue
        dst = dest_cue / src.relative_to(result.cue_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    log(f"已写入 {dest_cue.relative_to(acus)}")
    if on_progress:
        on_progress("已写入音频 ACB/AWB…", 0.8)

    append_music_sort(acus, mid)

    if result.has_ultima and create_ultima_event:
        eid = ultima_event_id if ultima_event_id is not None else next_custom_event_id(acus, start=70000)
        write_ultima_unlock_event(
            acus,
            event_id=int(eid),
            music_id=mid,
            music_title=_title_of(result) or str(mid),
        )
        log(f"已写入 ULT 解锁事件 event{int(eid):08d}")

    if on_progress:
        on_progress("完成", 1.0)


def _title_of(result: BuildResult) -> str:
    """从 Music.xml 读回曲名（PT 已写入最终值）。"""
    xml_path = result.music_dir / "Music.xml"
    try:
        root = ET.parse(xml_path).getroot()
        node = root.find("name/str")
        return (node.text or "").strip() if node is not None else ""
    except Exception:
        return ""


def cleanup_build_output(result: BuildResult) -> None:
    """删除 ``option build`` 的临时输出目录（打包结果已落位后调用）。"""
    shutil.rmtree(result.output_root, ignore_errors=True)


__all__ = [
    "SLOT_ORDER",
    "SLOT_UGC_DIFF",
    "SLOT_PT_MAIN_NAME",
    "GENRE_ID",
    "GENRE_NAME",
    "RELEASE_TAG_ID",
    "RELEASE_TAG_NAME",
    "PJSK_CHUNI_DOWNLOAD_ORDER",
    "PJSK_TO_CHUNI_SLOT",
    "chuni_slot_name_for_pjsk",
    "PJSK_LEVEL_RANGE",
    "CHUNI_CONST_RANGE",
    "pjsk_level_to_chuni_const",
    "const_to_level_pair",
    "SlotSource",
    "SlotResult",
    "BuildRequest",
    "BuildResult",
    "patch_ugc_header",
    "convert_sus_to_ugc",
    "prepare_48k_wav",
    "build_option_package",
    "normalize_package",
    "patch_music_xml_stage",
    "install_option_package_to_acus",
    "cleanup_build_output",
]
