<!-- markdownlint-disable MD032 MD012 -->

# mgxc -> c2s（PenguinTools）源码解析与本仓库桥接说明

本文目标：
- 详细解释 `Foahh/PenguinTools` 中 `mgxc -> c2s` 的真实实现链路。
- 说明本仓库如何“抄实现思路 + 改入口”构建 `exe`，供 Python 调用。

参考源码（上游）：
- `PenguinTools.Core/Chart/Parser/MgxcParser*.cs`
- `PenguinTools.Core/Chart/Converter/C2SConverter*.cs`
- `PenguinTools.Core/Chart/Models/c2s/*.cs`
- `PenguinTools.Core/Chart/Models/mgxc/*.cs`

---

## 1. 总体架构

上游链路是三段式：
1) `MgxcParser`：二进制 `mgxc` 解析为内存模型 `mg.Chart`
2) `C2SConverter`：把 `mg.Chart` 转成 `c2s` 节点（事件 + 音符）
3) 序列化：把 `c2s` 节点写成文本 `.c2s`

关键点：上游不是“边读边写”，而是“先建完整语义模型，再统一转换 + 校验 + 输出”。

---

## 2. Parser 层（MgxcParser）

### 2.1 入口流程（`MgxcParser.ActionAsync`）

入口顺序（简化）：
- 校验文件头 `MGXC`
- 读取并分块：
  - `meta` -> `ParseMeta`
  - `evnt` -> `ParseEvent`
  - `dat2` -> `ParseNote`
- 执行后处理：
  - `ProcessEvent`
  - `ProcessNote`
  - `ProcessTil`
  - `ProcessCommand`
  - `ProcessMeta`

这一步的结果是完整 `mg.Chart`，后续 Converter 不再关心二进制细节。

### 2.2 Event 处理

`ProcessEvent` 的核心职责：
- 确保头 BPM 事件存在且在 tick=0（否则直接报错）
- 确保头拍号存在（没有则补 `4/4` 在 bar=0）
- 根据 bar + 拍号计算每个拍号事件的绝对 tick
- 提取初始 `BgmInitialBpm/BgmInitialNumerator/BgmInitialDenominator`

这意味着后续 `MET_DEF`、音频偏移修正都依赖这里的标准化结果。

### 2.3 Note 处理

`ProcessNote` 会做“语义补全”而非仅透传：
- 收集同 tick 的 ExTap effect
- 把 ExTap 的 effect 覆盖到被覆盖音符上
- 删除无意义重叠 ExTap（避免重复语义）
- 冲突 effect 给出诊断信息

这一步是 “mgxc 的编辑器语义 -> 游戏可用语义” 的关键。

---

## 3. Converter 层（C2SConverter）

### 3.1 入口（`C2SConverter.ActionAsync`）

执行顺序：
1) `ConvertNote`：遍历 mg note，按类型分发
2) `ConvertEvent`：生成 BPM/MET/DCM/SLP
3) Post Validation：
   - Air parent / Slide 终点一致性检查
   - 长条最小长度检查
4) 若 `BgmEnableBarOffset`：统一平移事件与音符 tick
5) 按 c2s 文本格式写出

### 3.2 Event 映射

`ConvertEvent` 规则：
- BPM -> `BPM`
- Beat -> `MET`
- `smod` -> `DCM`（注意，不是 SFL）
- `til`（按 timeline 分组）-> `SLP`

长度逻辑：
- 区间长度使用“当前事件 tick 到下一事件 tick”
- 最后一个事件延长到“最后音符 tick（至少 1 tick）”
- `speed == 1` 的 DCM/SLP 会被过滤

### 3.3 Note 映射

主要映射（上游）：
- Tap -> `TAP`
- ExTap -> `CHR`
- Flick -> `FLK`
- Damage -> `MNE`
- Hold -> `HLD/LXD` 风格（按 effect）
- Slide -> `SLD/SCD` 风格（首段携带 effect）
- Air -> `AIR/AUL/AUR/ADW/ADL/ADR`（带 parent）
- AirSlide -> `ASC/ASD`（带 parent + 高度）
- AirCrash -> `ALD`（带密度 + 高度）

注意：Air / AirSlide 不是独立落点，依赖 parent pairing（地面键或 slide 尾段）。

### 3.4 输出格式细节

上游 `c2s` 写出特点：
- Header 固定 `VERSION/MUSIC/SEQUENCEID/...`
- `MET_DEF` 使用 `BgmInitialDenominator\tBgmInitialNumerator`
- 仅输出：Header + Events + Notes
- 不输出本仓库旧实现中的 `T_REC_* / T_NOTE_*` 统计页脚

---

## 4. 本仓库桥接 exe 设计

文件：`tools/PenguinBridge/Program.cs`

设计目标：
- 让 Python 只调用一个稳定命令：
  - `PenguinBridge.exe mgxc-to-c2s --in xxx.mgxc --out yyy.c2s`
- 与上游解耦：通过反射加载 `PenguinTools.Core.dll`
- 避免编译期绑定导致的版本耦合

关键实现点：
- 显式等待 `ActionAsync`（`Task.GetAwaiter().GetResult()`）
  - 防止“未解析完就取结果”造成空谱/损坏输出
- 反射注入 `AssetManager`
  - 用空 JSON（`{}`）初始化，满足 `MgxcParser.Assets` 必需依赖
- 运行时加载策略：
  - `CHUNI_PENGUIN_TOOLS_CORE_DLL`
  - 或与 exe 同目录的 `PenguinTools.Core.dll`

---

## 5. Python 调用约定

推荐最小调用：

```python
import subprocess
from pathlib import Path

bridge = Path("tools/PenguinBridge/bin/Release/net8.0/PenguinBridge.exe")
inp = Path(r"E:\foo\chart.mgxc")
out = inp.with_suffix(".c2s")

p = subprocess.run(
    [str(bridge), "mgxc-to-c2s", "--in", str(inp), "--out", str(out)],
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
if p.returncode != 0:
    raise RuntimeError(f"bridge failed\nstdout={p.stdout}\nstderr={p.stderr}")
```

若 `PenguinTools.Core.dll` 不在 exe 同目录，则先设置环境变量：

```powershell
$env:CHUNI_PENGUIN_TOOLS_CORE_DLL = "D:\path\to\PenguinTools.Core.dll"
```

---

## 6. 当前限制与建议

- 该桥接 exe 本身可独立编译，但运行时仍依赖 `PenguinTools.Core.dll` 及其间接依赖。
- 如果你的网络环境拉不到上游 submodule，建议：
  - 在可联网机器先构建 `PenguinTools.Core`，复制运行时依赖到本机。
  - 或维护一套已知可用的 `Core + deps` 二进制包供本项目直接加载。

---

## 7. 结论

本仓库采用“上游核心逻辑由 `PenguinTools.Core` 提供，本地只保留桥接入口”的方案，优点是：
- 转谱语义与上游一致
- Python 调用接口稳定
- 后续跟随上游升级时只需替换 Core 二进制，桥接层改动很小

