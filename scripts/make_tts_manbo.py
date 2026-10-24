#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""曼波配音（MiloraAPI mbAIsc）TTS 管线：配音 + 响度归一化 + WebVTT + timeline。

只依赖标准库 + ffmpeg/ffprobe，不要装第三方包。

用法（在仓库根目录执行）::

    python scripts/make_tts_manbo.py --dry-run          # 只切段、统计字数，不调接口
    python scripts/make_tts_manbo.py                    # 生成全部缺失片段
    python scripts/make_tts_manbo.py --only s01         # 只做 s01（可逗号分隔多个）
    python scripts/make_tts_manbo.py --manifest x.json --out-dir y/vo   # 换输入输出

输入 manifest（默认 docs/Introduction/v0.8.3/vo_script.json）::

    [{"id": "s01", "text": "大家好，这是 v0.8.3 的更新介绍。"}, ...]

产物（默认输出根 docs/Introduction/v0.8.3/film/assets/vo）::

    {id}.mp3                 原始 TTS（多段自动拼接成一条）
    norm/{id}.mp3            -16 LUFS / 48kHz / 立体声 mp3
    {id}.vtt                 WebVTT，按句切 cue，句内按字数比例分配时间
    timeline.json            每段时长 + 累计起点，供 OpenFilm/film.html 用
    .parts/{id}/spNN.mp3     分段缓存（额度保险：存在就不再请求接口）
    .quota.json              当日接口调用计数
    tts_run.log              本次运行日志（UTF-8）

接口（实测）::

    GET https://api.milorapart.top/apis/mbAIsc?text=<urlencode>&format=mp3&speed=0
    -> {"code":200,"msg":"生成完成!","url":"https://media.milorapart.top/voice/<hash>.mp3"}
    再下载 url 得到 mp3。单段文本 <=200 字（这里默认 <=170），每 IP 每天 50 次。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

# ---------------------------------------------------------------- 常量

API_URL = "https://api.milorapart.top/apis/mbAIsc"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_MANIFEST = Path("docs/Introduction/v0.8.3/vo_script.json")
DEFAULT_OUT_DIR = Path("docs/Introduction/v0.8.3/film/assets/vo")
DEFAULT_MAX_CHARS = 170      # 单次请求的分段目标上限
HARD_MAX_CHARS = 200         # 接口硬上限，绝不能超过
TARGET_LUFS = -16.0
TRUE_PEAK = -1.5
OUT_SAMPLE_RATE = 48000
OUT_CHANNELS = 2
OUT_BITRATE = "192k"
MAX_ATTEMPTS = 12
BACKOFF = [2, 4, 8, 16, 30, 45, 45]   # 第 n 次失败后等多久，合计 7 次重试
DAILY_LIMIT = 50

SENTENCE_END = "。！？!?；;…"


# ---------------------------------------------------------------- 日志

class Log:
    def __init__(self, path: Path | None):
        self.path = path
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = msg
        print(line, flush=True)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")


# ---------------------------------------------------------------- 文本切分

def _char_count(text: str) -> int:
    """用于时间分配的字数：忽略空白。"""
    return len(re.sub(r"\s+", "", text))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    """按句末标点切成句子，保留标点。空串返回 []。"""
    text = normalize_text(text)
    if not text:
        return []
    pattern = rf"[^{re.escape(SENTENCE_END)}]*[{re.escape(SENTENCE_END)}]+|[^{re.escape(SENTENCE_END)}]+$"
    parts = [p.strip() for p in re.findall(pattern, text)]
    return [p for p in parts if p]


def _hard_split(text: str, max_chars: int) -> list[str]:
    out, cur = [], ""
    for ch in text:
        cur += ch
        if _char_count(cur) >= max_chars:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    """单句超长时先按逗号/顿号/冒号切，仍超长再硬切。"""
    if _char_count(sentence) <= max_chars:
        return [sentence]
    pieces = re.findall(r"[^，,、：:]*[，,、：:]+|[^，,、：:]+$", sentence)
    out, cur = [], ""
    for piece in pieces:
        if _char_count(piece) > max_chars:
            if cur:
                out.append(cur)
                cur = ""
            out.extend(_hard_split(piece, max_chars))
        elif _char_count(cur) + _char_count(piece) <= max_chars:
            cur += piece
        else:
            if cur:
                out.append(cur)
            cur = piece
    if cur:
        out.append(cur)
    return out


