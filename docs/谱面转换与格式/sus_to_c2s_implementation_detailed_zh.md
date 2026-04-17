# SUS → c2s 转谱实现说明（与代码 `sus_to_c2s.py` 对照）

本文档说明 **本仓库当前** 从 Project SEKAI 系 **SUS** 文本生成 **CHUNITHM 文本谱 `.c2s`** 的**真实实现逻辑**，以及每条谱面事件在输出文件里**具体长什么样**。  

**重要结论（请先读）**：该实现是 **实验性子集转换**，与官谱 / [PenguinTools](https://github.com/Foahh/PenguinTools) 经由 MRGC 等中间格式的管线 **不在同一完成度**。许多 SUS 语义被忽略或过度简化，生成结果在真机上常表现为 **时间/滑条/流速** 与预期不符，因此不宜称为「可依赖的转谱器」。下文在 **§10** 归纳与官谱的差距。

---

## 1. 代码入口与调用关系

| 符号 | 文件 | 作用 |
|------|------|------|
| `convert_sus_to_c2s(sus_text: str) -> str` | `chuni_eventer_desktop/sus_to_c2s.py` | 输入整段 SUS 正文，返回完整 c2s 文本（UTF-8 逻辑串）。 |
| `try_convert_sus_to_c2s_bytes(sus_text: str) -> bytes \| None` | 同上 | 包装 `convert_sus_to_c2s`；任意异常则返回 `None`，不向外抛。 |
| `save_pjsk_bundle_to_cache` | `chuni_eventer_desktop/pjsk_sheet_client.py` | 下载 SUS 后调用 `try_convert_sus_to_c2s_bytes`，成功则写入 `pjsk_cache/.../chuni/*.c2s`。 |

PJSK 难度与输出文件名对应见 `PJSK_TO_CHUNI_SLOT`（如 `normal` → `BASIC.c2s`），与转谱算法本身无关。

---

## 2. 总体流水线（三步）

实现上 **`convert_sus_to_c2s` 固定顺序**为：

1. **扫描所有 `#` 行**，拆成 `(行号, 行内容)` 列表（`_iter_sus_commands`）。
2. **`_collect_state`**：只解析元数据与小节拍长、BPM 引用关系，得到 `_SusParseState`（每小节拍数、`ticks_per_beat`、BPM 定义表等）。**不在这里生成音符**。
3. **`_emit_notes_and_slides`**：再次扫描 `#` 行，解析 Tap / Hold / Slide / Directional，生成若干 `_TimedLine`（每行对应将来 c2s 里的一行正文）。
4. 另建 **`event_lines`**：在若干小节起点写 `BPM` 行，并在全局 tick 0 写一条 **`MET`**。
5. 将 **`event_lines + note_lines`** 按 `_TimedLine` 排序（先 `sort_tick`，再 `kind_pri`，再 `tie`，再 `text`），**只拼接 `.text` 字段**，前面再接**固定文件头**，得到最终字符串。

---

## 3. SUS 侧读取了哪些内容

### 3.1 元数据与 REQUEST（`_collect_state`）

| SUS 前缀 | 处理方式 |
|----------|----------|
| `#TITLE` / `#ARTIST` / `#DESIGNER`（含拼写 `DESINGER`） | 记入 state，**仅 CREATOR 间接使用**（见文件头）。 |
| `#REQUEST "…"` | 用正则找 `ticks_per_beat N`，成功则 `st.ticks_per_beat = N`（默认 **480**）。 |
| `#BASEBPM` | 作为「主 BPM」候选。 |
| `#BPMxx` | `xx` 两字符为键，值为 BPM 浮点，存入 `bpm_defs`。 |
| 形如 `#mmm02: …` | 小节 `mmm` 的**拍数**（measure length），更新 `active_beats`，再铺到 `beats_from_bar`。 |
| 形如 `#mmm08: …` | 在小节 `mmm` 引用某个 `#BPMxx` 的键（两字符），记入 `bpm_from_bar`。 |

小节号 `mmm`：**若三位全是十进制数字则按十进制**，否则按**十六进制**解析（`_parse_measure_field`）。

### 3.2 音符行（`_emit_notes_and_slides`）

仅处理 **`#` 开头且含 `:`** 的行，且头部至少 3 个字符为小节号 `mmm`，其后 `rest` 由 **`_parse_channel_rest`** 分类：

| `rest` 模式 | 语义 | 后续 |
|-------------|------|------|
| `02` | 小节拍长 | 跳过（已在 `_collect_state` 处理） |
| `08` | BPM 引用 | 跳过 |
| `1` + 一字符 `x` | **Tap** 通道 `#mmm1x` | 见 §5.1 |
| `5` + 一字符 `x` | **Directional** `#mmm5x` | 见 §5.4 |
| `2` + 两字符 `xy` | **Hold** `#mmm2xy` | 见 §5.2 |
| `3` / `4` 开头 + `xy` | **Slide** `#mmm3xy` / `#mmm4xy` | 见 §5.3 |
| 其它 | `ignore` | **整行丢弃** |

数据部 `data_part` 必须 **长度为偶数**，按 **每 2 个字符一组** 切分；组内第 1 字符为「点类型/子类型」，第 2 字符为 **宽度编码**（与 kb10uy v2.7 一致）。

**单小节内时间**：该小节 SUS tick 长度 `sus_len = beats * ticks_per_beat`，`n_groups = len(data_part)//2`，第 `g` 组对应 SUS tick：

`group_tick(g) = bar_start_sus_tick(bar) + round(g * sus_len / n_groups)`  

即 **在该小节内均匀插值**，与「组在字符串中的顺序」一一对应。

---

## 4. 时间轴：SUS tick → c2s 全局 tick → 小节内 offset

### 4.1 常量

- **`CTS_RESOLUTION = 384`**：输出 c2s 使用的 tick 分辨率（与项目内对 PenguinTools/样本的约定一致）。
- SUS 侧每拍 tick：`st.ticks_per_beat`（多来自 `#REQUEST`，默认 480）。

### 4.2 全局 c2s tick

对任意 SUS tick `sus_tick`：

`global_c2s_tick = round(sus_tick * (384 / ticks_per_beat))`  

（`_sus_tick_to_c2s_global`）

### 4.3 写进谱面行的小节与 offset

c2s 事件里多数地面/天空键使用 **「小节号 + 小节内 tick」**，不是一直用全局 tick。实现用 **`_global_c2s_to_bar_offset(st, g)`**：

- 从第 0 小节起，用 **`_bar_length_c2s(st, b)`**（该小节 SUS 长度换算到 c2s）逐节减去，直到剩余 `g` 落在当前小节长度内；
- 返回 `(bar, offset)`，其中 `offset` 为该小节内 tick。

**注意**：若全局 tick 超出由 `max_measure` 推导的小节链，函数会**继续向后虚拟延伸小节**（每节默认 4 拍换算），可能与真实乐曲长度不一致。

---

## 5. 轨位与各类音符在 c2s 里怎么写

### 5.1 轨位映射（PJSK 12 轨 → 中二地面列）

函数 **`_pjsk_lane_to_chuni(lane_char, width_ch)`**：

- `lane_char` 在字母表 `_SUS_LANE_ALPHABET`（`0-9a-z`）中的下标为 `p`（0-based）。
- **左端列**：`chuni_left = p + 2`（即使用中二 16 列里中间 12 列，对应文档 `sus_to_c2s_note_mapping_zh.md` §1.5）。
- **宽度**：宽度字符同样映射到 1～35，再限制在 `chuni_left + width ≤ 14`，否则 **钳位 width** 并记入 `warnings`（当前 **warnings 未写入文件**，仅函数返回值）。

### 5.2 Tap → `TAP`

- **条件**：`#mmm1x` 数据组首字符非 `0`。
- **输出一行**（TAB 分隔列，以下为逻辑列）：

```text
TAP    <小节>    <小节内offset>    <lane>    <width>
```

- 排序键：`kind_pri = 2`（`_KP_TAP`），与 BPM/MET/其它键的相对顺序见 §6。

**未区分** SUS Tap 子类型 `1`～`6`：**全部写成同一种 `TAP`**（与映射表草案一致）。

### 5.3 Hold → `HLD`

- **通道**：`#mmm2xy`，用 `(x,y)` 两字符区分不同 hold 栈（`hold_open[(x,y)]`）。
- **数据字符**：
  - `1`：**起点**，压栈 `(global_tick, lane, width)`。
  - `2`：**终点**，弹栈，写一行 `HLD`，持续时间 `dur = max(1, end_tick - start_tick)`。
  - `3`：**中继**：**当前实现直接 `continue`，不产生任何 c2s 行**（即 **忽略中继折点**）。

**输出行格式**：

```text
HLD    <起小节>    <起小节内offset>    <lane>    <width>    <dur>
```

`dur` 为 **c2s 全局 tick 差**，不是小节内相减。

### 5.4 Slide → `SLC`（极简折线）

- **通道**：`#mmm3xy` 与 `#mmm4xy` **同一套逻辑**（`kind` 均为 `slide`）。
- 每个非 `0` 数据组在对应时间生成事件 `(global_tick, tch, lane, width, bar, offset)` 加入 `slide_events[(x,y)]`。
- 按时间排序后，再按点类型排序：`1` → `3` → `4` → `5` → `2`（`_s_ord`）。

**链规则**：

- `tch == "1"`：若已有未结束链，**告警并清空**，开始新链。
- `tch in ("3","4","5")`：**追加**到当前链（可见中继、贝塞尔控制、不可见中继 **在输出上等价于一个几何点**）。
- `tch == "2"`：**追加终点后立刻 `flush_chain()`**：对链上相邻两点各生成一段 `SLC`。

**`flush_chain` 条件**：链长度 **≥ 2** 才输出；对相邻两点 `(g0,…)` 与 `(g1,…)`：

```text
SLC    <m0>    <o0>    <l0>    <w0>    <dur>    <l1>    <w1>    SLD
```

其中 `dur = max(1, g1 - g0)`（全局 tick 差）。**没有**实现官方常见的复杂 `SLD` 链字段、也没有把贝塞尔抽成密集中间点；**本质是把一条 SUS slide 压成少量直线段**。

若链以 `1` 开头但 **从未遇到 `2` 收尾**，结束时 **告警 `slide chain missing end`**，且 **不输出**该链。

### 5.5 Directional → `AIR` / `ADW` / …

映射表 **`_DIRECTIONAL_TO_C2S`**：

| SUS 首字符 | c2s 类型 |
|------------|----------|
| `1` | `AIR` |
| `2` | `ADW` |
| `3` | `AUL` |
| `4` | `AUR` |
| `5` | `ADL` |
| `6` | `ADR` |

**输出行格式**（与当前代码完全一致）：

```text
<类型>    <小节>    <offset>    <lane>    <width>    TAP    DEF
```

即：**固定带 `TAP` 与 `DEF` 两列**（作为天空键附着/占位），是否与所有官谱样本一致 **未做全量验证**。

---

## 6. 排序：为何同一时刻事件顺序是这样

`_TimedLine` 为 `order=True` 的 dataclass，字段顺序为：

1. `sort_tick`（c2s 全局 tick，用于对齐时间）
2. `kind_pri`（**硬编码优先级**）
3. `tie`（递增整数，打破同 tick 同优先级的稳定顺序）
4. `text`

`kind_pri` 取值：

| 值 | 含义 |
|----|------|
| 0 | `BPM` |
| 1 | `MET` |
| 2 | `TAP` |
| 3 | `HLD` |
| 4 | `SLC` |
| 5 | `AIR` 系 |

因此 **同一全局时刻** 下顺序为：**BPM → MET → TAP → HLD → SLC → 天空**。这与官谱是否要求严格一致 **未证明**。

---

## 7. 文件头（固定模板 + 动态 BPM）

`convert_sus_to_c2s` 在事件行前写入**固定多行**（节选逻辑含义）：

- `VERSION    1.13.00    1.13.00`
- `MUSIC 0` / `SEQUENCEID 0` / `DIFFICULT 0` / `LEVEL 0.0`
- `CREATOR` ← 来自 SUS `#DESIGNER`，缺省为 `PJSK SUS import`
- **`BPM_DEF`**：四个字段 **相同**，均为 **`_main_bpm(st)`**（优先 `#BASEBPM`，否则第一个 `#BPMxx`，再否则 **120.0**），格式化为三位小数。
- **`MET_DEF    4    4`**（固定 4/4）
- **`RESOLUTION` / `CLK_DEF`** 均为 **384**
- `PROGJUDGE_*`、`TUTORIAL` 等为固定占位

**BPM 事件行**：

- 遍历 `st.bpm_from_bar` 的键并包含小节 `0`，对每个 `(bar, 0)` 在「该小节起点全局 tick」写：

```text
BPM    <bar>    0    <bpm三位小数>
```

`_bpm_value_at_bar` 按小节向前找**最近**的 `#mmm08` 引用键，再到 `bpm_defs` 取值；否则用 `_main_bpm`。

**去重**：`(bar, 0, round(bpm,3))` 已出现则跳过，避免重复 `BPM` 行。

**MET 事件**：**始终只写一行**：

```text
MET    0    0    4    4
```

**不处理** SUS 内拍号变化（若存在）。

---

## 8. 明确未实现或未读取的 SUS 内容

下列在 **当前 `sus_to_c2s.py` 中没有任何等价输出**（或仅被静默跳过）：

| 内容 | 结果 |
|------|------|
| `#TIL` / `#HISPEED` 等流速 | **忽略**；c2s **`SLP`** 时间线不会生成 |
| `#MEASUREBS` / `#MEASUREHS` 等 | **忽略** |
| `#ATR` / `#ATTRIBUTE` | **忽略** |
| Tap 子类型差异 | **全部合并为 `TAP`** |
| Hold 中继 `3` | **忽略** |
| Slide 的贝塞尔几何 | **不插值**；`3`/`4`/`5` 仅当折线顶点 |
| `FLK` / `CHR` / `SXC`/`SXD` / `ALD` / `ASC`/`ASD`/`AHD` 等 | **从不输出** |
| 多拍号 `MET` | **仅 4/4 一行** |
| `warnings` 列表 | **不写入 c2s**，调用方也未见持久化 |

---

## 9. 与文档 `sus_to_c2s_note_mapping_zh.md` 的关系

该文档描述的是 **目标映射与轨位约定**；**实际代码**在 Hold 中继、Slide 几何、事件排序等方面 **并未完全达到** 文档 §3.4 / §3.5 所暗示的精度。若以文档为「规格」，则 **实现落后于规格**。

---

## 10. 为何在实际使用中被认为「基本不可用」（工程向归纳）

1. **时间系统**：BPM 只按 `#mmm08` 小节边界切换 + 单一 `MET`，与复杂拍号/弱起 **不对齐** 时，整谱偏移常见。  
2. **Hold**：中继被丢弃，**长条形状与判定**与 PJSK/官机习惯不符。  
3. **Slide**：**直线段近似 + 链尾必须 `2`**，与 SUS 曲线及官谱 `SLC`/`SLD` 链 **差距大**，易出现断条、怪条。  
4. **流速**：无 `SLP`，**Hi-Speed 与显示**与目标环境不一致。  
5. **键型缺失**：无 `FLK` 等，PJSK 中映射到多种 Tap 的表现 **无法还原**。  
6. **验证不足**：输出未与 [PenguinTools](https://github.com/Foahh/PenguinTools) / 官方 c2s 做逐事件 diff 测试。

若需要 **可玩、可对齐官机** 的谱面，当前更稳妥的路径仍是：**社区成熟工具链**（如经 MRGC 等中间格式再出 c2s）或 **在编辑器内手工修谱**。

---

## 11. 维护者速查：关键符号在源码中的位置

| 主题 | 函数 / 常量 |
|------|-------------|
| 小节号解析 | `_parse_measure_field` |
| 状态收集 | `_collect_state` |
| SUS tick → 全局 c2s tick | `_sus_tick_to_c2s_global` |
| 全局 tick → 小节内 | `_global_c2s_to_bar_offset`, `_bar_length_c2s` |
| 通道分类 | `_parse_channel_rest` |
| 全部音符 | `_emit_notes_and_slides` |
| 拼接输出 | `convert_sus_to_c2s` |

---

*文档版本：与仓库 `sus_to_c2s.py` 行为同步描述；若代码变更，请同步修订本文 §5–§8。*
