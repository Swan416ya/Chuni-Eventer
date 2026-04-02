<!-- markdownlint-disable MD012 MD060 -->

# PGKO MGXC 转码 1:1 对照表

本文给出当前 Python 内置实现与 PenguinTools（C#）的逐项映射关系，便于后续精确补齐。

参考项目：`[Foahh/PenguinTools](https://github.com/Foahh/PenguinTools)`

---

## 总览


| PenguinTools（C#）                                          | Python（当前仓库）                                                           | 当前状态                       |
| --------------------------------------------------------- | ---------------------------------------------------------------------- | -------------------------- |
| `PenguinTools.Core/Chart/Parser/MgxcParser.cs`            | `chuni_eventer_desktop/pgko_to_c2s.py::_parse_mgxc`                    | 已有核心块解析（MGXC/evnt/dat2）    |
| `PenguinTools.Core/Chart/Parser/MgxcParser.Event.cs`      | `chuni_eventer_desktop/pgko_to_c2s.py::_parse_mgxc`（event 部分）          | 已解析 bpm/beat/smod；til 暂跳过 |
| `PenguinTools.Core/Chart/Parser/MgxcParser.Note.cs`       | `chuni_eventer_desktop/pgko_to_c2s.py`（note 扫描+映射）                     | 已覆盖主要类型；配对为近似实现            |
| `PenguinTools.Core/Chart/Converter/C2SConverter.cs`       | `chuni_eventer_desktop/pgko_to_c2s.py::convert_pgko_chart_pick_to_c2s` | 已实现“可用优先”转换总流程             |
| `PenguinTools.Core/Chart/Converter/C2SConverter.Event.cs` | `pgko_to_c2s.py`（BPM/MET/SFL/SLP 写出）                                    | 已有 BPM/MET/SFL/SLP（可用对齐） |
| `PenguinTools.Core/Chart/Converter/C2SConverter.Note.cs`  | `pgko_to_c2s.py`（Tap/Hold/Slide/Air/AHD）                               | 已有基本落地；高级语义未全齐             |
| `PenguinTools.Core/Chart/Models/c2s/*.cs`                 | `chuni_eventer_desktop/_suspect/c2s_emit.py`                           | 能力子集，不含完整 C# 模型字段          |


---

## 解析层 1:1

### 1) MGXC 主入口


| C#                                  | Python                                           | 对照说明                                              |
| ----------------------------------- | ------------------------------------------------ | ------------------------------------------------- |
| `MgxcParser.ActionAsync`            | `convert_pgko_chart_pick_to_c2s` + `_parse_mgxc` | C# 分阶段执行（Parse->Process->Convert），Python 合并为单文件流程 |
| `ReadBlock(HeaderMeta, ParseMeta)`  | 未完整实现 meta 解析                                    | Python 当前不依赖 meta 参与输出                            |
| `ReadBlock(HeaderEvnt, ParseEvent)` | `_parse_mgxc` 中 `hdr == b"evnt"`                 | 已实现块读取与事件循环                                       |
| `ReadBlock(HeaderDat2, ParseNote)`  | `_parse_mgxc` 中 `hdr == b"dat2"`                 | 已实现 note 结构读取                                     |


### 2) Event 解析


| C# `MgxcParser.Event`          | Python 对应                                | 状态        |
| ------------------------------ | ---------------------------------------- | --------- |
| `name == "bpm "` -> `BpmEvent` | 读取 `tick/bpm` 到 `_MgxcEvent(kind="bpm")` | 已对齐       |
| `name == "beat"`               | 读取 bar/num/den 并转为拍号事件                      | 已对齐（写出 MET） |
| `name == "smod"`               | 读取 tick/speed 并转为速度事件                      | 已对齐（写出 SFL） |
| `name == "til "`               | 读取 timeline/tick/speed 并转为滚速事件              | 已对齐（写出 SLP） |
| `name == "bmrk"/"mbkm"/"rimg"` | 跳过字段，保持流对齐                               | 已实现“安全跳过” |


### 3) Note 解析字段


| C# 字段         | Python 字段（`_MgxcNote`） | 状态                        |
| ------------- | ---------------------- | ------------------------- |
| `type`        | `typ`                  | 已对齐                       |
| `longAttr`    | `long_attr`            | 已对齐                       |
| `direction`   | `direction`            | 已对齐                       |
| `exAttr`      | `ex_attr`              | 已对齐（暂少用）                  |
| `variationId` | 读取后丢弃                  | 部分                        |
| `x`           | `x`                    | 已对齐                       |
| `width`       | `width`                | 已对齐                       |
| `height`      | `height`               | 已对齐（AHD 近似使用）             |
| `tick`        | `tick`                 | 已对齐                       |
| `timelineId`  | 读取后丢弃                  | 部分                        |
| 输入顺序          | `seq`                  | Python 额外补充，用于同 tick 稳定排序 |


---

## 转换层 1:1

### 4) 总转换入口


