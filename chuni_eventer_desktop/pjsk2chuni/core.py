#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ---------------------------------------------------------------------------
# VENDORED：上游转换器原样收录，请勿就地改写转谱逻辑；如需同步请改上游后整体复制。
# 上游：E:\koishi Project\Chunicharter\pjsk2chuni\pjsk2chuni.py
#   （同目录 docs/01..08 为规格与裁定依据；本文件注释里 research/* 属上游仓库）
# SHA256：BF2F654833E6AD9C0D36B533AA3540FA0D6CA72157C614100937DB47FEFBB635
# 同步日期：2026-10-07
# 产品侧接线（元数据打补丁 / PenguinTools option build / 写入 ACUS）在
#   chuni_eventer_desktop/pjsk2chuni/pipeline.py，不在本文件内。
# ---------------------------------------------------------------------------
"""
pjsk2chuni —— Project SEKAI 官谱 .sus → CHUNITHM .c2s / .ugc(v8) 转换器

规格依据：
  research/08-pjsk-curve-slides.md §3/§4     编码语义、曲线烘焙、lane ×4/3 映射、时间换算
  research/11-pjsk-marker-notes.md §0.1/§4.1 标记音符处理表、ALD(AIR-CRUSH IV=0) 装饰线
  游戏侧类型语义：research/repos/sekai-sus-parser/（il2cpp hasJudgment）

标记音符处理（11 报告 2026-10-06 裁定版）：
  ch5 2/5/6 缓动锚        → 曲线烘焙输入（无损失）
  ch5 1/3/4 flick 标记    → AIR/AUL/AUR 挂同位音符或丝带（用户裁定 flick→AIR）
  ch1 t3 Skip             → SLD 可见中继（曲线穿过，不作段边界）
  ch1 t5/t6 Friction      → 独立=TAP/CHR；在链顶点上=ALD 绿色装饰线
  ch1 t7/t8 FrictionHide  → 链续接标记（合并相接链），不产出
  ch9 Guide               → ALD 绿色装饰线（隐形段跳过）
  ch1 t4 / lane≥14 t1/t2  → skill/fever 事件，删除
  链头 tap/critical       → 并入丝带头（critical → Ex 丝带 SXD/SXC、Ex-HOLD HXD）

用法：
  python tools/pjsk2chuni.py <file.sus|dir>... [-o OUTDIR] [--formats c2s,ugc]
      [--decorations all|guides|off] [--no-merge] [--crush-h 1.0]
      [--title T] [--artist A] [--level L] [--creator C] [--songid ID]
"""
import argparse
import bisect
import math
import re
import sys
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

RES = 384                    # C2S ticks / measure（恒定）
UGB = 480                    # UGC ticks / beat（@TICKS）
FIELD_LO, FIELD_HI = 2, 13   # pjsk 可演奏区 raw lane

NOTE_RE = re.compile(r"^#(\d{3})([1-9])([0-9a-fA-F])([0-9a-zA-Z]?):\s*(.*)$")
METER_RE = re.compile(r"^#(\d{3})02:\s*(\S+)")
BPMCH_RE = re.compile(r"^#(\d{3})08:\s*(.*)$")
BPMDEF_RE = re.compile(r"^#BPM([0-9a-zA-Z]{2}):\s*(\S+)")

C2S_DIFF = {"easy": "00", "normal": "01", "hard": "02",
            "expert": "03", "master": "03", "append": "04"}
UGC_DIFF = {"easy": "0", "normal": "1", "hard": "2",
            "expert": "3", "master": "3", "append": "5"}


def b36(c):
    return int(c, 36)

def x36(n):
    return "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[n]

def rhu(x):
    """round half up（Fraction/float → int）"""
    if isinstance(x, Fraction):
        return (2 * x.numerator + x.denominator) // (2 * x.denominator)
    return int(math.floor(x + 0.5))

def inv_mono(f, y, lo=0.0, hi=1.0, iters=60):
    """f 在 [lo,hi] 单调递增，求 f(u)=y"""
    for _ in range(iters):
        mid = (lo + hi) / 2
        if f(mid) < y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2

def smoothstep(u):
    return u * u * (3 - 2 * u)

