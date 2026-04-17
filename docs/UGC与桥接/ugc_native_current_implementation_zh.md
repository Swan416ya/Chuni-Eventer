# UGC 原生转 c2s 当前实现说明

本文档描述当前仓库中“**不依赖 mgxc 回退**”的 `UGC -> c2s` 实现状态，包括：

- 代码入口与执行链路
- UGC 解析规则（头部与正文）
- 中间层与 c2s 输出映射
- 已做过的关键优化点
- 当前差异瓶颈与下一步建议

---

## 1. 目标与现状

目标是实现：

- 输入：`.ugc`
- 输出：`.c2s`
- 约束：不通过同目录 `mgxc` 回退，不依赖 `PenguinBridge mgxc-to-c2s`

现状：

- 已有可运行的原生 UGC 路径（`backend=python`）
- 事件层（`BPM/BEAT/TIL`）已基本打通
- 音符层已覆盖 Tap/Hold/Slide/Air 以及一部分高级节点（`ASC/ASD/SXC/SXD/HXD/ALD/SLA`）
- 与参考 c2s 仍存在明显差异，主要在 `C...` 紧凑编码与高级节点语义还原

---

## 2. 代码入口与执行流程

主入口：`chuni_eventer_desktop/pgko_to_c2s.py::convert_pgko_chart_pick_to_c2s_with_backend`

当前行为：

1. 若 `pick.ext == "ugc"`：
   - 走 `_parse_ugc(...)` 解析 UGC
   - 走 `_emit_c2s_from_semantic(...)` 输出 c2s
   - 返回 `(out_path, "python")`

2. 若 `pick.ext == "mgxc"`：
   - 先尝试 C# bridge（`convert_mgxc_with_penguin_bridge`）
   - 失败时回退 Python 的 `_parse_mgxc + _emit_c2s_from_semantic`

说明：UGC 分支已经是“原生直转”，不再依赖 `_find_fallback_mgxc`。

---

## 3. UGC 解析实现（`_parse_ugc`）

### 3.1 头部命令解析（`@...`）

已处理命令（核心）：

- 元信息：`TITLE`、`ARTIST`、`DESIGN`、`SONGID`、`BGM`、`DIFF`、`CONST`
- 开关：`FLAG SOFFSET`
- 事件：`BPM`、`BEAT`、`SPDMOD`、`TIL`、`USETIL`

时间换算要点：

- 先收集 `BEAT` 构建拍号轴
- `Bar'Tick` 通过 `_build_bar_to_tick(...)` 转绝对 tick
- 已支持“Tick 跨小节且中间拍号变化”的逐段推进（这是后来修复点）

### 3.2 正文行解析（`#...`）

支持两种行：

- 父行：`#Bar'Tick:payload[,suffix]`
- 子行：`#offset>payload`

已解析的正文类型（按 payload 首字符）：

- `t` Tap
- `x` ExTap
- `f` Flick
- `d` Damage
- `h` Hold
- `s` Slide
- `a` Air
- `H` AirHold
- `S` AirSlide
- `C` AirCrush（含 `,interval`）

`C` 行目前状态：

- 已解析颜色字符与 interval
- 已按 interval 对类型做分流（当前策略：`interval<0` 走 0x09，否则 0x0A）
- 已尝试基于 interval 生成 `SLA`

---

## 4. 中间层模型

当前统一中间层沿用 mgxc 同构结构：

- `_MgxcMeta`
- `_MgxcEvent(kind, tick, value, value2)`
- `_MgxcNote(typ, long_attr, direction, ex_attr, x, width, height, tick, timeline, seq)`

优势：

- 可复用现有 `_emit_c2s_from_semantic` 主体
- 可直接与 `_parse_mgxc` 结果做结构级对比

---

## 5. c2s 输出实现（`_emit_c2s_from_semantic`）

### 5.1 事件输出

- `bpm -> BPM`
- `beat -> MET`
- `smod -> DCM`
- `til -> SLP`

其中：

- tick 缩放为 `384 / MGXC_TICKS_PER_BAR_4_4`
- `SOFFSET` 会触发额外平移逻辑

### 5.2 音符输出

基础类型：

- `0x01 -> TAP`
- `0x02 -> CHR`
- `0x03 -> FLK`
- `0x04 -> MNE`
- `0x05 -> HLD`
- `0x06 -> SLD/SLC`
- `0x07 -> AIR/AUL/AUR/ADL/ADR/ADW`

高级类型（当前已接入）：

- `0x08 -> HXD`
- `0x09 -> ASC/ASD/SXC`（按 long_attr 分支）
- `0x0A -> ALD`，并尝试补 `SLA`

附加逻辑：

- 空中 linkage 推断（优先同 tick 覆盖，再历史覆盖）
- 同拍输出排序（当前仍在调优）

---

## 6. c2s emitter 扩展

文件：`chuni_eventer_desktop/_suspect/c2s_emit.py`

在原有基础上新增了：

- `HxdNote`
- `AscNote`
- `AsdNote`
- `AldNote`
- `SlaNote`
- `SxcNote`
- `SxdNote`

并对头部文本做了格式对齐（`PROGJUDGE_AER` 与空行结构）。

---

## 7. 评估与迭代机制

### 7.1 评估脚本

`scripts/evaluate_ugc_native_similarity.py`

每轮自动对两个样本输出：

- `same_bytes`
- `similarity(seq-pos)`（同下标行一致率）
- `similarity(edit-op)`（SequenceMatcher 比率）
- `top_tag_deltas`
- `first_diff`

### 7.2 迭代日志

`docs/ugc_native_conversion_iteration_log_zh.md`

每次代码修改后：

1. 重新生成两份 native c2s
2. 与参考 c2s 对比
3. 追加一轮记录

---

## 8. 当前主要问题（未解决）

1. **`C...` 紧凑编码语义不完整**
   - interval、颜色、子节点类型、控制点与终点语义尚未完全贴合官方行为
   - 直接导致 `ALD/SLA` 数量与位置偏差

2. **高级节点生成规则仍与官方存在结构差异**
   - `SXC/SXD/ASC/ASD/HXD` 的触发条件与分段策略仍不够准确

3. **同拍输出顺序仍有局部偏差**
   - 行顺序差异会放大 line-by-line 相似度损失

4. **当前是“启发式逼近”，不是“规格完整实现”**
   - 已能跑通，但未达到“稳定高一致”目标

---

## 9. 结论

当前实现已经从“不可用”推进到“可运行且可持续评估迭代”，并建立了完整的回归记录机制。  
但要达到高一致度（例如 70%+ edit-op 甚至接近字节等价），关键仍在于补齐 `C...` 紧凑语法与高级节点的完整语义映射，而不仅是微调排序或单点参数。

