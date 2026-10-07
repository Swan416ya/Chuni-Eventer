#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证应用内 pjsk→中二链路：与上游转换器等价 + 端到端打包落位。

用法（在仓库根目录）：
    python scripts/verify_pjsk2chuni_pipeline.py \
        --bundle pjsk_cache/pjsk_0224 \
        --music-id 7901 \
        --levels 4 8 12 14 15 \
        --reference "E:\\koishi Project\\Chunicharter\\pjsk2chuni\\pjsk2chuni.py" \
        --out build/_verify_pjsk2chuni

检查项：
  1. 每个槽位的 .ugc 谱面正文（@ENDHEAD 之后）与上游 ``pjsk2chuni.py`` 输出**逐字节一致**；
  2. PenguinTools ``option build`` 出整包，产物齐全（c2s / Music.xml / DDS / CueFile.xml / acb / awb）；
  3. 规范性：c2s 为 CRLF 且无 BOM、XML 无 BOM、Music.xml 的 genre/releaseTag/等级正确；
  4. 落位：把包写进临时 ACUS 副本，检查目录结构与 ULT 事件。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from chuni_eventer_desktop.pjsk2chuni import pipeline  # noqa: E402
from chuni_eventer_desktop.pjsk2chuni.core import measure_leading_silence  # noqa: E402

SLOTS = ("BASIC", "ADVANCED", "EXPERT", "MASTER", "ULTIMA")
_FAILURES: list[str] = []


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    _FAILURES.append(msg)
    print(f"  [FAIL] {msg}")


def check(cond: bool, msg: str) -> None:
    (ok if cond else fail)(msg)