def measure_leading_silence(path, thr=200, max_sec=60.0):
    """测音频文件的前导静音长度（秒）——pjsk fillerSec（元数据/实测一致）。
    返回 None = 无法测量（非 16bit/读不到/全静音）。"""
    import wave
    import array
    try:
        w = wave.open(str(path), "rb")
    except Exception:
        return None
    with w:
        if w.getsampwidth() != 2:
            return None
        rate, ch = w.getframerate(), w.getnchannels()
        win = max(1, rate // 100)              # 10ms 窗
        limit = min(w.getnframes(), int(rate * max_sec))
        pos = 0
        while pos < limit:
            buf = w.readframes(min(win, limit - pos))
            if not buf:
                break
            a = array.array("h")
            a.frombytes(buf)
            if max((abs(x) for x in a), default=0) >= thr:
                for k, x in enumerate(a):          # 样本级精确定位首个超阈样本
                    if abs(x) >= thr:
                        return (pos + k // ch) / rate
                return pos / rate
            pos += len(a) // ch
        return None


def ugc_hh(h_c2s):
    """C2S 高度 → UGC 2 位 36 进制 hh（= (H-1)*2 ×10）"""
    v = max(0, min(1295, rhu((h_c2s - 1) * 2 * 10)))
    return x36(v // 36) + x36(v % 36)

def sig_of(m):
    """pjsk #MMM02（每小节四分音符数）→ 拍号 (num, den)。
    整数 x = x/4；小数如 2.5 = 5/2。"""
    fr = m if isinstance(m, Fraction) else Fraction(m)
    if fr.denominator == 1:
        return fr.numerator, 4
    return fr.numerator, fr.denominator


# ---------------------------------------------------------------- sus 解析

class Sus:
    def __init__(self):
        self.title = self.artist = self.designer = ""
        self.diff_name = ""
        self.songid = ""
        self.meters = {}        # bar -> Fraction(beats)
        self.bpm_table = {}
        self.bpm_events = []    # (bar, Fraction, value)
        self.shorts = []        # (bar, frac, lane, w, type)   通道1
        self.chains_raw = []    # (bar, frac, lane, w, vtype, ident) 通道3
        self.guides_raw = []    # 同上 通道9
        self.airs = []          # (bar, frac, lane, w, type)   通道5
        self.til = []           # #TIL00 滚动速度时间线 (bar, tick@480, speed)
        self.warn = []

def parse_sus(path):
    sus = Sus()
    parts = path.stem.split("_", 2)
    sus.songid = parts[0] if len(parts) >= 2 else path.stem
    sus.diff_name = parts[2] if len(parts) >= 3 else ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or not s.startswith("#"):
            continue
        m = BPMDEF_RE.match(s)
        if m:
            try:
                sus.bpm_table[b36(m[1])] = float(m[2])
            except ValueError:
                pass
            continue
        if s.startswith("#REQUEST"):
            continue
        m = re.match(r'^#TIL00:\s*"(.*)"', s)
        if m:
            for ent in m[1].split(","):
                ent = ent.strip()
                mm2 = re.match(r"(\d+)'(\d+):([0-9.]+)", ent)
                if mm2:
                    sus.til.append((int(mm2[1]), int(mm2[2]), float(mm2[3])))
            continue
        for pat, attr in ((r'^#TITLE\s+"(.*)"', "title"),
                          (r'^#ARTIST\s+"(.*)"', "artist"),
                          (r'^#DESIGNER\s+"(.*)"', "designer")):
            m = re.match(pat, s)
            if m:
                setattr(sus, attr, m[1])
                break
        else:
            m = METER_RE.match(s)
            if m:
                try:
                    sus.meters[int(m[1])] = Fraction(m[2])
                except (ValueError, ZeroDivisionError):
                    sus.warn.append(f"坏拍号行: {s}")
                continue
            m = BPMCH_RE.match(s)
            if m:
                bar, v = int(m[1]), re.sub(r"\s", "", m[2])
                n = len(v) // 2
                for i in range(n):
                    tok = int(v[2 * i:2 * i + 2], 36)
                    if tok == 0 or tok not in sus.bpm_table:
                        continue
                    sus.bpm_events.append((bar, Fraction(i, n), sus.bpm_table[tok]))
                continue
            m = NOTE_RE.match(s)
            if not m:
                continue
            bar, lt, lane, ident, data = int(m[1]), int(m[2]), int(m[3], 16), m[4], m[5]
            v = re.sub(r"\s", "", data)
            n = len(v) // 2
            for i in range(n):
                t, w = b36(v[2 * i]), b36(v[2 * i + 1])
                if t == 0 or w == 0:
                    continue
                frac = Fraction(i, n)
                if lt == 1:
                    sus.shorts.append((bar, frac, lane, w, t))
                elif lt == 3:
                    sus.chains_raw.append((bar, frac, lane, w, t, ident))
                elif lt == 9:
                    sus.guides_raw.append((bar, frac, lane, w, t, ident))
                elif lt == 5:
                    sus.airs.append((bar, frac, lane, w, t))
                elif lt in (2, 4):
                    sus.warn.append(f"通道{lt} 点位（pjsk 不用）bar{bar} lane{lane} t{t} 忽略")
    return sus


# ---------------------------------------------------------------- 中间模型

class Pt:
    """丝带顶点"""
    __slots__ = ("bar", "frac", "lane", "w", "vtype", "beat_abs",
                 "ease_in", "ease_out", "flicks", "skip", "friction", "fhide",
                 "fhide_t", "tap_relay")

    def __init__(self, bar, frac, lane, w, vtype):
        self.bar, self.frac, self.lane, self.w, self.vtype = bar, frac, lane, w, vtype
        self.beat_abs = None
        self.ease_in = self.ease_out = False
        self.flicks = []        # pjsk flick 标记 1/3/4
        self.skip = False       # ch1 t3
        self.friction = 0       # 0/5/6
        self.fhide = False      # ch1 t7/t8
        self.fhide_t = 0        # 7 或 8（t8=FrictionHideCritical）
        self.tap_relay = False  # 链中段 tap → 可见中继（用户裁定 2026-10-06）

    @property
    def key(self):
        return (self.bar, self.frac, self.lane, self.w)


class Chain:
    def __init__(self, pts):
        self.pts = pts


class Ground:
    """独立地面音符：TAP / CHR（含 Friction 翻译来的）"""
    __slots__ = ("bar", "frac", "lane", "w", "crit", "flicks", "beat_abs", "mark_keys")

    def __init__(self, bar, frac, lane, w, crit):
        self.bar, self.frac, self.lane, self.w, self.crit = bar, frac, lane, w, crit
        self.flicks = []
        self.beat_abs = None
        self.mark_keys = None      # 额外的 AIR 标记查找键（宽 tap 的头+尾 1 tick 差）

    @property
    def key(self):
        return (self.bar, self.frac, self.lane, self.w)


class Model:
    def __init__(self):
        self.grounds = []
        self.holds = []         # {"chain": Chain, "ex": bool}
        self.slides = []        # 同上
        self.guide_chains = []
        self.ald_chains = []    # 嵌套窄 slide 降级成的装饰链
        self.bpm_events = []
        self.counts = defaultdict(int)
        self.warn = []


def build_model(sus, opts):
    mdl = Model()
    meters = sus.meters
    mdl.warn = list(sus.warn)
    all_bars = ([b for b, *_ in sus.shorts] + [b for b, *_ in sus.chains_raw]
                + [b for b, *_ in sus.guides_raw] + [b for b, *_ in sus.airs]
                + list(meters) + [b for b, _, _ in sus.bpm_events])
    max_bar = max(all_bars + [0])
    # 绝对 beat / UGC tick 前缀
    cum_beats = [Fraction(0)]
    cum_ugc = [0]
    for b in range(max_bar + 1):
        m = meters.get(b, Fraction(4))
        cum_beats.append(cum_beats[-1] + m)
        cum_ugc.append(cum_ugc[-1] + rhu(UGB * m))
    mdl.cum_beats, mdl.cum_ugc, mdl.max_bar = cum_beats, cum_ugc, max_bar
    mdl.meters = meters

    def beat_abs(bar, frac):
        return cum_beats[bar] + frac * meters.get(bar, Fraction(4))

    def locate(beat):
        bar = bisect.bisect_right(cum_beats, beat) - 1
        bar = max(0, min(bar, max_bar))
        m = meters.get(bar, Fraction(4))
        frac = (beat - cum_beats[bar]) / m
        return bar, min(max(frac, Fraction(0)), Fraction(1))

    def abs_c2s(beat):
        bar, frac = locate(beat)
        return bar * RES + rhu(frac * RES)

    def abs_ugc(beat):
        bar, frac = locate(beat)
        return cum_ugc[bar] + rhu(frac * UGB * meters.get(bar, Fraction(4)))

    mdl.beat_abs, mdl.locate, mdl.abs_c2s, mdl.abs_ugc = beat_abs, locate, abs_c2s, abs_ugc

    def beat_of_c2s(tick_abs):
        bar = tick_abs // RES
        return cum_beats[bar] + Fraction(tick_abs % RES, RES) * meters.get(bar, Fraction(4))

    def beat_of_ugc(tick_abs):
        if tick_abs >= cum_ugc[-1]:
            return cum_beats[-1]
        bar = max(0, bisect.bisect_right(cum_ugc, tick_abs) - 1)
        frac = Fraction(tick_abs - cum_ugc[bar], UGB) / meters.get(bar, Fraction(4))
        return cum_beats[bar] + frac * meters.get(bar, Fraction(4))

    mdl.beat_of_c2s, mdl.beat_of_ugc = beat_of_c2s, beat_of_ugc
    mdl.bpm_events = sorted(sus.bpm_events, key=lambda e: (e[0], e[1])) or [(0, Fraction(0), 120.0)]

    # ---- 索引 ----
    air_at = defaultdict(list)
    for bar, frac, lane, w, t in sus.airs:
        air_at[(bar, frac, lane, w)].append(t)
    short_exact = defaultdict(list)     # (bar,frac,lane,w) -> [type]
    short_pos = defaultdict(list)       # (bar,frac,lane) -> [(w,type)]
    for bar, frac, lane, w, t in sus.shorts:
        short_exact[(bar, frac, lane, w)].append(t)
        short_pos[(bar, frac, lane)].append((w, t))

    # ---- 丝带重建（id 分组，t1 切链，t2 收链）----
    def rebuild(raw):
        by_id = defaultdict(list)
        for bar, frac, lane, w, t, ident in raw:
            by_id[ident].append(Pt(bar, frac, lane, w, t))
        chains = []
        for ident, pts in by_id.items():
            pts.sort(key=lambda p: (p.bar, p.frac))
            for p in pts:
                p.beat_abs = beat_abs(p.bar, p.frac)
            cur = []
            for p in pts:
                if p.vtype == 1 and cur:
                    chains.append(Chain(cur))
                    cur = [p]
                else:
                    cur.append(p)
                    if p.vtype == 2:
                        chains.append(Chain(cur))
                        cur = []
            if cur:
                chains.append(Chain(cur))
        return chains

    chains = rebuild(sus.chains_raw)
    mdl.guide_chains = rebuild(sus.guides_raw)
    for c in mdl.guide_chains:
        for p in c.pts:
            p.beat_abs = beat_abs(p.bar, p.frac)

    # ---- 顶点标记 ----
    chain_keys = set()
    for c in chains:
        for p in c.pts:
            chain_keys.add(p.key)
    for c in chains:
        for p in c.pts:
            for t in air_at.get(p.key, ()):
                if t == 2:
                    p.ease_in = True
                elif t in (5, 6):
                    p.ease_out = True
                elif t in (1, 3, 4):
                    p.flicks.append(t)
                else:
                    mdl.warn.append(f"未知 air 标记 t{t} @bar{p.bar}")
            for t in short_exact.get(p.key, ()):
                if t == 3:
                    p.skip = True
                elif t in (5, 6):
                    p.friction = t
                elif t in (7, 8):
                    p.fhide = True
                    p.fhide_t = t

    # ---- 装饰带判定（2026-10-06 最终版，用户截图确认）：**链头 t8=FrictionHideCritical
    # （非瞬时）→ 装饰线**——如 45/72 的"OK"字母笔画（大 hold 垫在下面、字母是装饰）；
    # 链头 t7 / 真实 tap / 无标记 → 判定丝带；瞬时静止链（≤2tick）→ 宽 tap（在下方分类处理）----
    for c in list(chains):
        if c.pts[0].fhide_t == 8 and float(c.pts[-1].beat_abs - c.pts[0].beat_abs) > 2 / 480:
            chains.remove(c)
            mdl.ald_chains.append(c)
            mdl.counts["guide_demoted"] += 1
            for p in c.pts:
                if p.flicks:
                    mdl.counts["flick_dropped"] += len(p.flicks)
                    p.flicks = []

    # ---- 链分类（静止→HOLD，移动→SLIDE；critical 头→Ex）----
    head_keys = {c.pts[0].key for c in chains}
    for c in chains:
        head = c.pts[0]
        ex = any(t in (2, 6) for t in short_exact.get(head.key, ()))
        # 静止链→HOLD；但宽度有变化的静止链→竖直 SLIDE（HLD 单宽度装不下变宽；
        # chunithm 竖直变宽段合法，官方 Sheriruth 同款）
        dur = float(c.pts[-1].beat_abs - head.beat_abs)
        if len({p.lane for p in c.pts}) == 1 and dur <= 2 / 480:
            # 瞬时静止链（≤2 pjsk tick）= 宽 tap（无条件——1tick 的"hold"在 C2S 里
            # 头尾塌缩会让 PenguinTools 抛 FormatException；用户实证：73-77 的三连闪
            # 是带 AIR 的宽 tap；ch1 t8=FrictionHideCritical → 金键 CHR；AIR 取 ch5
            # 方向标记；链头/尾的 ch1 t1/t2 判定由宽 tap 自身覆盖，已在其后吸收）
            g = Ground(head.bar, head.frac, head.lane, head.w, crit=True)
            g.mark_keys = [head.key, c.pts[-1].key]   # ch5 方向标记常在尾（1 tick 差）
            mdl.counts["wide_tap"] += 1
            mdl.grounds.append(g)
            continue
        static = len({p.lane for p in c.pts}) == 1 and len({p.w for p in c.pts}) == 1
        (mdl.holds if static else mdl.slides).append({"chain": c, "ex": ex})

    # ---- 地面单点（tap=slide 上的实点：链中段的 tap 出 TAP；丝带头/尾的 tap 被
    #      丝带自身判定覆盖 → 吸收，避免与 Ex 疑似载体重复；t7/t8 隐形层跳过）----
    headtail_keys = set()
    for sl in mdl.holds + mdl.slides:
        c = sl["chain"]
        headtail_keys.add(c.pts[0].key)
        headtail_keys.add(c.pts[-1].key)
    for bar, frac, lane, w, t in sus.shorts:
        if t == 4:
            mdl.counts["skill_dropped"] += 1
            continue
        if t == 3:
            if (bar, frac, lane, w) not in chain_keys:
                mdl.warn.append(f"Skip 标记不在丝带顶点上 bar{bar} lane{lane} — 忽略")
            continue
        if t in (7, 8):
            mdl.counts["fhide"] += 1
            continue
        if t not in (1, 2, 5, 6):
            mdl.warn.append(f"未知短音符类型 t{t} @bar{bar} — 忽略")
            continue
        if lane < FIELD_LO or lane > FIELD_HI:
            if t in (1, 2) and lane >= 14:
                mdl.counts["fever_dropped"] += 1
            else:
                mdl.warn.append(f"场外短音符 bar{bar} lane{lane} t{t} — 忽略")
            continue
        key = (bar, frac, lane, w)
        if key in headtail_keys and t in (1, 2):
            mdl.counts["headtail_absorbed"] += 1
            continue                       # 丝带头/尾判定即覆盖该 tap
        if t in (5, 6):
            if any(tt in (1, 2) for tt in short_exact.get(key, ())):
                continue                      # 同位已有 tap
            mdl.counts["friction_ground"] += 1
        mdl.grounds.append(Ground(bar, frac, lane, w, crit=(t in (2, 6))))
    for g in mdl.grounds:
        g.beat_abs = beat_abs(g.bar, g.frac)
        keys = g.mark_keys or [g.key]
        g.flicks = [t for k in keys for t in air_at.get(k, ()) if t in (1, 3, 4)]
    # ---- 链点上同位有地面音符（非链头）时，flick 归地面音符，避免 AIR 双发 ----
    ground_keys = {g.key for g in mdl.grounds}
    for group in mdl.holds + mdl.slides:
        for p in group["chain"].pts:
            if p.key in ground_keys and p.flicks:
                mdl.counts["flick_to_ground"] += len(p.flicks)
                p.flicks = []

    # ---- 没被消费的 air 标记 ----
    used = ground_keys | chain_keys
    for key, ts in air_at.items():
        for t in ts:
            if key in used:
                continue
            if t in (1, 3, 4):
                mdl.counts["flick_dropped"] += 1
            elif t in (2, 5, 6):
                mdl.counts["ease_orphan"] += 1
    return mdl


# ---------------------------------------------------------------- 几何烘焙

def span_cells(lane, w):
    """pjsk (lane,width) → 中二 (cell, width)；cell=lane 原值直通（用户裁定 2026-10-06：
    不改宽度、场地左右各空 2 轨）。lane 2..13 → cell 2..13，lane+w≤14 ⇒ cell+w≤14 恒合法。"""
    return lane, w

def span_cells_f(lane_f, w_f):
    a = math.floor(lane_f)
    b = math.floor(lane_f + w_f)
    c = max(0, min(15, a))
    return c, max(1, min(b, 16) - c)

def cell_left_edge(cell):
    """1:1 映射下 chunithm cell 的左缘即 pjsk lane 坐标里的同号整点"""
    return float(cell)

def bake_curve(beat0, lane0, w0, beat1, lane1, w1, ei, eo):
    """曲线段采样（不含起点，含终点）：[(beat, lane_f, w_f)]（整数格）。

    **移植社区标准算法 = Margrete Interpolator（doc04 §4.2 参考实现，本仓 repos/
    margrete-air-curve-converter/src/mgxc/Interpolator.cpp）**：
    - 顶点只按 lane **整数格**步进（每格一个，`HorizontalSegment`）；顶点位置=整数格、
      时刻=反解缓动（InverseSolve）得——顶点精确落在理想曲线上，无 floor/round 偏置锯齿；
    - 宽度在顶点处取最近整数（chunithm 段内宽度线性插值，官方 Sheriruth `12 4 → 7 6`
      即单段直插，不为宽度加顶点）；
    - 同 tick 相撞由写出端 keep-better（Margrete PushSegment 语义）处理。
    pjsk 的缓动是 (lane,时间) 双轴贝塞尔：lane 走 x=smoothstep(u)、时间走 y(u)。"""
    d_lane, d_w = lane1 - lane0, w1 - w0
    db = beat1 - beat0
    if not (ei or eo) or d_lane == 0 or db == 0:
        return [(beat1, float(lane1), float(w1))]
    t1c = 0.5 if ei else 0.0
    t2c = 0.5 if eo else 1.0
    out = []
    step = 1 if d_lane > 0 else -1
    for cell in range(int(lane0) + step, int(lane1), step):   # 中间整数格（端点是源顶点）
        xe = (cell - lane0) / d_lane
        u = inv_mono(smoothstep, min(1.0, max(0.0, xe)))
        beat = beat0 + (3 * (1 - u) ** 2 * u * t1c
                        + 3 * (1 - u) * u * u * t2c + u ** 3) * db
        wq = max(1, int(round(w0 + u * d_w)))
        out.append((beat, float(cell), float(wq)))
    out.append((beat1, float(lane1), float(w1)))
    return out

def bake_segment(P, Q):
    """Pt 版 bake_curve。"""
    return bake_curve(P.beat_abs, P.lane, P.w, Q.beat_abs, Q.lane, Q.w,
                      P.ease_in, P.ease_out)

def bake_slide(chain):
    """链 → (head, [(beat_abs, lane_f, w_f, visible)])；Skip 点并回曲线、留可见中继"""
    pts = chain.pts
    head, tail = pts[0], pts[-1]
    skips = [p for p in pts[1:-1] if p.skip and not (p.ease_in or p.ease_out) and not p.flicks]
    bounds = [p for p in pts if not any(p is s for s in skips)]
    emitted = []
    segs = list(zip(bounds, bounds[1:]))
    for P, Q in segs:
        baked = bake_segment(P, Q)
        for j, (beat, lane_f, w_f) in enumerate(baked):
            is_end = j == len(baked) - 1
            # 中继可见性**完全跟随源**（vtype 3 = 源可见中继）+ 链尾收尾
            # （参考渲染器只对 ch3 type-3 画菱形；tap_relay 强制可见会造出
            #  用户反馈的"不该有的中继点"——2026-10-06 修正）
            visible = is_end and (Q is tail or Q.vtype == 3)
            emitted.append([beat, lane_f, w_f, visible])
    for S in skips:                       # Skip 点：曲线上的可见中继
        for P, Q in segs:
            if Q.beat_abs <= P.beat_abs or not (P.beat_abs <= S.beat_abs <= Q.beat_abs):
                continue
            tt = float((S.beat_abs - P.beat_abs) / (Q.beat_abs - P.beat_abs))
            if P.ease_in or P.ease_out:
                t1 = 0.5 if P.ease_in else 0.0
                t2 = 0.5 if P.ease_out else 1.0
                u = inv_mono(lambda u: 3 * (1 - u) ** 2 * u * t1 + 3 * (1 - u) * u * u * t2 + u ** 3, tt)
                x = smoothstep(u)
            else:
                x = tt
            lane_f = P.lane + x * (Q.lane - P.lane)
            w_f = P.w + tt * (Q.w - P.w)
            emitted.append([S.beat_abs, lane_f, w_f, True])
            break
    emitted.sort(key=lambda e: e[0])
    return head, emitted


# ---------------------------------------------------------------- 写出端

def collect_alds(mdl, opts):
    """装饰线段：[(beat0, lane0, w0, beat1, lane1, w1)]（pjsk 坐标，float）。
    导向带/降级链走曲线烘焙（带 ease 锚的段逐格采样），Friction 覆盖线为直连段。"""
    segs = []
    mode = opts.decorations
    if mode == "off":
        return segs

    def add_line(baked):
        # 单线装饰（2026-10-06 用户裁定：双轮廓机制去掉，保留单条 ALD 即可）
        for A, B in zip(baked, baked[1:]):
            segs.append((A[0], A[1], A[2], B[0], B[1], B[2]))

    # 0) 导向带（降级链）——曲线烘焙单线
    for c in getattr(mdl, "ald_chains", []):
        baked = [(c.pts[0].beat_abs, float(c.pts[0].lane), float(c.pts[0].w))]
        for A, B in zip(c.pts, c.pts[1:]):
            baked.extend(bake_segment(A, B))
        add_line(baked)
    # 1) ch9 Guide 引导带（仅可见点 1/2 之间的段；sus 无 ease 信息，直连）
    for c in mdl.guide_chains:
        vis = [p for p in c.pts if p.vtype in (1, 2)]
        add_line([(q.beat_abs, float(q.lane), float(q.w)) for q in vis])
    return segs


def write_c2s(mdl, sus, opts, path):
    L = []
    bpm0 = mdl.bpm_events[0][2]
    L.append(f"VERSION\t1.14.00\t1.14.00")
    L.append("MUSIC\t0")
    L.append("SEQUENCEID\t0")
    L.append(f"DIFFICULT\t{C2S_DIFF.get(sus.diff_name, '03')}")
    L.append(f"LEVEL\t{opts.level or '0.0'}")
    L.append(f"CREATOR\t{opts.creator or ('pjsk2chuni (sus by ' + (sus.designer or '?') + ')')}")
    L.append(f"BPM_DEF\t{bpm0:.3f}\t{bpm0:.3f}\t{bpm0:.3f}\t{bpm0:.3f}")
    L.append("MET_DEF\t4\t4")
    L.append("RESOLUTION\t384")
    L.append("CLK_DEF\t384")
    L.append("PROGJUDGE_BPM\t240.000")
    L.append("PROGJUDGE_AER\t  0.999")
    L.append("TUTORIAL\t0")
    L.append("")
    for bar, frac, v in mdl.bpm_events:
        L.append(f"BPM\t{bar}\t{rhu(frac * RES)}\t{v:.3f}")
    prev = None
    for b in range(mdl.max_bar + 1):
        m = mdl.meters.get(b, Fraction(4))
        if b == 0 or m != prev:
            num, den = sig_of(m)
            L.append(f"MET\t{b}\t0\t{den}\t{num}")
        prev = m
    # #TIL00 滚动速度时间线 → SFL 链（每段 dur=到下一事件；末段到谱尾）
    til = sorted({(b * RES + rhu(Fraction(tk, max(1, rhu(UGB * mdl.meters.get(b, Fraction(4))))) * RES), sp)
                  for b, tk, sp in sus.til})
    for i, (abs_t, sp) in enumerate(til):
        end = til[i + 1][0] if i + 1 < len(til) else (mdl.max_bar + 1) * RES
        dur = end - abs_t
        if dur <= 0:
            continue
        bb2, tk2 = divmod(abs_t, RES)
        L.append(f"SFL\t{bb2}\t{tk2}\t{dur}\t{sp:.6f}")
    L.append("")

    rows = []   # (abs_tick, seq, text)

    def add(abs_t, text):
        rows.append((abs_t, len(rows), text))

    def air_rows(beat, lane, w, flicks, trg):
        c, wc = span_cells(lane, w)
        for t in flicks:
            word = {1: "AIR", 3: "AUL", 4: "AUR"}[t]
            bar, tick = divmod(mdl.abs_c2s(beat), RES)
            add(mdl.abs_c2s(beat), f"{word}\t{bar}\t{tick}\t{c}\t{wc}\t{trg}\tDEF")
            mdl.counts["air_c2s"] += 1

    for g in sorted(mdl.grounds, key=lambda g: g.beat_abs):
        c, wc = span_cells(g.lane, g.w)
        bar, tick = divmod(mdl.abs_c2s(g.beat_abs), RES)
        if g.crit:
            add(mdl.abs_c2s(g.beat_abs), f"CHR\t{bar}\t{tick}\t{c}\t{wc}\tCE")
        else:
            add(mdl.abs_c2s(g.beat_abs), f"TAP\t{bar}\t{tick}\t{c}\t{wc}")
        air_rows(g.beat_abs, g.lane, g.w, g.flicks, "CHR" if g.crit else "TAP")

    for sl in mdl.holds:
        c = sl["chain"]
        h, t = c.pts[0], c.pts[-1]
        c0, w0 = span_cells(h.lane, h.w)
        t0, t1 = mdl.abs_c2s(h.beat_abs), mdl.abs_c2s(t.beat_abs)
        dur = max(1, t1 - t0)
        bar, tick = divmod(t0, RES)
        word = "HXD" if sl["ex"] else "HLD"
        add(t0, f"{word}\t{bar}\t{tick}\t{c0}\t{w0}\t{dur}" + ("\tCE" if sl["ex"] else ""))
        for p in c.pts:
            air_rows(p.beat_abs, p.lane, p.w, p.flicks, "HLD")

    for sl in mdl.slides:
        c = sl["chain"]
        head, pts = bake_slide(c)
        t0 = mdl.abs_c2s(head.beat_abs)
        c0, w0 = span_cells(head.lane, head.w)
        # 同 tick 择优（04 报告 §4.2 PushSegment）：保留离理想曲线（时间上）更近的点
        pts_fmt = []
        for beat, lane_f, w_f, visible in pts:
            t = mdl.abs_c2s(beat)
            if not pts_fmt and t <= t0:
                continue                     # 与链头同 tick（零时长段）→ 丢
            cc, wc = span_cells_f(lane_f, w_f)
            if pts_fmt and t == pts_fmt[-1][0]:
                bt = mdl.beat_of_c2s(t)
                if abs(beat - bt) < abs(pts_fmt[-1][3] - bt):
                    pts_fmt[-1] = (t, cc, wc, beat, visible or pts_fmt[-1][4])
            elif pts_fmt and t < pts_fmt[-1][0]:
                continue
            else:
                pts_fmt.append((t, cc, wc, beat, visible))
        prev_t, prev_c, prev_w = t0, c0, w0
        seg_n = 0
        for t, cc, wc, _beat, visible in pts_fmt:
            dur = t - prev_t
            word = ("SXD" if visible else "SXC") if sl["ex"] else ("SLD" if visible else "SLC")
            tail = "\tSLD\tCE" if sl["ex"] else "\tSLD"
            bar, tick = divmod(prev_t, RES)
            add(prev_t, f"{word}\t{bar}\t{tick}\t{prev_c}\t{prev_w}\t{dur}\t{cc}\t{wc}{tail}")
            prev_t, prev_c, prev_w = t, cc, wc
            seg_n += 1
        mdl.counts["slide_segs"] += seg_n
        for p in c.pts:
            air_rows(p.beat_abs, p.lane, p.w, p.flicks, "SLD")

    _ald_cursor = None
    for b0, l0, w0, b1, l1, w1 in sorted(collect_alds(mdl, opts), key=lambda sg: mdl.abs_c2s(sg[0])):
        t0, t1 = mdl.abs_c2s(b0), mdl.abs_c2s(b1)
        if _ald_cursor is not None and t0 <= _ald_cursor:
            t1 += _ald_cursor + 5 - t0      # 整段顺延：装饰节点不与前一装饰塌缩
            t0 = _ald_cursor + 5
        dur = max(5, t1 - t0)               # 起止至少差 1 个 C2S tick
        t1 = t0 + dur
        c0, w0c = span_cells_f(l0, w0)
        c1, w1c = span_cells_f(l1, w1)
        bar, tick = divmod(t0, RES)
        H = opts.crush_h
        add(t0, f"ALD\t{bar}\t{tick}\t{c0}\t{w0c}\t0\t{H:.1f}\t{dur}\t{c1}\t{w1c}\t{H:.1f}\tGRN")
        mdl.counts["ald"] += 1
        _ald_cursor = t1

    rows.sort(key=lambda r: (r[0], r[1]))
    L.extend(r[2] for r in rows)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def write_ugc(mdl, sus, opts, path):
    bpm0 = mdl.bpm_events[0][2]
    H = []
    H.append("' converted by pjsk2chuni (research/08 + research/11 spec)")
    H.append("@VER\t8")
    H.append("@EXVER\t1")
    H.append(f"@TITLE\t{opts.title or sus.title or sus.songid}")
    H.append(f"@ARTIST\t{opts.artist or sus.artist or ''}")
    H.append(f"@DESIGN\t{opts.creator or sus.designer or 'pjsk2chuni'}")
    H.append(f"@DIFF\t{UGC_DIFF.get(sus.diff_name, '3')}")
    H.append(f"@LEVEL\t{opts.level or '0'}")
    H.append(f"@CONST\t{opts.level or '0'}")
    H.append(f"@SONGID\t{opts.songid or ('pjsk_' + sus.songid)}")
    H.append("@FLAG\tEXLONG\tTRUE")
    H.append("@FLAG\tHIPRECISION\tTRUE")
    H.append("@TICKS\t480")
    if getattr(opts, "bgm", None):
        H.append(f"@BGM\t{opts.bgm}")
        ofs = getattr(opts, "bgmofs", "auto")
        if isinstance(ofs, str) and ofs.strip().lower() == "auto":
            trim = measure_leading_silence(Path(opts.outdir) / opts.bgm)
            ofs_v = -trim if trim is not None else 0.0
            if trim is None:
                print(f"   [warn] 无法测量 {opts.bgm} 前导静音，@BGMOFS=0")
            else:
                print(f"   [bgm] 前导静音 {trim:.3f}s（fillerSec）→ @BGMOFS {-trim:.5f}")
        else:
            ofs_v = float(ofs)
        H.append(f"@BGMOFS\t{ofs_v:.5f}")
        if getattr(opts, "bgmprv", None) is not None:
            s, e = opts.bgmprv
            H.append(f"@BGMPRV\t{s:.2f}\t{e:.2f}")
    prev = None
    for b in range(mdl.max_bar + 1):
        m = mdl.meters.get(b, Fraction(4))
        if b == 0 or m != prev:
            num, den = sig_of(m)
            H.append(f"@BEAT\t{b}\t{num}\t{den}")
        prev = m
    for bar, frac, v in mdl.bpm_events:
        tick = rhu(frac * UGB * mdl.meters.get(bar, Fraction(4)))
        H.append(f"@BPM\t{bar}'{tick}\t{v:.5f}")
    H.append("@TIL\t0\t0'0\t1.00000")
    for _b, _t, _s in sorted(sus.til):
        H.append(f"@TIL\t0\t{_b}'{_t}\t{_s:.5f}")   # #TIL00 滚动速度时间线
    H.append("@MAINTIL\t0")
    H.append("@ENDHEAD")

    blocks = []   # (abs_tick, seq, [lines])

    def add(abs_t, lines):
        blocks.append((abs_t, len(blocks), lines))

    def air_lines(beat, lane, w, flicks):
        c, wc = span_cells(lane, w)
        bar, frac = mdl.locate(beat)
        tick = rhu(frac * UGB * mdl.meters.get(bar, Fraction(4)))
        out = []
        for t in flicks:
            dd = {1: "UC", 3: "UL", 4: "UR"}[t]
            # AIR 是独立父行，必须带 #Bar'Tick: 前缀（裸行会被 UMIGURI 忽略）
            out.append(f"#{bar}'{tick}:a{x36(c)}{x36(wc)}{dd}N")
            mdl.counts["air_ugc"] += 1
        return out

    for g in sorted(mdl.grounds, key=lambda g: mdl.abs_ugc(g.beat_abs)):
        c, wc = span_cells(g.lane, g.w)
        bar, tick = mdl.locate(g.beat_abs)
        tick = rhu(tick * UGB * mdl.meters.get(bar, Fraction(4)))
        head_row = f"x{x36(c)}{x36(wc)}C" if g.crit else f"t{x36(c)}{x36(wc)}"
        add(mdl.abs_ugc(g.beat_abs), [f"#{bar}'{tick}:{head_row}"] + air_lines(g.beat_abs, g.lane, g.w, g.flicks))

    for sl in mdl.holds:
        c = sl["chain"]
        h, t = c.pts[0], c.pts[-1]
        c0, w0 = span_cells(h.lane, h.w)
        bar, frac = mdl.locate(h.beat_abs)
        tick = rhu(frac * UGB * mdl.meters.get(bar, Fraction(4)))
        t0, t1 = mdl.abs_ugc(h.beat_abs), mdl.abs_ugc(t.beat_abs)
        dur = max(1, t1 - t0)
        lines = []
        if sl["ex"]:
            lines.append(f"#{bar}'{tick}:x{x36(c0)}{x36(w0)}C")
        lines.append(f"#{bar}'{tick}:h{x36(c0)}{x36(w0)}")
        lines.append(f"#{dur}>s")                       # 结束子行必须紧跟父行
        for p in c.pts:
            lines += air_lines(p.beat_abs, p.lane, p.w, p.flicks)
        add(t0, lines)

    for sl in mdl.slides:
        c = sl["chain"]
        head, pts = bake_slide(c)
        c0, w0 = span_cells(head.lane, head.w)
        bar, frac = mdl.locate(head.beat_abs)
        tick = rhu(frac * UGB * mdl.meters.get(bar, Fraction(4)))
        t0 = mdl.abs_ugc(head.beat_abs)
        lines = []
        if sl["ex"]:
            lines.append(f"#{bar}'{tick}:x{x36(c0)}{x36(w0)}C")
        lines.append(f"#{bar}'{tick}:s{x36(c0)}{x36(w0)}")
        # 同 tick 择优（04 报告 §4.2 PushSegment）——**在 C2S tick 级去重**：
        # PenguinTools/UgcParser 转 C2S 时两个相邻子行（UGC 1 tick = 0.2 C2S tick）
        # 会塌缩到同一 C2S tick 并抛 FormatException，故子行间隔强制 ≥5 UGC tick
        pts_fmt = []
        for beat, lane_f, w_f, visible in pts:
            cc, wc = span_cells_f(lane_f, w_f)
            ct = mdl.abs_c2s(beat)
            if pts_fmt and ct == pts_fmt[-1][0]:
                bt = mdl.beat_of_c2s(ct)
                if abs(beat - bt) < abs(pts_fmt[-1][3] - bt):
                    pts_fmt[-1] = (ct, cc, wc, beat, visible or pts_fmt[-1][4])
            elif pts_fmt and ct < pts_fmt[-1][0]:
                continue
            else:
                pts_fmt.append((ct, cc, wc, beat, visible))
        seg_n = 0
        prev_rel = 0
        for ct, cc, wc, _beat, visible in pts_fmt:
            rel = max(prev_rel + 5, mdl.abs_ugc(_beat) - t0)
            lines.append(f"#{rel}>{'s' if visible else 'c'}{x36(cc)}{x36(wc)}")
            prev_rel = rel
            seg_n += 1
        for p in c.pts:
            lines += air_lines(p.beat_abs, p.lane, p.w, p.flicks)
        mdl.counts["slide_segs"] += seg_n
        add(t0, lines)

    _ald_cursor = None
    for b0, l0, w0, b1, l1, w1 in sorted(collect_alds(mdl, opts), key=lambda sg: mdl.abs_ugc(sg[0])):
        t0, t1 = mdl.abs_ugc(b0), mdl.abs_ugc(b1)
        if _ald_cursor is not None and t0 <= _ald_cursor:
            t1 += _ald_cursor + 5 - t0      # 整段顺延：装饰节点不与前一装饰塌缩
            t0 = _ald_cursor + 5
        dur = max(5, t1 - t0)               # 起止至少差 1 个 C2S tick
        t1 = t0 + dur
        c0, w0c = span_cells_f(l0, w0)
        c1, w1c = span_cells_f(l1, w1)
        bar, frac = mdl.locate(b0)
        tick = rhu(frac * UGB * mdl.meters.get(bar, Fraction(4)))
        hh = ugc_hh(opts.crush_h)
        lines = [f"#{bar}'{tick}:C{x36(c0)}{x36(w0c)}{hh}5,0", f"#{dur}>c{x36(c1)}{x36(w1c)}{hh}"]
        mdl.counts["ald"] += 1
        add(t0, lines)

    blocks.sort(key=lambda b: (b[0], b[1]))
    body = []
    for _, _, ls in blocks:
        body.extend(ls)
    path.write_text("\n".join(H + body) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- CLI

def convert_file(path, opts):
    sus = parse_sus(path)
    if path.stem.endswith("_info") or sus.diff_name == "info":
        return None
    mdl = build_model(sus, opts)
    outdir = Path(opts.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = path.stem
    written = []
    if "c2s" in opts.formats:
        p = outdir / f"{stem}.c2s"
        write_c2s(mdl, sus, opts, p)
        written.append(p)
    if "ugc" in opts.formats:
        p = outdir / f"{stem}.ugc"
        write_ugc(mdl, sus, opts, p)
        written.append(p)
    k = mdl.counts
    n_tap = sum(1 for g in mdl.grounds if not g.crit)
    n_chr = sum(1 for g in mdl.grounds if g.crit)
    air = k.get("air_c2s", k.get("air_ugc", 0))
    print(f"== {path.name}")
    print(f"   TAP {n_tap}  CHR {n_chr}  HOLD {len(mdl.holds)}  "
          f"SLIDE {len(mdl.slides)} 链/{k.get('slide_segs', 0)} 段  "
          f"AIR {air}(弃{k.get('flick_dropped', 0)})  ALD {k.get('ald', 0)}")
    print(f"   宽tap {k.get('wide_tap', 0)}  Friction→实点 {k.get('friction_ground', 0)}  "
          f"FrictionHide弃 {k.get('fhide', 0)}  "
          f"弃事件 skill{k.get('skill_dropped', 0)}/fever{k.get('fever_dropped', 0)}  "
          f"孤立缓动锚 {k.get('ease_orphan', 0)}")
    for w in mdl.warn[:6]:
        print(f"   [warn] {w}")
    if len(mdl.warn) > 6:
        print(f"   [warn] …共 {len(mdl.warn)} 条")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="pjsk sus → chunithm c2s/ugc")
    ap.add_argument("inputs", nargs="+", help=".sus 文件或目录")
    ap.add_argument("-o", "--outdir", default="output/pjsk")
    ap.add_argument("--formats", default="c2s,ugc", help="逗号分隔：c2s,ugc")
    ap.add_argument("--decorations", choices=["all", "guides", "off"], default="all",
                    help="ALD 装饰线来源：all=Guide+丝带Friction（默认）/ guides / off")
    ap.add_argument("--no-merge", action="store_true", help="关闭 FrictionHide 链续接合并")
    ap.add_argument("--crush-h", type=float, default=1.0, help="装饰线高度（C2S H，默认 1.0）")
    ap.add_argument("--title"), ap.add_argument("--artist")
    ap.add_argument("--level"), ap.add_argument("--creator"), ap.add_argument("--songid")
    ap.add_argument("--bgm", help="UGC @BGM 音频文件名（相对谱面目录）")
    ap.add_argument("--bgmofs", default="auto",
                    help="音源偏移秒（正=延后/负=提前）；auto=自动测前导静音取负（默认）")
    ap.add_argument("--bgmprv", help="试听范围秒，如 9:75")
    opts = ap.parse_args(argv)
    opts.formats = [f.strip().lower() for f in opts.formats.split(",") if f.strip()]
    if getattr(opts, "bgmprv", None):
        a, b = opts.bgmprv.split(":")
        opts.bgmprv = (float(a), float(b))
    files = []
    for inp in opts.inputs:
        p = Path(inp)
        if p.is_dir():
            files.extend(sorted(p.glob("*.sus")))
        elif p.suffix == ".sus":
            files.append(p)
        else:
            print(f"跳过 {inp}（不是 .sus）", file=sys.stderr)
    n = 0
    for f in files:
        try:
            if convert_file(f, opts) is not None:
                n += 1
        except Exception as e:
            print(f"[ERR] {f.name}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    print(f"\n完成：{n}/{len(files)} 张 → {opts.outdir}（{','.join(opts.formats)}）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