| C# `C2SConverter.ActionAsync`      | Python `convert_pgko_chart_pick_to_c2s` | 差异                  |
| ---------------------------------- | --------------------------------------- | ------------------- |
| `ConvertNote()` + `ConvertEvent()` | 单函数内按 note/event 分支生成输出                 | Python 更轻量，缺少完整后验校验 |
| `Post Validation`                  | 无专门后验模块                                 | 可后续补                |
| `WriteAllTextAsync(OutPath)`       | `out.write_text(...)`                   | 等价                  |


### 5) 事件到 c2s


| C#                     | Python                            | 状态  |
| ---------------------- | --------------------------------- | --- |
| `BpmEvent -> c2s.Bpm`  | `_MgxcEvent("bpm") -> BpmSetting` | 已对齐 |
| `BeatEvent -> c2s.Met` | `beat(bar,num,den) -> MeterSetting` | 已实现（含头拍号兜底） |
| `smod -> DCM`          | `smod -> SpeedSetting(SFL)`        | 近似实现 |
| `til -> SLP`           | `til(timeline,tick,speed) -> TimelineSpeedSetting` | 已实现 |


### 6) Note 到 c2s（核心）


| C# 分支 (`C2SConverter.Note.cs`) | Python 对应逻辑                             | 当前结果                  |
| ------------------------------ | --------------------------------------- | --------------------- |
| `mg.Tap -> c2s.Tap`            | `typ==0x01 -> TapNote`                  | 已实现 |
| `mg.ExTap -> c2s.ExTap`        | `typ==0x02 -> ChargeNote(CHR+effect)`   | 已实现（方向到 effect 映射） |
| `mg.Flick -> c2s.Flick`        | `typ==0x03 -> FlickNote(FLK+L/R)`       | 已实现（方向映射） |
| `mg.Hold -> c2s.Hold`          | `typ==0x05 begin/end 配对 -> HoldNote`    | 已实现                   |
| `mg.Slide -> c2s.Slide`        | `typ==0x06 chain -> SlideNote(SLD/SLC)` | 已实现（曲线按 long_attr 近似） |
| `mg.Air -> c2s.Air`            | `typ==0x07 -> AirNote`                  | 已实现（方向映射完成）           |
| `mg.AirSlide -> c2s.AirSlide`  | `typ in (0x08,0x09) -> 分段 AirHold(AHD)` | 近似实现                  |
| `mg.AirCrash -> c2s.AirCrash`  | `typ==0x0A -> 分段 AirHold(AHD)`          | 近似实现                  |
| `mg.Damage -> c2s.Damage`      | `typ==0x04 -> MineNote(MNE)`              | 近似实现 |
| Pairing（正负 note 互配）            | Ground Anchor + 就近覆盖推断 linkage          | 近似实现（可用）              |


---

## 选择与回退层 1:1（项目定制）

这部分是 Python 项目特有策略，不是 PenguinTools 原生结构。


| Python 函数                        | 作用                     | 现状              |
| -------------------------------- | ---------------------- | --------------- |
| `pick_pgko_chart_for_convert`    | 下载目录内选择源谱面             | 已按 `mgxc > ugc` |
| `_find_fallback_mgxc`            | `ugc` 场景自动旁路到可用 `mgxc` | 已实现             |
| `convert_pgko_chart_pick_to_c2s` | 回退后统一走 mgxc 管线         | 已实现             |
| `convert_pgko_audio_to_chuni_from_pick` | 复用 pjsk 音频管线转 ACB/AWB，并读取 `wvp0/wvp1` 预览片段 | 已实现 |


---

## c2s 输出模型能力对照


| C# 模型（PenguinTools）          | Python `c2s_emit`                                      | 结论     |
| ---------------------------- | ------------------------------------------------------ | ------ |
| `Tap/Flick/ExTap/Damage` 细粒度 | `TapNote/FlickNote/ChargeNote/MineNote` 可表达，但当前转换未全部使用 | 可继续补齐  |
| `Slide` 完整字段                 | `SlideNote`（`SLD/SLC`）                                 | 已可用    |
| `Air` 带 parent/color         | `AirNote`（`linkage` + 默认 `DEF`）                        | 基本可用   |
| `AirSlide/AirCrash` 高度/密度/颜色 | `AirHold` 子集能力                                         | 当前只能近似 |
| `MET/DCM/SLP`                | `MeterSetting/SpeedSetting` 有类定义，但当前转换未输出              | 可继续补   |


---

## 建议的“继续 1:1 补齐”顺序

1. 事件层：把 `smod -> SFL` 再校准到更接近 C# DCM 语义  
2. Air 层：扩展 `c2s_emit` 后补更高保真 `AirSlide/AirCrash` 字段  
3. 事件层：进一步校准 `smod` 与 C# DCM 的长度策略  
4. Air 层：若扩展 `c2s_emit`，再做 `AirSlide/AirCrash` 高保真字段输出

---

## 附：你当前实现的定位

- 与 PenguinTools 思路一致：二进制解析 -> 语义映射 -> c2s 输出  
- 但工程策略不同：你这边优先“内置可用、零外部依赖”，因此采用了部分近似映射  
- 在 pgko 下载链路中已经形成闭环，可直接用于日常导入流程