def split_for_tts(sentences: list[str], max_chars: int) -> list[str]:
    """把句子贪心打包成 <= max_chars 的请求段。"""
    chunks, cur = [], ""
    for sentence in sentences:
        for piece in _split_long_sentence(sentence, max_chars):
            if not cur:
                cur = piece
            elif _char_count(cur) + _char_count(piece) <= max_chars:
                cur += piece
            else:
                chunks.append(cur)
                cur = piece
    if cur:
        chunks.append(cur)
    return chunks


# ---------------------------------------------------------------- ffmpeg

def run_ffmpeg(args: list[str], timeout: int = 300):
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout,
    )


def probe_duration(path: Path) -> float:
    p = run_ffmpeg([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(path),
    ], timeout=120)
    if p.returncode != 0:
        return 0.0
    try:
        return float(json.loads(p.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0.0


def measure_loudness(path: Path) -> dict | None:
    """用 loudnorm 的分析模式量 integrated loudness / true peak 等。"""
    p = run_ffmpeg([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA=11:print_format=json",
        "-f", "null", "-",
    ])
    blocks = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", p.stderr, re.S)
    if not blocks:
        return None
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError:
        return None


def concat_parts(parts: list[Path], dst: Path) -> bool:
    """把多段 mp3 拼成一条；先尝试无损 copy，失败再重编码。"""
    if len(parts) == 1:
        dst.write_bytes(parts[0].read_bytes())
        return True
    list_file = dst.with_suffix(".concat.txt")
    list_file.write_text(
        "".join("file '" + str(p.resolve()).replace("\\", "/").replace("'", "'\\''") + "'\n"
                for p in parts),
        encoding="utf-8",
    )
    try:
        p = run_ffmpeg([
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c:a", "copy", str(dst),
        ])
        if p.returncode == 0 and probe_duration(dst) > 0:
            return True
        p = run_ffmpeg([
            "ffmpeg", "-y", "-hide_banner", "-nostats", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c:a", "libmp3lame", "-q:a", "2", str(dst),
        ])
        return p.returncode == 0 and probe_duration(dst) > 0
    finally:
        list_file.unlink(missing_ok=True)


def _encode_norm(src: Path, dst: Path, gain_db: float, use_limiter: bool) -> bool:
    """按给定增益（必要时加真峰限制器）编码 48kHz 立体声 mp3。"""
    filters = [f"volume={gain_db:.2f}dB"]
    if use_limiter:
        filters.append(f"alimiter=limit={10 ** (TRUE_PEAK / 20):.4f}:level=false")
    p = run_ffmpeg([
        "ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(src),
        "-af", ",".join(filters),
        "-ar", str(OUT_SAMPLE_RATE), "-ac", str(OUT_CHANNELS),
        "-c:a", "libmp3lame", "-b:a", OUT_BITRATE, str(dst),
    ])
    return p.returncode == 0 and probe_duration(dst) > 0


def normalize_loudness(src: Path, dst: Path, measured: dict, log: Log) -> dict | None:
    """响度归一化到 TARGET_LUFS / TP TRUE_PEAK：增益 + 真峰限制，带一次校正迭代。

    曼波原始约 -18~-20 LUFS，直接加增益会顶到 0 dBFS，所以超峰时挂 alimiter；
    限制后积分响度会掉一点，再按实测误差校正一次。
    """
    base_i = float(measured["input_i"])
    base_tp = float(measured["input_tp"])
    if base_i <= -70:
        log("    ! 原始音频接近静音，跳过响度归一化")
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp" + dst.suffix)
    gain = TARGET_LUFS - base_i
    best_err, best_gain = None, gain
    try:
        for attempt in range(1, 4):
            use_limiter = base_tp + gain > TRUE_PEAK - 0.05
            if not _encode_norm(src, tmp, gain, use_limiter):
                log("    ! loudnorm 编码失败")
                return None
            m = measure_loudness(tmp)
            if not m:
                log("    ! 归一化后无法测量响度")
                return None
            err = float(m["input_i"]) - TARGET_LUFS
            log(f"    响度第 {attempt} 遍：gain={gain:+.2f}dB "
                f"limiter={'on' if use_limiter else 'off'} -> "
                f"I={m['input_i']} LUFS  TP={m['input_tp']} dBTP")
            if best_err is None or abs(err) < best_err:
                best_err, best_gain = abs(err), gain
            if abs(err) <= 0.25:
                break
            gain -= err
        final_limiter = base_tp + best_gain > TRUE_PEAK - 0.05
        if not _encode_norm(src, tmp, best_gain, final_limiter):
            return None
        os.replace(tmp, dst)
        return measure_loudness(dst)
    finally:
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- HTTP / 接口

class QuotaExhausted(RuntimeError):
    pass


def _http_get(url: str, timeout: int = 90) -> tuple[int, bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json, audio/mpeg, */*",
            "Referer": "https://api.milorapart.top/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(), resp.headers.get("Content-Type", "")


def tts_request(text: str, speed: int) -> tuple[dict, int]:
    """调一次生成接口，返回 (json, http_status)。"""
    url = f"{API_URL}?text={urllib.parse.quote(text, safe='')}&format=mp3&speed={speed}"
    status, body, _ctype = _http_get(url)
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        raise RuntimeError(f"返回不是 JSON（HTTP {status}）：{body[:200]!r}")
    return data, status


def _range_get(url: str, start: int, end: int, timeout: int = 60) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://api.milorapart.top/",
            "Range": f"bytes={start}-{end}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read(), dict(resp.headers)


CHUNK = 32 * 1024


def download_mp3(url: str, dst: Path) -> None:
    """分块 Range 下载直链音频。

    media.milorapart.top 会把长连接在中途直接 reset（IncompleteRead / curl 56），
    但支持 HTTP Range（206），所以按 32KB 分块拿、每块单独重试，稳定且不浪费 TTS 额度。
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp" + dst.suffix)
    tmp.unlink(missing_ok=True)

    body = bytearray()
    total: int | None = None
    while total is None or len(body) < total:
        start = len(body)
        end = start + CHUNK - 1
        if total is not None:
            end = min(end, total - 1)
        last = ""
        for attempt in range(1, 9):
            try:
                status, chunk, headers = _range_get(url, start, end)
                if status not in (200, 206):
                    raise RuntimeError(f"HTTP {status}")
                if total is None:
                    cr = headers.get("Content-Range", "")
                    if "/" in cr:
                        total = int(cr.rsplit("/", 1)[1])
                body.extend(chunk)
                break
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(min(1.5 * attempt, 6))
        else:
            raise RuntimeError(f"分块下载失败（{start}-{end}）：{last}")

    if len(body) < 1024:
        raise RuntimeError(f"下载体积异常：{len(body)} bytes")
    tmp.write_bytes(bytes(body))
    if probe_duration(tmp) <= 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("下载的 mp3 无法解析时长")
    os.replace(tmp, dst)


# ---------------------------------------------------------------- 配额账本

def load_quota(quota_path: Path) -> dict:
    today = date.today().isoformat()
    data: dict = {}
    if quota_path.exists():
        try:
            data = json.loads(quota_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if data.get("date") != today:
        data = {"date": today, "api_calls": 0, "daily_limit": DAILY_LIMIT,
                "note": "仅统计本脚本调用；同 IP 其他用量不计入"}
        save_quota(quota_path, data)
    data.setdefault("daily_limit", DAILY_LIMIT)
    data.setdefault("api_calls", 0)
    return data


def save_quota(quota_path: Path, data: dict) -> None:
    quota_path.parent.mkdir(parents=True, exist_ok=True)
    quota_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 生成单段

def generate_part(text: str, dst: Path, speed: int, log: Log) -> tuple[dict, dict]:
    """带重试地生成并下载一段。返回 (json, 元信息)。额度耗尽会抛 QuotaExhausted。

    media.milorapart.top 经常传到一半断连，所以拿到直链后**复用直链重试下载**，
    只有直链本身失效（连续多次失败）才重新调生成接口，避免白白消耗每日额度。
    """
    last_err = "未知错误"
    url = ""
    data: dict = {}
    status = 0
    attempts = 0
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        try:
            if not url or attempts > 1 and attempts % 5 == 0:
                data, status = tts_request(text, speed)
                if data.get("code") != 200 or not data.get("url"):
                    msg = str(data.get("msg", ""))
                    if any(k in msg for k in ("上限", "今日", "次数", "频繁", "限制")) or data.get("code") == 429:
                        raise QuotaExhausted(f"接口返回额度/频率限制：{msg}")
                    raise RuntimeError(f"HTTP {status} 返回异常：{msg or data}")
                url = str(data["url"])
                log(f"    HTTP {status}  code={data.get('code')}  msg={data.get('msg')}  url={url}")
            download_mp3(url, dst)
            return data, {"attempts": attempts, "http_status": status}
        except QuotaExhausted:
            raise
        except urllib.error.HTTPError as exc:
            last_err = f"HTTPError {exc.code} {exc.reason}"
            url = ""  # 直链失效，下一轮重新生成
            if exc.code in (429, 403):
                raise QuotaExhausted(f"接口拒绝（HTTP {exc.code}），可能额度用尽") from exc
        except Exception as exc:  # noqa: BLE001 - 网络断连/超时/解析失败都要重试
            last_err = f"{type(exc).__name__}: {exc}"
        log(f"    ! 第 {attempts}/{MAX_ATTEMPTS} 次失败：{last_err}")
        if attempts < MAX_ATTEMPTS:
            wait = BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
            log(f"    ... {wait}s 后重试下载")
            time.sleep(wait)
    raise RuntimeError(f"重试 {MAX_ATTEMPTS} 次仍失败：{last_err}")


# ---------------------------------------------------------------- VTT

def format_vtt_ts(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def write_vtt(dst: Path, sentences: list[str], duration: float) -> None:
    """按句切 cue；句内按字数比例分配整段时长（无词级时间戳）。"""
    cues = [s for s in sentences if normalize_text(s)]
    weights = [max(1, _char_count(s)) for s in cues]
    total_w = sum(weights) or 1
    lines = ["WEBVTT", ""]
    t = 0.0
    for idx, (sentence, weight) in enumerate(zip(cues, weights)):
        span = duration * weight / total_w
        start, end = t, t + span
        t = end
        lines.append(str(idx + 1))
        lines.append(f"{format_vtt_ts(start)} --> {format_vtt_ts(end)}")
        lines.append(normalize_text(sentence))
        lines.append("")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 主流程

def load_manifest(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SystemExit(f"manifest 顶层必须是数组：{path}")
    entries = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise SystemExit(f"manifest 第 {i} 项不是对象")
        eid = str(item.get("id", "")).strip()
        text = str(item.get("text", ""))
        if not eid or not re.fullmatch(r"[A-Za-z0-9_.-]+", eid):
            raise SystemExit(f"manifest 第 {i} 项 id 非法：{eid!r}（只允许字母数字 _ . -）")
        if eid in seen:
            raise SystemExit(f"manifest 出现重复 id：{eid}")
        seen.add(eid)
        if not normalize_text(text):
            raise SystemExit(f"manifest {eid} 文本为空")
        entries.append({
            "id": eid,
            "text": text,
            "sub": str(item.get("sub", "")),   # 字幕用；缺省时回落到 text
        })
    return entries


def plan_entry(entry: dict, out_dir: Path, max_chars: int) -> dict:
    # TTS 念 text；字幕优先用 sub（TTS 念不顺的公式/箭头可以只出现在字幕里）
    sentences = split_sentences(entry["text"])
    sub_sentences = split_sentences(entry["sub"]) if normalize_text(entry.get("sub", "")) else list(sentences)
    chunks = split_for_tts(sentences, max_chars)
    part_dir = out_dir / ".parts" / entry["id"]
    parts = [{
        "index": i + 1,
        "name": f"sp{i + 1:02d}",
        "text": chunk,
        "chars": _char_count(chunk),
        "path": part_dir / f"sp{i + 1:02d}.mp3",
    } for i, chunk in enumerate(chunks)]
    return {
        "id": entry["id"],
        "text": entry["text"],
        "sub": entry.get("sub", "") or entry["text"],
        "sentences": sentences,
        "sub_sentences": sub_sentences,
        "parts": parts,
        "raw": out_dir / f"{entry['id']}.mp3",
        "norm": out_dir / "norm" / f"{entry['id']}.mp3",
        "vtt": out_dir / f"{entry['id']}.vtt",
    }


def build_timeline(plans: list[dict]) -> dict:
    entries, start = [], 0.0
    pending = []
    for plan in plans:
        if not plan.get("duration"):
            pending.append(plan["id"])
            continue
        entries.append({
            "id": plan["id"],
            "duration": round(plan["duration"], 3),
            "start": round(start, 3),
            "chars": sum(p["chars"] for p in plan["parts"]),
            "raw": plan["raw_rel"],
            "norm": plan["norm_rel"],
            "vtt": plan["vtt_rel"],
            "text": normalize_text(plan["text"]),
            "sub": normalize_text(plan["sub"]),
            "sentences": plan["sub_sentences"],
            "tts_sentences": plan["sentences"],
            "parts": plan["parts_meta"],
            "loudness": plan.get("loudness"),
        })
        start += plan["duration"]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "voice": "manbo (milorapart mbAIsc)",
        "target_lufs": TARGET_LUFS,
        "sample_rate": OUT_SAMPLE_RATE,
        "channels": OUT_CHANNELS,
        "max_chars_per_request": max_chars_global,
        "total_duration": round(start, 3),
        "entries": entries,
        "pending_ids": pending,
    }


def main(argv: list[str] | None = None) -> int:
    global max_chars_global
    ap = argparse.ArgumentParser(
        description="曼波配音 TTS 管线（MiloraAPI mbAIsc）：配音 + -16 LUFS 归一化 + VTT + timeline")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                    help=f"manifest 路径（默认 {DEFAULT_MANIFEST}）")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                    help=f"输出根目录（默认 {DEFAULT_OUT_DIR}）")
    ap.add_argument("--only", default=None,
                    help="只处理指定 id（逗号分隔），调试用")
    ap.add_argument("--dry-run", action="store_true",
                    help="只切段 + 统计字数/计划调用数，不请求接口")
    ap.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS,
                    help=f"单次请求分段上限，<=200（默认 {DEFAULT_MAX_CHARS}）")
    ap.add_argument("--speed", type=int, default=0, help="接口 speed 参数（-50~50，默认 0）")
    ap.add_argument("--max-calls", type=int, default=34,
                    help="本次运行最多发多少次接口请求（额度保护，默认 34）")
    ap.add_argument("--force-norm", action="store_true", help="即使 norm 文件已存在也重新归一化")
    ap.add_argument("--no-vtt", action="store_true", help="不生成 VTT")
    args = ap.parse_args(argv)

    if args.max_chars > HARD_MAX_CHARS:
        raise SystemExit(f"--max-chars 不能超过接口硬上限 {HARD_MAX_CHARS}")
    max_chars_global = args.max_chars

    manifest = args.manifest
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    log = Log(out_dir / "tts_run.log")
    quota_path = out_dir / ".quota.json"
    quota = load_quota(quota_path)

    log("=" * 78)
    log(f"[{datetime.now().isoformat(timespec='seconds')}] 曼波配音管线  "
        f"manifest={manifest}  out={out_dir}")
    log(f"今日账本 {quota_path.name}: {quota['api_calls']}/{quota['daily_limit']} 次，"
        f"本次预算 --max-calls={args.max_calls}")

    if not manifest.exists():
        log(f"! manifest 不存在：{manifest}")
        log("  先放好 vo_script.json 再跑；或 --dry-run 不读文件时也需要它。")
        return 2

    entries = load_manifest(manifest)
    selected = entries
    if args.only:
        wanted = [s.strip() for s in args.only.split(",") if s.strip()]
        unknown = [w for w in wanted if w not in {e["id"] for e in entries}]
        if unknown:
            log(f"! --only 里有 manifest 不存在的 id：{unknown}")
        selected = [e for e in entries if e["id"] in wanted]
        if not selected:
            raise SystemExit("--only 没有匹配到任何条目")

    plans = [plan_entry(e, out_dir, args.max_chars) for e in selected]

    # ---- dry-run：只报告切段与计划
    if args.dry_run:
        total_chars = 0
        planned_calls = 0
        log("")
        for plan in plans:
            raw_exists = plan["raw"].exists() and probe_duration(plan["raw"]) > 0
            missing = [p for p in plan["parts"]
                       if not (p["path"].exists() and probe_duration(p["path"]) > 0)]
            n_calls = 0 if raw_exists else len(missing)
            planned_calls += n_calls
            total_chars += sum(p["chars"] for p in plan["parts"])
            log(f"  {plan['id']:<6} TTS{_char_count(plan['text']):>3}字 -> "
                f"{len(plan['parts'])} 段 {[p['chars'] for p in plan['parts']]}  "
                f"raw={'已存在(跳过)' if raw_exists else '待生成'}  需调用 {n_calls}"
                f"  | 字幕{_char_count(plan['sub'])}字/{len(plan['sub_sentences'])}cue")
            if not raw_exists and any(p["chars"] > HARD_MAX_CHARS for p in plan["parts"]):
                log("    ! 有分段超过 200 字，接口会拒绝")
        log("")
        log(f"合计 {len(plans)} 条 / {total_chars} 字 / 计划接口调用 {planned_calls} 次"
            f"（今日已用 {quota['api_calls']}，预算内剩余约 {args.max_calls}）")
        return 0

    calls_this_run = 0
    soft_failures: list[str] = []
    for plan in plans:
        eid = plan["id"]
        raw, norm = plan["raw"], plan["norm"]
        raw_dur = probe_duration(raw) if raw.exists() else 0.0
        log("")
        if raw_dur > 0:
            log(f"[{eid}] 原始配音已存在（{raw_dur:.2f}s），跳过接口调用")
        else:
            log(f"[{eid}] 生成 {len(plan['parts'])} 段："
                f"{[p['chars'] for p in plan['parts']]}")
            for part in plan["parts"]:
                if part["path"].exists() and probe_duration(part["path"]) > 0:
                    log(f"  {part['name']} 已存在，跳过")
                    continue
                if calls_this_run >= args.max_calls:
                    log(f"! 已达本次 --max-calls={args.max_calls} 上限，停止")
                    soft_failures.append(eid)
                    break
                if quota["api_calls"] >= quota["daily_limit"]:
                    log(f"! 今日账本已达 {quota['daily_limit']} 次上限，停止（可用 --max-calls 调整保护阈值）")
                    soft_failures.append(eid)
                    break
                log(f"  {part['name']}（{part['chars']}字）请求中 ...")
                try:
                    _json, meta = generate_part(part["text"], part["path"], args.speed, log)
                    calls_this_run += 1
                    quota["api_calls"] += 1
                    save_quota(quota_path, quota)
                    part["attempts"] = meta["attempts"]
                    log(f"  {part['name']} OK  {probe_duration(part['path']):.2f}s  "
                        f"（第 {meta['attempts']} 次请求成功，今日累计 {quota['api_calls']} 次）")
                except QuotaExhausted as exc:
                    log(f"  ! 额度/频率限制，中止：{exc}")
                    soft_failures.append(eid)
                    break
                except Exception as exc:  # noqa: BLE001
                    log(f"  ! {part['name']} 生成失败：{exc}")
                    soft_failures.append(eid)
                    break
            parts_ok = all(p["path"].exists() and probe_duration(p["path"]) > 0
                           for p in plan["parts"])
            if not parts_ok:
                plan["duration"] = 0.0
                log(f"[{eid}] 分段不全，本轮跳过拼接/归一化/字幕")
                continue
            log(f"[{eid}] 拼接 {len(plan['parts'])} 段 -> {raw.name}")
            if not concat_parts([p["path"] for p in plan["parts"]], raw):
                log(f"  ! 拼接失败：{raw}")
                plan["duration"] = 0.0
                continue
            raw_dur = probe_duration(raw)

        plan["duration"] = raw_dur
        plan["parts_meta"] = [{
            "name": p["name"], "chars": p["chars"], "duration": round(probe_duration(p["path"]), 3),
            "text": normalize_text(p["text"]),
        } for p in plan["parts"]]

        # ---- 响度归一化
        loud_raw = measure_loudness(raw)
        norm_ok = norm.exists() and probe_duration(norm) > 0
        if norm_ok and not args.force_norm and norm.stat().st_mtime >= raw.stat().st_mtime:
            log(f"[{eid}] 归一化音频已存在且不比原始旧，跳过")
            loud_norm = measure_loudness(norm)
        else:
            if loud_raw:
                log(f"[{eid}] 原始响度 I={loud_raw['input_i']} LUFS  TP={loud_raw['input_tp']} dBTP"
                    f" -> 归一化到 {TARGET_LUFS} LUFS / {OUT_SAMPLE_RATE}Hz / stereo")
            loud_norm = normalize_loudness(raw, norm, loud_raw, log) if loud_raw else None
            if loud_norm:
                log(f"[{eid}] 归一化后 I={loud_norm['input_i']} LUFS  TP={loud_norm['input_tp']} dBTP"
                    f"  LRA={loud_norm['input_lra']}")
            else:
                log(f"  ! {eid} 归一化失败")
        plan["loudness"] = {
            "raw_lufs": float(loud_raw["input_i"]) if loud_raw else None,
            "norm_lufs": float(loud_norm["input_i"]) if loud_norm else None,
        }

        # ---- 字幕（用 sub，TTS 念的 text 只在没有 sub 时才上字幕）
        if not args.no_vtt:
            write_vtt(plan["vtt"], plan["sub_sentences"], raw_dur)
            log(f"[{eid}] VTT -> {plan['vtt'].name}  {len(plan['sub_sentences'])} cue / {raw_dur:.2f}s")

    # ---- timeline（含已存在的旧条目时也完整重算）
    for plan in plans:
        plan["raw_rel"] = os.path.relpath(plan["raw"], out_dir.parent).replace("\\", "/")
        plan["norm_rel"] = os.path.relpath(plan["norm"], out_dir.parent).replace("\\", "/")
        plan["vtt_rel"] = os.path.relpath(plan["vtt"], out_dir.parent).replace("\\", "/")
        plan.setdefault("parts_meta", [])
        plan.setdefault("loudness", None)
    # 未选中的条目如果已有成品也要算进时间轴
    chosen = {p["id"] for p in plans}
    for entry in entries:
        if entry["id"] in chosen:
            continue
        plan = plan_entry(entry, out_dir, args.max_chars)
        dur = probe_duration(plan["raw"]) if plan["raw"].exists() else 0.0
        if dur > 0:
            plan["duration"] = dur
            plan["raw_rel"] = os.path.relpath(plan["raw"], out_dir.parent).replace("\\", "/")
            plan["norm_rel"] = os.path.relpath(plan["norm"], out_dir.parent).replace("\\", "/")
            plan["vtt_rel"] = os.path.relpath(plan["vtt"], out_dir.parent).replace("\\", "/")
            plan["parts_meta"] = []
            plan["loudness"] = None
            plans.append(plan)
    plans.sort(key=lambda p: next(i for i, e in enumerate(entries) if e["id"] == p["id"]))

    timeline = build_timeline(plans)
    timeline_path = out_dir / "timeline.json"
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    log("")
    log(f"timeline -> {timeline_path}  （{len(timeline['entries'])} 条，"
        f"总时长 {timeline['total_duration']:.2f}s）")
    if timeline["pending_ids"]:
        log(f"! 尚未完成的 id：{timeline['pending_ids']}")
    if calls_this_run:
        log(f"本次接口调用 {calls_this_run} 次；今日账本 {quota['api_calls']}/{quota['daily_limit']}")
    else:
        log("本次未调用接口（全部命中已有文件）")
    if soft_failures:
        log(f"! 有失败/中止：{sorted(set(soft_failures))}")
        return 1
    return 0


max_chars_global = DEFAULT_MAX_CHARS

if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