def ugc_body(text: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "@ENDHEAD":
            return "\n".join(lines[i + 1 :])
    return "\n".join(lines)


def ugc_header_map(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.startswith("@") and "\t" in line:
            key, _, val = line.partition("\t")
            out.setdefault(key[1:].upper(), val)
        if line.strip() == "@ENDHEAD":
            break
    return out


def load_slots(bundle: Path) -> dict[str, pipeline.SlotSource]:
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    slots: dict[str, pipeline.SlotSource] = {}
    for s in manifest.get("slots") or []:
        slot = str(s.get("chuniSlot") or "").upper()
        rel = s.get("susFile")
        if slot and rel:
            slots[slot] = pipeline.SlotSource(slot=slot, sus_path=(bundle / rel).resolve())
    return slots


def run_reference(reference: Path, sus: Path, out_dir: Path, *, title: str, artist: str,
                  creator: str, songid: int, level: float) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(reference),
        str(sus),
        "-o",
        str(out_dir),
        "--formats",
        "ugc",
        "--title",
        title,
        "--artist",
        artist,
        "--creator",
        creator,
        "--songid",
        str(songid),
        "--level",
        f"{level:g}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"上游转换失败：{proc.stdout}\n{proc.stderr}")
    ugc = out_dir / (sus.stem + ".ugc")
    if not ugc.is_file():
        raise RuntimeError(f"上游未产出 {ugc}")
    return ugc.read_text(encoding="utf-8")


def _first_note_tick(c2s_path: Path) -> int | None:
    """c2s 里第一条判定/长条/装饰行的绝对 tick（bar*384 + tick）。"""
    import re

    note_words = ("TAP", "CHR", "HLD", "HXD", "SLD", "SLC", "SXD", "SXC", "HOLD")
    for line in c2s_path.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0] in note_words:
            try:
                return int(parts[1]) * 384 + int(parts[2])
            except ValueError:
                continue
    return None


def check_soffset_shift(work: Path, source, beat_m) -> None:
    """用 PenguinTools ``chart convert`` 对比 SOFFSET 开/关的谱面起点差值。"""
    from chuni_eventer_desktop import penguin_tools_cli as pt

    cli = pt.resolve_penguin_tools_cli()
    if cli is None:
        print("   （跳过 SOFFSET 位移校验：未找到 PenguinTools.CLI）")
        return
    ugc = work / f"{source.slot.lower()}.ugc"
    text = ugc.read_text(encoding="utf-8")
    off = work / "_soffset_off.ugc"
    off_text = text.replace("@FLAG\tSOFFSET\tTRUE", "@FLAG\tSOFFSET\tFALSE")
    if off_text == text:
        fail("SOFFSET 行未找到，无法校验位移")
        return
    off.write_text(off_text, encoding="utf-8")
    on_c2s = work / "_soffset_on.c2s"
    off_c2s = work / "_soffset_off.c2s"
    for src, dst in ((ugc, on_c2s), (off, off_c2s)):
        p = subprocess.run(
            [str(cli), "chart", "convert", str(src), str(dst), "--no-progress"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if not dst.is_file():
            fail(f"chart convert 失败（{src.name}）：{p.stdout[:200]} {p.stderr[:200]}")
            return
    a = _first_note_tick(on_c2s)
    b = _first_note_tick(off_c2s)
    if a is None or b is None or beat_m is None:
        fail("无法从 c2s 读取首个音符 tick")
        return
    num, den = int(beat_m.group(1)), int(beat_m.group(2))
    expect = int(round(384 * num / den))
    check(
        a - b == expect,
        f"SOFFSET 位移 = 一个小节：{a} - {b} = {a - b}（期望 {expect} = {num}/{den}）",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--music-id", type=int, required=True)
    ap.add_argument("--levels", nargs=5, type=float, default=[4.0, 8.0, 12.0, 14.0, 15.0],
                    help="BASIC ADVANCED EXPERT MASTER ULTIMA 定数")
    ap.add_argument("--reference", default=r"E:\koishi Project\Chunicharter\pjsk2chuni\pjsk2chuni.py")
    ap.add_argument("--out", default="build/_verify_pjsk2chuni")
    ap.add_argument("--title", default=None)
    ap.add_argument("--artist", default=None)
    ap.add_argument("--creator", default="chunieventer")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-install", action="store_true")
    args = ap.parse_args(argv)

    bundle = Path(args.bundle).resolve()
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    title = args.title or str(manifest.get("title") or f"pjsk_{args.music_id}")
    artist = args.artist or str(manifest.get("composer") or "PJSK")
    slots = load_slots(bundle)
    levels = {s: float(args.levels[i]) for i, s in enumerate(SLOTS)}
    print(f"bundle={bundle}\n曲名={title} / 曲师={artist}\n槽位={list(slots)}")

    out_root = Path(args.out).resolve()
    if out_root.exists():
        shutil.rmtree(out_root, ignore_errors=True)
    out_root.mkdir(parents=True, exist_ok=True)
    work = out_root / "work"

    audio_rel = (manifest.get("audio") or {}).get("file")
    if not audio_rel:
        print("manifest 无音频，无法测 @BGMOFS", file=sys.stderr)
        return 2
    audio_src = (bundle / str(audio_rel)).resolve()

    # ---- 1) 与上游逐字节等价 ----
    print("\n== 1) 与上游转换器等价（谱面正文逐字节比较）")
    ref_dir = out_root / "reference"
    wav = pipeline.prepare_48k_wav(audio_src, work / f"pjsk_{args.music_id:04d}_48k.wav")
    measured = measure_leading_silence(wav)
    _raw_filler = manifest.get("fillerSec")
    try:
        filler_sec: float | None = float(_raw_filler) if _raw_filler is not None else None
    except (TypeError, ValueError):
        filler_sec = None
    if filler_sec is None:
        trim = 0.0 if measured is None else float(measured)
        print(f"   缓存无 fillerSec → 退回实测 {trim:.4f}s（@BGMOFS=0 + SOFFSET）")
    else:
        trim = filler_sec
        extra = "" if measured is None else f"（实测 {measured:.3f}s，差 {measured - filler_sec:+.3f}s）"
        print(f"   元数据 fillerSec={filler_sec:.3f}s → 按元数据裁片头；@BGMOFS=0 + SOFFSET{extra}")
        check(True, f"清单带 fillerSec={filler_sec:.3f}s（权威延迟值）")
    if trim > 1e-4:
        trimmed = pipeline.prepare_48k_wav(
            audio_src, work / f"pjsk_{args.music_id:04d}_48k_trim{trim:.3f}.wav", trim_leading_sec=trim
        )
        import wave

        with wave.open(str(wav), "rb") as w:
            d_full = w.getnframes() / w.getframerate()
        with wave.open(str(trimmed), "rb") as w:
            d_trim = w.getnframes() / w.getframerate()
        check(abs((d_full - d_trim) - trim) < 0.05, f"裁切音频时长 {d_full - d_trim:.3f}s ≈ 前导静音 {trim:.3f}s")
    reference = Path(args.reference)
    for slot, source in slots.items():
        ours = work / f"{slot.lower()}.ugc"
        result = pipeline.convert_sus_to_ugc(
            source,
            ours,
            title=title,
            artist=artist,
            creator=args.creator,
            songid=args.music_id,
            level_const=levels[slot],
            jacket_name="jacket_0000.png",
            bgm_name=wav.name,
            bgm_offset_sec=0.0,
            preview=(0.0, 30.0),
            work_dir=work,
            is_main=(slot == ("ULTIMA" if "ULTIMA" in slots else max(slots))),
        )
        ours_text = ours.read_text(encoding="utf-8")
        if reference.is_file():
            ref_text = run_reference(reference, source.sus_path, ref_dir / slot, title=title,
                                     artist=artist, creator=args.creator, songid=args.music_id,
                                     level=levels[slot])
            check(ugc_body(ref_text) == ugc_body(ours_text), f"{slot}: 谱面正文与上游一致")
            if ugc_body(ref_text) != ugc_body(ours_text):
                a = ugc_body(ref_text).splitlines()
                b = ugc_body(ours_text).splitlines()
                for i in range(max(len(a), len(b))):
                    x = a[i] if i < len(a) else "<missing>"
                    y = b[i] if i < len(b) else "<missing>"
                    if x != y:
                        print(f"      first diff line {i}: ref={x!r} ours={y!r}")
                        break
        else:
            print(f"   （跳过上游比较：未找到 {reference}）")
        h = ugc_header_map(ours_text)
        check(h.get("DIFF") == str(pipeline.SLOT_UGC_DIFF[slot]), f"{slot}: @DIFF={h.get('DIFF')}")
        check(h.get("GENRE") == pipeline.GENRE_NAME, f"{slot}: @GENRE={h.get('GENRE')}")
        check(h.get("CONST") == f"{levels[slot]:.2f}", f"{slot}: @CONST={h.get('CONST')}")
        check(h.get("BGM") == wav.name, f"{slot}: @BGM={h.get('BGM')}")
        check(h.get("BGMOFS") == "0.00000", f"{slot}: @BGMOFS={h.get('BGMOFS')}")
        check("SOFFSET" in ours_text, f"{slot}: @FLAG SOFFSET 存在")
        check(result.counts.get("tap", 0) + result.counts.get("chr", 0) > 0, f"{slot}: 判定音符非空")
        check(
            ("main true" in h.get("CMT", "")) == (slot == ("ULTIMA" if "ULTIMA" in slots else max(slots))),
            f"{slot}: @CMT 主谱标记={h.get('CMT')!r}",
        )

    if args.skip_build:
        return _report()

    # ---- 2) 端到端 option build ----
    print("\n== 2) PenguinTools option build 端到端")
    req = pipeline.BuildRequest(
        bundle_root=bundle,
        slots=[pipeline.SlotSource(slot=s, sus_path=src.sus_path) for s, src in slots.items()],
        chuni_music_id=args.music_id,
        title=title,
        artist=artist,
        creator=args.creator,
        levels={s: levels[s] for s in slots},
        jacket_png=bundle / "封面.png",
        audio_src=audio_src,
        work_dir=work,
        filler_sec=filler_sec,
        stage_id=8,
        stage_str="レーベル 共通0008_新イエローリング",
    )
    try:
        result = pipeline.build_option_package(
            req, log=lambda m: print(f"   · {m}"), on_progress=lambda m, r: None
        )
    except Exception as e:  # noqa: BLE001
        fail(f"option build 失败：{e}")
        return _report()
    ok(f"package_root={result.package_root}")
    check(
        abs(result.trim_leading_sec - trim) < 1e-6,
        f"裁片头用的是 {'fillerSec 元数据' if filler_sec is not None else '实测值'}：{result.trim_leading_sec:.3f}s（{result.trim_source}）",
    )
    c2s = sorted(result.music_dir.glob("*.c2s"))
    check(len(c2s) >= 1, f"c2s 数量={len(c2s)}")
    for f in c2s:
        data = f.read_bytes()
        check(b"\r\n" in data and b"\r\r\n" not in data, f"{f.name}: CRLF")
        check(not data.startswith(b"\xef\xbb\xbf"), f"{f.name}: 无 BOM")
    for name in ("Music.xml", f"music{args.music_id:04d}.acb", f"music{args.music_id:04d}.awb", "CueFile.xml"):
        target = result.cue_dir / name if name.endswith((".acb", ".awb", "CueFile.xml")) else result.music_dir / name
        check(target.is_file(), f"{target.relative_to(result.package_root)} 存在")
    music_xml = (result.music_dir / "Music.xml").read_text(encoding="utf-8")
    check("<id>2</id>" in music_xml and "niconico" in music_xml, "Music.xml genre=2/niconico")
    check("<str>PJSK</str>" in music_xml and "<id>-2</id>" in music_xml, "Music.xml releaseTag=-2/PJSK")
    import xml.etree.ElementTree as ET

    tree = ET.parse(result.music_dir / "Music.xml")
    fumen_levels: dict[int, tuple[int, int]] = {}
    for fd in tree.getroot().findall("fumens/MusicFumenData"):
        type_id = int(fd.findtext("type/id") or "0")
        fumen_levels[type_id] = (int(fd.findtext("level") or "0"), int(fd.findtext("levelDecimal") or "0"))
    for slot in slots:
        idx = {"BASIC": 0, "ADVANCED": 1, "EXPERT": 2, "MASTER": 3, "ULTIMA": 4}[slot]
        const = levels[slot]
        want = (int(const), int(round((const - int(const)) * 100)))
        check(fumen_levels.get(idx) == want, f"Music.xml {slot} level={fumen_levels.get(idx)}（期望 {want}）")
        check((result.music_dir / f"{args.music_id:04d}_{idx:02d}.c2s").is_file(),
              f"{slot} → _{idx:02d}.c2s")
    check(not result.has_ultima or "<enableUltima>true</enableUltima>" in music_xml,
          "ULTIMA 存在时 enableUltima=true")
    cfg = json.loads((work / "options.json").read_text(encoding="utf-8"))
    check(cfg.get("optionName") == str(args.music_id), "options.json optionName 正确")
    check(cfg.get("chartFileDiscovery") == ["ugc"], "options.json chartFileDiscovery=[ugc]")
    check(cfg.get("hcaEncryptionKey") == 32931609366120192, "options.json hcaEncryptionKey 正确")
    check(cfg.get("customReleaseTagId") == -2 and cfg.get("customReleaseTagTitleName") == "PJSK",
          "options.json releaseTag=-2/PJSK")
    stage_node = tree.getroot().find("stageName")
    check(
        stage_node is not None
        and (stage_node.findtext("id") or "") == "8"
        and "レーベル" in (stage_node.findtext("str") or ""),
        "Music.xml stageName 打卡成功且 XML 仍可解析",
    )
    check((tree.getroot().findtext("sortName") or "") == title, "Music.xml sortName = 曲名")

    # 音频对齐：@BGMOFS 0 + SOFFSET ⇒ PT 真实偏移 = +1 小节；ACB 时长应 ≈ 裁切后音频 + 1 小节
    import re
    import wave

    ugc_sample = next(iter(slots.values()))
    ugc_text = (work / f"{ugc_sample.slot.lower()}.ugc").read_text(encoding="utf-8")
    bpm_m = re.search(r"^@BPM\t\d+'\d+\t([\d.]+)", ugc_text, re.M)
    beat_m = re.search(r"^@BEAT\t\d+\t(\d+)\t(\d+)", ugc_text, re.M)
    if bpm_m and beat_m:
        bar_offset = (60.0 / float(bpm_m.group(1))) * int(beat_m.group(1)) * (4 / int(beat_m.group(2)))
        with wave.open(str(result.audio_wav), "rb") as w:
            audio_len = w.getnframes() / w.getframerate()
        expected_ms = (audio_len + bar_offset) * 1000.0
        try:
            import gc

            from PyCriCodecsEx.acb import ACB

            acb = ACB(str(result.cue_dir / f"music{args.music_id:04d}.acb"))
            acb_ms = float(acb.view.CueTable[0].Length)
            del acb
            gc.collect()  # 释放文件句柄，否则清理临时目录会失败
            ok(f"@BGMOFS=0 + SOFFSET → 小节偏移 {bar_offset:.4f}s；ACB 时长 {acb_ms / 1000:.3f}s"
               f"（期望 ≈{expected_ms / 1000:.3f}s）")
            check(abs(acb_ms - expected_ms) < 250, "ACB 时长 ≈ 裁切后音频 + 1 小节（音频对齐）")
        except ImportError:
            print("   （跳过 ACB 时长校验：未安装 PyCriCodecsEx）")
    # SOFFSET 应把谱面整体后移「一个小节」（与音频 adelay 的一小节对应）
    check_soffset_shift(work, ugc_sample, beat_m)
    if result.warnings:
        print("   警告：")
        for w in result.warnings[:10]:
            print(f"     - {w}")

    # ---- 3) 落位到临时 ACUS ----
    if args.skip_install:
        pipeline.cleanup_build_output(result)
        return _report()
    print("\n== 3) 写入临时 ACUS 副本")
    fake_acus = out_root / "ACUS"
    (fake_acus / "music").mkdir(parents=True, exist_ok=True)
    (fake_acus / "event").mkdir(parents=True, exist_ok=True)
    try:
        pipeline.install_option_package_to_acus(
            fake_acus, result, log=lambda m: print(f"   · {m}"), on_progress=lambda m, r: None
        )
        ok("install 未抛异常")
    except Exception as e:  # noqa: BLE001
        fail(f"install 失败：{e}")
    dest = fake_acus / "music" / f"music{args.music_id:04d}"
    check(dest.is_dir(), f"{dest.relative_to(fake_acus)} 存在")
    check((dest / "Music.xml").is_file(), "Music.xml 落位")
    check(any(dest.glob("CHU_UI_Jacket_*.dds")), "封面 DDS 落位")
    cue = fake_acus / "cueFile" / f"cueFile{args.music_id:06d}"
    check((cue / f"music{args.music_id:04d}.acb").is_file(), "acb 落位")
    check((cue / f"music{args.music_id:04d}.awb").is_file(), "awb 落位")
    if result.has_ultima:
        events = sorted((fake_acus / "event").glob("event*"))
        check(bool(events), f"ULT 事件已写入（{len(events)}）")
    pipeline.cleanup_build_output(result)
    check(not result.output_root.exists(), "临时输出目录已清理")
    return _report()


def _report() -> int:
    print("\n== 结论")
    if _FAILURES:
        print(f"失败 {len(_FAILURES)} 项：")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("全部检查通过。")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
