# UGC → MGXC → c2s 管线设计说明

本文说明 [PenguinTools](https://github.com/Foahh/PenguinTools) 中与谱面相关的**真实代码结构**、**UGC / MGXC / c2s 三种形态的阅读方式与对应关系**，以及本仓库**计划中的「UGC 转 MGXC（再沿用现有 MGXC→c2s）」**逻辑与可行性理由。

> **本地样本说明**：当前工作区内的 `.cache/pgko_downloads` 目录下**未检出任何文件**，因此下文**无法**基于你机器上的具体 UGC/MGXC/c2s 做逐行或十六进制对比；待缓存目录有样本后，可将典型文件与本文结构描述逐项核对。

---

## 1. PenguinTools 的转谱逻辑（基于上游源码，而非 Issues）

### 1.1与 Issues 页的关系

[PenguinTools Issues](https://github.com/Foahh/PenguinTools/issues) 在公开页面上**没有可检索的讨论串**（当前为0 条 open issue）。**可复核的「转谱逻辑」应以仓库源码为准**，核心在 `PenguinTools.Core` 工程内。

### 1.2 总体数据流

上游采用**固定两阶段**：

1. **解析 MGXC** → 内存中的 `Models.mgxc.Chart`（元数据、事件树、音符树）。
2. **转换并写出 c2s** → 文本谱（`VERSION`、头字段、`BPM`/`MET`/`SFL`/`SLP` 等事件行 + 各类音符行）。

对应入口类（节选职责）：

| 阶段 | C# 类型 | 路径（main 分支） | 做什么 |
|------|---------|-------------------|--------|
| 读盘 | `MgxcParser` | `PenguinTools.Core/Chart/Parser/MgxcParser*.cs` | 校验 `MGXC` 头；顺序读 `meta`、`evnt`、`dat2` 块；`ProcessEvent` / `ProcessNote` / `ProcessTil` / `ProcessCommand` / `ProcessMeta` |
| 写出 | `C2SConverter` | `PenguinTools.Core/Chart/Converter/C2SConverter*.cs` | 对每条 mgxc 音符调用 `ConvertNote`；对整谱事件调用 `ConvertEvent`；固定写出 `RESOLUTION\t384` 等表头后追加事件行与音符行 |

`MgxcParser.ActionAsync` 的骨架（与二进制布局强相关）可概括为：

- 读4 字节 `"MGXC"`，跳过块大小等字段；
- `ReadBlock("meta", ParseMeta)`；
- `ReadBlock("evnt", ParseEvent)`；
- 建立 `TimeCalculator`（与 tick/拍号推进相关）；
- `ReadBlock("dat2", ParseNote)`；
- 再经多步 `Process*` 规范化事件与音符（例如补头拍号、ExTap 与其它 note 的 effect 合并等）。

`C2SConverter.ActionAsync` 的骨架可概括为：

- 以已解析的 `mg.Chart` 为**唯一输入**（**不包含 UGC 解析**）；
- 生成 c2s 头（`VERSION`、`CREATOR`、`BPM_DEF`、`MET_DEF`、`RESOLUTION`、`CLK_DEF` 等）；
- 遍历 `Events` / `Notes` 输出 `.Text` 行。

**结论**：在 Foahh/PenguinTools **当前公开代码树中，不存在独立的「UGC 文件解析器」**；社区若谈「用 PenguinTools 转谱」，通常指 **已有 MGXC（或由其它工具先得到 MGXC）→ c2s**。

### 1.3 `mgxc -> c2s` 的实现细化（可直接借鉴）

从 `C2SConverter.cs`（以及同目录 `C2SConverter.Event.cs`、`C2SConverter.Note.cs`）看，流程可进一步拆成 5 步：

1. **时间计算器绑定**  
   `Diagnostic.TimeCalculator = Mgxc.GetCalculator()`，后续所有事件/音符都在同一时间换算上下文内转换。

2. **先音符、后事件地转换到 c2s 模型**  
   - `foreach (var note in Mgxc.Notes.Children) ConvertNote(note);`  
   - `ConvertEvent(Mgxc);`  
   说明 `ConvertNote/ConvertEvent` 是明确分层的语义映射入口，而不是文本层拼接。

3. **写出前做 Post Validation（关键）**  
   包括但不限于：  
   - `Slide` 终点与 `Air` 依附关系检查（重叠计数）  
   - LongNote 长度最小单位检查  
   - 必要时报告 warning（不一定阻断输出）

4. **可选整体偏移（BarOffset）**  
   `Mgxc.Meta.BgmEnableBarOffset` 打开时，把所有非 0 tick 事件和音符整体平移一个小节长度，这解释了为什么同谱在不同元数据选项下 c2s 时间戳会整体偏移。

5. **固定头 + 事件段 + 音符段串行写出**  
   固定写出：`VERSION` / `CREATOR` / `BPM_DEF` / `MET_DEF` / `RESOLUTION=384` / `CLK_DEF=384` 等，然后输出事件文本，再输出音符文本。

这 5 步的工程意义是：**把「语义映射、合法性检查、文本序列化」三层明确分开**。对我们做 UGC 方案非常有价值，因为 UGC 的不确定性集中在“语义映射层”，而 c2s 写出层可以保持稳定复用。

---

## 2. 三种文件「怎么读」与相互关系

### 2.1 MGXC（二进制、块结构）

**阅读方式**：按块解析的二进制格式，本仓库与上游一致：

- 文件头：`MGXC`（4 字节）。
- 典型块：`meta`（曲名、作者、音频文件名、预览、`dsgn`/`arts`/`titl`/`wvfn`/`wvp0`/`wvp1` 等）、`evnt`（`bpm `、`beat`、`smod`、`til ` 等四字符事件名 + 类型化字段）、`dat2`（紧密排列的 note 记录：`type`、`long_attr`、`direction`、`ex_attr`、轨位 `x`、宽 `width`、`height`、tick、`timeline` 等）。

**语义角色**：可视为 **MA3 / 自定义工具链内部的「结构化谱面中间表示」**，与 PenguinTools 的 `mgxc` 模型一一对应；**现有 MGXC→c2s 已全部围绕此表示实现**（Python 见 `chuni_eventer_desktop/pgko_to_c2s.py::_parse_mgxc`，C# 见 `MgxcParser`）。

**与 c2s 的对应**：**时间轴从 MGXC 的 tick（工程内约定 480）缩放到 c2s 的 384**（本仓库 `scale = 384/480`）；事件与音符类型映射见 `docs/pgko_mgxc_conversion_tech.md` 与 `docs/pgko_mgxc_conversion_1to1_mapping.md`。

### 2.2 c2s（文本、CHUNITHM 谱面）

**阅读方式**：UTF-8 文本；固定表头 + 多行事件 + 空行 + 多行音符。

- 表头：`VERSION`、`MUSIC`、`CREATOR`、`BPM_DEF`、`MET_DEF`、`RESOLUTION`（PenguinTools 写出为 **384**）、`CLK_DEF` 等。
- 正文：`BPM`/`MET`/`SFL`/`SLP`/… 与 `TAP`/`HLD`/`SLD`/`AIR`/… 等，具体字段顺序由 `c2s` 模型决定。

**语义角色**：**面向 CHUNITHM 客户端/编辑器的终端谱面格式**；本仓库的 `c2s_emit` 是其子集实现，并与 PenguinTools 的 `Models.c2s` 对齐思路（见映射表文档）。

### 2.3 UGC（文本、编辑器导出）

**阅读方式**：**按行文本**；编码在工程里按 **UTF-8 优先，失败则 cp932** 尝试（`_read_ugc_text`）。

本仓库**已实际使用**的指令（与谱面元数据/资源相关，**不是完整谱面本体**）：

- `@DESIGN\t...`：制谱者名字（用于 c2s `CREATOR` 等展示链路的补强）。
- `@JACKET`（大小写不敏感）后接封面文件名：与同目录资源联动（`docs/pgko_mgxc_conversion_tech.md` 与 `pgko_to_c2s.py` 中 `_try_read_ugc_jacket_filename_near`）。

**完整谱面在 UGC 中的形态**：一般为 **以 `@` 开头的命令 + 参数** 的序列（具体指令集与 MA3 系编辑器/导出工具一致）。**当前代码未解析 UGC 中的音符与 BPM 等事件**；仅在有同目录 **MGXC** 时，通过 `_find_fallback_mgxc` **借道二进制**完成转 c2s。

**三者的关系（概念层）**：

| 形态 | 载体 | 与另两者的关系 |
|------|------|------------------|
| UGC | 文本 | 与 MGXC **同源不同壳**：面向编辑/分发；谱面语义应能落到与 `dat2`/`evnt` 等价的对象集合 |
| MGXC | 二进制 | **PenguinTools 与当前 Python 管线的共同输入**；是 UGC 与 c2s 之间的**桥梁格式** |
| c2s | 文本 | **终端交付格式**；由 MGXC 语义经缩放与类型映射得到 |

---

## 3. 本仓库现状：UGC 为何不「直转 c2s」

`convert_pgko_chart_pick_to_c2s_with_backend`（`pgko_to_c2s.py`）中：

- 若 pick 为 `ugc`，则 **必须** `_find_fallback_mgxc` 成功，否则 `NotImplementedError`（明确提示「暂不支持 ugc 直转」）。
- 成功时实际转码路径与直接选 MGXC 相同：优先 **PenguinBridge**（C# `mgxc-to-c2s`），失败则 **Python `_parse_mgxc` + `c2s_emit`**。

因此：**「UGC → c2s」在工程上被刻意拆成「找 MGXC」+「已有 MGXC→c2s」**；缺口集中在 **仅有 UGC、无 MGXC** 的包。

---

## 4. 计划实现：UGC → MGXC（再 c2s）

### 4.1 目标

让用户 **不必再手动用外部工具把 UGC 转成 MGXC**：在下载目录仅含 `.ugc`（及音频/封面等）时，仍能走完 **UGC → MGXC → c2s**（后半段复用现有逻辑）。

### 4.2 建议的代码结构（与现有模块对齐）

1. **新增 UGC 解析层**（例如 `ugc_parser.py` 或与 `pgko_to_c2s.py` 同文件的 `_parse_ugc`）  
   - 输入：`Path` →输出：与 `_parse_mgxc` **同构**的中间结构：`_MgxcMeta`、`_MgxcEvent` 列表、`_MgxcNote` 列表（**或**直接输出 `mgxc.Chart` 等价物）。  
   - 指令覆盖范围按优先级：**BPM/拍号/流速类事件** → **Tap/Hold/Slide/Air/…**（与 `dat2` 类型码一致）。

2. **新增 MGXC 序列化层**（`_emit_mgxc`）  
   - 将上述结构按 `MGXC` + `meta` + `evnt` + `dat2` 的**已知布局**写回临时或同名 `.mgxc`文件。  
   - 字段编码需与 `_parse_mgxc` / `MgxcParser` **读写对称**（类型0/1/2/3/4的字段、`evnt` 里四字符 tag、`dat2` 里每条 note 的字节序与长度）。

3. **接入现有转码入口**  
   - `convert_pgko_chart_pick_to_c2s_with_backend`：当 `pick.ext == "ugc"` 且 `_find_fallback_mgxc` 为 `None` 时，调用 **UGC→MGXC**，将 `source_path` 切换为生成的 `mgxc`，再走 **现有** Bridge / Python 路径。  
   - `pick_pgko_chart_for_convert` 可保持 `mgxc > ugc`；仅在「无 mgxc」时依赖新逻辑。

4. **验证策略**  
   - 用**同曲同难度**下并存的一对 `foo.ugc` + `foo.mgxc`（用户本地或 pgko 包）：UGC 解析结果与 `_parse_mgxc(foo.mgxc)` **diff 事件/音符列表**（允许顺序经排序后比较）。  
   - 再比较输出的 c2s 与「直接用原 MGXC 转」的差异是否在可接受范围。

### 4.3 为什么认为「可以这么转」

1. **上游能力边界清晰**  
   PenguinTools **只认 MGXC**，说明在其设计里 **MGXC 已承载转 c2s 所需的全部谱面语义**；UGC 作为编辑器导出，**目的就是把同一套语义交给游戏/工具链**，否则不会与 MGXX 生态并存。

2. **本仓库已有可逆参考实现**  
   `_parse_mgxc` 已把 `meta`/`evnt`/`dat2` 拆成结构化数据；**若 UGC 指令能映射到同一套 `_MgxcEvent`/`_MgxcNote`**，则 **写回 MGXC 本质上是该解析过程的逆操作**（在布局已知的前提下是工程问题，而非未知格式问题）。

3. **复用已验证的 MGXC→c2s**  
   避免在 Python 里维护两套「UGC→c2s」与「MGXC→c2s」映射；**单一真相来源**仍是 MGXC 语义层，降低与 PenguinTools / PenguinBridge 行为漂移的风险。

4. **与当前产品行为一致**  
   已有 `_read_ugc_*` 证明 UGC **在同一目录生态内与 MGXC 配对使用**；补齐「无 MGXC」分支只是**把用户手工步骤自动化**。

### 4.4 风险与已知难点（需在实现中逐项消化）

- **UGC 指令全集**：若 pgko/编辑器导出含未文档化指令，需要**以样本驱动**补解析表。  
- **ExTap effect、Slide 曲线、Air 高度/多段**：MGXC 内已有字段，但 UGC 侧命令参数是否与之一一对应，需对照样本。  
- **与 C# `ProcessNote` 等后处理的一致性**：若生成 MGXC 后走 PenguinBridge，需保证写出文件能通过 `MgxcParser` 的校验（例如**首 tick BPM**、**首小节拍号**等；Python 路径已在 `convert_pgko_chart_pick_to_c2s_with_backend` 对部分情况做了默认补全）。

### 4.5 以 `Ver seX` 三文件为例：我会怎么转、为什么可行

示例路径（你指定）：

- `@.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.ugc`
- `@.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.mgxc`
- `@.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.c2s`

#### A. 当前已有 `Ver seX.mgxc` 时（最稳路径）

1. 读取 `Ver seX.mgxc`：解析 `meta/evnt/dat2` 为结构化对象。  
2. 走 `mgxc -> c2s`：优先 PenguinBridge（C#），失败回退 Python。  
3. 写出 `Ver seX.c2s`。  

**为什么可行**：这是现有仓库已跑通的主链路，输入与上游工具能力边界完全一致（都以 MGXC 为主输入）。

#### B. 只有 `Ver seX.ugc`，没有 `Ver seX.mgxc` 时（本次目标）

我会做成「两段式自动化」：

1. **UGC 解析到中间语义对象**  
   - 从 `Ver seX.ugc` 提取 meta（如设计者、封面名等）  
   - 解析 BPM/拍号/流速命令到事件对象  
   - 解析 Tap/Hold/Slide/Air 等到 note 对象  
   - 输出与 `_parse_mgxc` 同构的数据结构（`_MgxcMeta/_MgxcEvent/_MgxcNote`）

2. **中间语义对象写回 `Ver seX.mgxc`**  
   - 按 `MGXC + meta + evnt + dat2` 块布局落盘  
   - 字段按小端和已知类型编码写入

3. **复用现有 MGXC->c2s**  
   - 把新生成的 `Ver seX.mgxc` 直接喂给现有转换入口  
   - 得到 `Ver seX.c2s`

**为什么可行**：

- `mgxc->c2s` 在上游/本仓库都已经稳定；  
- 我们已有 `_parse_mgxc`，证明 MGXC 字段语义和字节布局可被稳定读取；  
- 因此只要 UGC 能映射到同构语义对象，就能通过“写 MGXC”接入成熟后半段，避免重复造一套 UGC->c2s 文本拼接器。

#### C. 有 `Ver seX.ugc` + `Ver seX.mgxc` + `Ver seX.c2s` 三者并存时（验证路径）

用于验证转换正确性，我会做三组对比：

1. **UGC 解析结果 vs MGXC 解析结果**  
   比较事件序列（BPM/beat/smod/til）与 note 序列（类型、tick、lane、width、方向、timeline）。  

2. **由 MGXC 直接转出的 c2s vs 由 UGC 先转 MGXC 再转出的 c2s**  
   核对头字段、事件行数量、关键 note 行（Tap/Hold/Slide/Air）时序。  

3. **若已有现成 `Ver seX.c2s`**  
   将它作为第三方基准，只接受“可解释差异”（如排序差异、可选偏移、保留位差异），不接受语义差异（漏 note、错拍、错 lane）。

这样可以把问题定位到具体层次：是 UGC 解析错、MGXC 序列化错，还是 c2s 映射差异。

---

## 5. 语句级转换对照（你要的“实际互相转化逻辑”）

这一节只讲“语句怎么互转”，不讲文件选择优先级。

> 说明：由于当前工作区没有 `.cache/pgko_downloads` 实样，UGC 音符语句示例先用“**语法示意**”写法；`MGXC` 字段与 `c2s` 目标行是按现有代码与上游模型可确认的真实映射。

### 5.1 中间层定义（必须落地）

为了让 `UGC -> MGXC -> c2s` 可验证，先把 UGC 每条语句都转换到统一中间层（与当前代码同构）：

| 中间层对象 | 字段 | 含义 | 进入 MGXC 的位置 |
|---|---|---|---|
| `_MgxcMeta` | `designer/artist/title/song_id/bgm_file/wvp0/wvp1/difficulty/cnst` | 曲目元信息 | `meta` 块（`dsgn/arts/titl/sgid/wvfn/wvp0/wvp1/diff/cnst`） |
| `_MgxcEvent` | `kind` + `tick` + `value/value2` | 事件语义 | `evnt` 块（`bpm ` / `beat` / `smod` / `til `） |
| `_MgxcNote` | `typ,long_attr,direction,ex_attr,x,width,height,tick,timeline,seq` | 音符语义 | `dat2` 块 |

只要 UGC 每条语句能稳定映射到上面三类对象，就能：

1. 写出合法 `MGXC`；  
2. 直接复用已稳定的 `mgxc -> c2s`。

### 5.2 元数据语句：UGC -> MGXC -> c2s

| UGC 语句（示例） | 中间层 | MGXC 落盘 | c2s 体现 |
|---|---|---|---|
| `@DESIGN\tAlice` | `_MgxcMeta.designer = "Alice"` | `meta:dsgn="Alice"` | `CREATOR\tAlice`（若 UGC 未给值，再回退 meta.designer/meta.artist） |
| `@JACKET\tversex.jpg` | `jacket_filename="versex.jpg"`（资源侧字段） | 不强制入谱面 note/event | 不直接进 c2s；用于封面资源生成链路 |
| （示意）`@TITLE\tVer seX` | `_MgxcMeta.title="Ver seX"` | `meta:titl="Ver seX"` | 不直接写成 c2s 行，但影响外部元数据生成 |
| （示意）`@ARTIST\tComposer` | `_MgxcMeta.artist="Composer"` | `meta:arts="Composer"` | 间接作为 creator 兜底来源 |

### 5.3 事件语句：UGC -> MGXC -> c2s

| UGC 语句（语法示意） | 中间层对象 | MGXC 事件 | c2s 行 |
|---|---|---|---|
| `@BPM <tick> <bpm>` | `_MgxcEvent(kind="bpm", tick=t, value=bpm)` | `evnt:bpm ` | `BPM\t<measure>\t<tick>\t<bpm>` |
| `@BEAT <bar> <num>/<den>` | `_MgxcEvent(kind="beat", tick=bar, value=num, value2=den)` | `evnt:beat` | `MET\t<measure>\t<tick>\t<den>\t<num>` |
| `@SMOD <tick> <speed>` | `_MgxcEvent(kind="smod", tick=t, value=speed)` | `evnt:smod` | `SFL` 段（过滤 speed=1.0） |
| `@TIL <timeline> <tick> <speed>` | `_MgxcEvent(kind="til", tick=t, value=speed, value2=timeline)` | `evnt:til ` | `SLP` 段（按 timeline 分组） |

操作逻辑（事件）：

1. UGC 事件语句先入 `_MgxcEvent`；  
2. 写 `evnt` 块时按 tag 编码；  
3. 转 c2s 时执行 `scale = 384/480`，得到 `measure/tick` 后输出事件行。

### 5.4 音符语句：UGC -> MGXC -> c2s（核心）

| UGC 语句（语法示意） | 中间层 `_MgxcNote` | MGXC `dat2` | c2s 输出 |
|---|---|---|---|
| `@TAP t lane width` | `typ=0x01` | 单条 note | `TAP` |
| `@EXTAP t lane width dir` | `typ=0x02,direction=dir` | 单条 note | `CHR`（`direction -> effect`） |
| `@FLICK t lane width dir` | `typ=0x03,direction=dir` | 单条 note | `FLK`（左右方向） |
| `@DAMAGE t lane width` | `typ=0x04` | 单条 note | `MNE` |
| `@HOLD_BEGIN ...` / `@HOLD_END ...` | `typ=0x05,long_attr=0x01/0x05` | 两条配对 note | `HLD(length=end-start)` |
| `@SLIDE_BEGIN/JOIN/END ...` | `typ=0x06,long_attr=0x01/0x02..0x06` | 多条链式 note | `SLD/SLC`（分段） |
| `@AIR t lane width dir` | `typ=0x07,direction=dir` | 单条 note | `AIR/AUL/AUR/ADL/ADR/ADW`（含 linkage） |
| `@AHS_BEGIN/.../END` | `typ=0x08 or 0x09` | 链式 note | `AHD` 分段 |
| `@ACR_BEGIN/.../END` | `typ=0x0A` | 链式 note | 近似 `AHD` 分段 |

操作逻辑（音符）：

1. UGC 音符语句 -> `_MgxcNote`；  
2. 写 `dat2` 时保留 `tick/timeline/seq`；  
3. 转 c2s 时按类型分支：
   - 单点类直接落 `measure/tick/lane/width`；  
   - 长音类按 begin/end 或链节点计算 `length`；  
   - `AIR` 额外做 `direction` 映射和 `linkage` 推断（关联地面 `TAP/HLD/SLD`）。

### 5.5 `Ver seX` 路径下的实操模板

以你指定路径为例：

- `@.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.ugc`
- `@.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.mgxc`
- `@.cache/pgko_downloads/Ver seX/Ver seX/Ver seX.c2s`

#### 步骤 1：读 `Ver seX.ugc`，逐行产出中间层

例如读取到（示意）：

- `@DESIGN\tAlice`
- `@BPM 0 200.0`
- `@BEAT 0 4/4`
- `@TAP 960 6 1`
- `@HOLD_BEGIN 1440 5 1`
- `@HOLD_END 1920 5 1`

对应中间层：

- `_MgxcMeta(designer="Alice", ...)`
- `_MgxcEvent("bpm", tick=0, value=200.0)`
- `_MgxcEvent("beat", tick=0, value=4, value2=4)`
- `_MgxcNote(typ=0x01, tick=960, x=6, width=1, ...)`
- `_MgxcNote(typ=0x05, long_attr=0x01, tick=1440, x=5, width=1, ...)`
- `_MgxcNote(typ=0x05, long_attr=0x05, tick=1920, x=5, width=1, ...)`

#### 步骤 2：把中间层写成 `Ver seX.mgxc`

- meta 写 `dsgn=Alice`；  
- evnt 写 `bpm `/`beat`；  
- dat2 写三条 note（tap + hold begin/end）。

#### 步骤 3：`Ver seX.mgxc -> Ver seX.c2s`

按 `384/480` 缩放后示意：

- `bpm tick=0` -> `BPM\t0\t0\t200.000`
- `beat bar=0 4/4` -> `MET ... 4 4`
- `tap tick=960` -> `TAP` 在 `measure=1,tick=0`
- `hold 1440->1920` -> `HLD length=384`

### 5.6 为什么这种“语句 -> 中间层 -> 两端文件”是必须的

- UGC 是行语句协议，MGXC 是二进制块协议，c2s 是行文本协议；三者语法完全不同。  
- 直接做 `UGC -> c2s` 文本拼接，无法复用现有 `mgxc->c2s` 的后处理与校验。  
- 中间层把“语句解释”与“文件格式编码”分离，才能做到可对比、可单测、可定位错误。

---

## 6. 参考链接

- [Foahh/PenguinTools](https://github.com/Foahh/PenguinTools) — 源码中 `MgxcParser`、`C2SConverter`。  
- [PenguinTools Issues](https://github.com/Foahh/PenguinTools/issues) — 当前无公开 issue 可供引用；技术细节以代码为准。  
- 本仓库：`docs/pgko_mgxc_conversion_tech.md`、`docs/pgko_mgxc_conversion_1to1_mapping.md`、`chuni_eventer_desktop/pgko_to_c2s.py`。

---

*文档版本：与 2026-04-14 仓库状态对齐；若 `.cache/pgko_downloads` 后续加入样本，建议在本节追加「典型文件片段示例」与「指令对照表」。*
