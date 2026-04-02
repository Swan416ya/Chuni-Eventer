# PGKO 转码技术解析（当前实现）

## 目标与优先级

当前内置转码目标是把 pgko 下载产物转换为 CHUNITHM `c2s`，并遵循：

- 优先使用 `mgxc`
- 若没有 `mgxc`，再尝试 `ugc`（通过同目录/邻近 `mgxc` 回退）

不再把 `mrgc` 作为当前实现目标。

## 入口与流程

核心入口在 `chuni_eventer_desktop/pgko_to_c2s.py`：

- `pick_pgko_chart_for_convert(download_output)`
  - 在下载目录内选择转码源，优先级：`mgxc > ugc`
- `convert_pgko_chart_pick_to_c2s(pick)`
  - 执行转码并输出 `.c2s`

UI 入口在 `chuni_eventer_desktop/ui/pgko_sheet_download_dialog.py`：

- 下载成功后弹窗询问是否转码
- 调用 `pick_pgko_chart_for_convert` + `convert_pgko_chart_pick_to_c2s`
- 成功时展示输出文件路径，失败时弹出详细错误

## 文件选择策略

当 `pick.ext != "mgxc"` 时，会执行 `_find_fallback_mgxc(source)`：

1. 同名同目录：`source.with_suffix(".mgxc")`
2. 同目录任意 `*.mgxc`
3. 上一级目录递归查找同 stem `*.mgxc`

若仍找不到，则抛出 `NotImplementedError`，并带上：

- 源文件路径
- 同目录可见的 `mgxc/ugc` 文件列表

## mgxc 解析实现

`_parse_mgxc(path)` 直接读取二进制块结构：

- 头校验：`MGXC`
- 事件块：`evnt`
- 音符块：`dat2`

解析字段：

- 事件：`bpm`（用于 `BPM` 定义）
- 音符：`type/long_attr/direction/ex_attr/x/width/height/tick`
- 记录原始顺序 `seq`，避免同 tick 错序导致配对偏差

## c2s 映射规则（当前）

时基缩放：

- `mgxc tick(480)` -> `c2s tick(384)`，比例 `384 / 480`

已支持映射：

- `Tap/ExTap/Flick` -> `TAP`（当前统一落成 `TapNote`）
- `Hold begin/end` -> `HLD`
- `Slide begin/joints/end` -> `SLD/SLC`
- `Air` -> `AIR/AUR/AUL/ADW/ADR/ADL`
- `AirHold/AirSlide` -> 分段 `AHD`
- `AirCrush` -> 近似分段 `AHD`（保节奏与路径连续）

## Air linkage（父类型推断）

为避免空中 note 全部固定挂 `TAP`，实现了两段式推断：

1. 先扫描地面 note，构建 `ground_anchors`（`TAP/HLD/SLD`）
2. 为空中 note 选择 linkage：
   - 优先同 tick 且覆盖
   - 再选最近历史覆盖
   - 再选最近历史任意 anchor
   - 最后兜底 `TAP`

这使输出中的 `AIR` 能出现 `TAP/HLD/SLD` 混合链接，更接近真实谱面关系。

## 已知限制

当前是“可用优先”的内置实现，仍有差距：

- `ExTap/Flick/Damage` 尚未细分到完整 c2s 标签体系（目前以基础可播为主）
- `AirSlide/AirCrush` 的高度、密度等高级语义受当前 `c2s_emit` 能力限制，采用近似映射
- `ugc` 目前不是直接解析，而是“借道 mgxc 回退”

## 调试与验证建议

建议最小回归流程：

1. 下载 pgko 包并自动解压
2. 点“转码”
3. 检查输出 `.c2s` 是否生成
4. 抽样检查：
   - `BPM` 行是否存在
   - `HLD/SLD/SLC/AIR/AHD` 是否出现
   - `AIR` linkage 是否不再单一 `TAP`

## 后续可扩展方向

- 直接解析 `ugc`（不依赖旁路 `mgxc`）
- 补齐 `ExTap/Flick/Damage` 等更精细语义映射
- 升级 `c2s_emit` 以承载更多 Air 相关高级参数
