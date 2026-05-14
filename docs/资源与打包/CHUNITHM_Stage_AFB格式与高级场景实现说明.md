# CHUNITHM Stage 用 AFB：格式要点、DDS 嵌入方式与「高级场景」实现路径

本文整理 **Stage 相关的 `*.afb`** 在公开工具链（[PenguinTools](https://github.com/Foahh/PenguinTools) + [muautils / `mua`](https://github.com/Foahh/muautils)）中的**可操作语义**，说明 **DDS 在 AFB 内如何被定位与替换**，并对比 **「单图生成 st」** 与 **「游戏内复杂 stage（如 `stage026801`）」** 的差距，供 Chuni-Eventer 后续实现参考。

> **范围说明**：下文关于二进制分块的描述，严格对应 `muautils` 当前开源实现；完整 AFB 是否为某一封包规范的全貌，需以逆向或官方资料为准，本文不声称覆盖全部字段语义。

---

## 1. 术语与文件角色

| 文件 | 在 `Stage.xml` 中 | 常见用途（工具链语境） |
|------|-------------------|------------------------|
| `st_*.afb` | `baseFile/path` | 背景与演出相关贴图等资源的主容器 |
| `nf_*.afb` | `notesFieldFile/path` | 谱面判定区域（Notes Field）相关资源 |
| `CHU_UI_Stage_*.dds` | `image/path`（可选） | UI 列表/预览用缩略图；**不是** `st_*.afb` 的必需组成部分 |

**Stage.xml** 中还会见到 `objectFile/path` 等扩展字段；复杂演出可能依赖 **多资源联合**，不单靠 `st_*.afb`。

与本仓库相关的已有归纳：

- [PenguinTools图片转StageAFB实现解析.md](./PenguinTools图片转StageAFB实现解析.md)
- [PenguinTools图片转DDS实现解析.md](./PenguinTools图片转DDS实现解析.md)
- [stage 创建和管理实现方案](../活动与玩法机制/stage创建和管理实现方案.md)

---

## 2. PenguinTools 中的两条 AFB 相关路径

### 2.1 AFB → 多张 DDS（提取）

- **入口类**：`PenguinTools.Media.AfbExtractor` — 校验输入路径后调用 `IMediaTool.ExtractDdsAsync`。
- **默认实现**：`PenguinTools.Infrastructure.MuaMediaTool` 执行命令：

  ```text
  mua extract_dds -s <afb 路径> -d <输出目录>
  ```

源码参考（主仓库）：

- `PenguinTools.Media/AfbExtractor.cs`
- `PenguinTools.Infrastructure/MuaMediaTool.cs` 中 `ExtractDdsAsync`

**结论**：AFB 内「按块拆 DDS」的算法**不在** PenguinTools 主仓库，而在 **`mua`（muautils）**。

### 2.2 图片 → `st_*.afb`（生成）

- **编排**：`PenguinTools.Media.StageConverter` — 生成/保存 Stage 目录与 `Stage.xml`，调用 `ConvertStageAsync`，并将 `nf_dummy.afb` 复制为目标 `nf_*.afb`。
- **底层命令**：

  ```text
  mua convert_stage -b <背景图> -s <st 模板.afb> -d <输出 st.afb> [-f1..-f4 特效图]
  ```

**结论**：**「写 st_*.afb」** 同样是 **`mua`** 完成二进制层替换；PenguinTools 负责参数、校验与文件布局。

---

## 3. `mua` 如何定位 AFB 内的 DDS 子块

实现位置：`muautils` 的 `src/image/detail/chunk.cpp`、`src/image/image.cpp`。

### 3.1 分块标记

| 标记 | 字节（示意） | 作用（在本实现中） |
|------|----------------|-------------------|
| DDS 起始 | `DDS ` | 标准 DDS 魔数；每个内嵌 DDS 子 blob 从此开始 |
| 区间边界辅助 | `POF0` | 与「下一个 `DDS `」配合，用于计算当前块的结束位置 |

核心逻辑：`LocateDdsChunks` 内部调用 `LocateChunks(data, header=DDS\0, footer=POF0)`：

1. 扫描数据中所有 `DDS ` 出现位置；
2. 扫描所有 `POF0` 出现位置；
3. 对每个 `DDS ` 起点，在不超过「下一个 `DDS `」」的前提下，确定结束位置（与最近的合适 `POF0` 等相关逻辑配合，见源码 `LocateChunks`）。

### 3.2 提取到磁盘

`Image::ExtractDds(srcPath, dstFolder)`：

- 若未找到任何 DDS 块，抛出 **「No DDS chunks found」**；
- 否则在 `dstFolder` 下写出：`<afb 主文件名>_0001.dds`、`_0002.dds`、…（序号从 1 递增）。

**要点**：在此模型下，**AFB 被当作「二进制容器 + 多段内嵌 DDS」**；**非 DDS 区域**可能包含引擎私有数据，`mua` **不解析**其语义。

### 3.3 关于 `POF0`

文档层面可记为：**与 DDS 交错出现的四字节模式，被当前 `muautils` 用作子资源边界判断的一部分**。是否为某通用封包格式的正式字段名，需结合更全的逆向资料；**实现工具时不应假设**「仅有 DDS 与 POF0」即等于完整 AFB 规范。

---

## 4. `convert_stage` 如何把 DDS 写回 `st_*.afb`

实现位置：`src/image/image.cpp` 的 `Image::ConvertStage`，配合 `chunk.cpp` 的 `ReplaceChunks`、`dds.cpp` 的编码函数。

### 4.1 流程摘要

1. 异步读取模板 `st_模板.afb` 的完整字节；
2. `LocateDdsChunks` 得到模板中 **按顺序** 的 DDS 块列表；
3. 并行准备替换用字节流：
   - **背景**：`ConvertBackground` — 输入图缩放到 **1920×1080**，编码为 **BC1（DXT1）** 的 legacy DDS；
   - **特效合成**：`ConvertEffect` — 最多 4 张图，各 **256×256**（空槽用透明块），拼成 **2×2** 得到 **512×512**，编码为 **BC3（DXT5）**；
4. `ReplaceChunks`：用上述新 DDS **按槽顺序替换**原文件中的对应字节区间；若新 DDS 与旧块 **长度不同**，会重算输出文件总长度（**变长替换**）。

### 4.2 与「模板」的绑定关系

- **不是**从零生成规范完整的 AFB；
- **是**在 **给定模板**（如 `st_dummy.afb` 或从游戏里取的 `st_00011.afb`）上，**覆写前若干个 DDS 槽**（具体槽位数与顺序由模板决定）。

因此：**模板里有多少个 `DDS ` 槽，理论上就对应多少张可独立替换的贴图**；而 `convert_stage` **当前只生成两类新 DDS**（一张全屏背景 BC1 + 一张 512×512 特效 BC3），与模板前若干 chunk 对齐。

### 4.3 与 Chuni-Eventer 当前实现的对应

`chuni_eventer_desktop/stage_afb_convert.py` 调用 `convert_stage` 时 **`fx_paths=None`**，即 **未使用 `-f1..-f4`**，等价于只用背景相关路径、不用四格特效拼板（具体仍取决于模板第二槽是否被空白 DDS 填满，以实测为准）。

---

## 5. 「原生复杂 Stage」与工具链能力的差距

### 5.1 能确定的部分

- 对 **`st_26801.afb`** 这类资源运行 **`mua extract_dds`**，可列出 **内嵌 DDS 的数量与导出文件**，用于建立「贴图层」清单（分辨率、BC 格式可用 DDS 头解析）。
- **`convert_stage`** 解决的是 **「在已知模板上替换有限贴图槽」**，适合 **UGC 简化背景** 或 **基于 dummy 的自定义**。

### 5.2 不能仅从 `mua` 推出的部分（「小部件运动」）

屏幕上 **平移 / 旋转 / 缩放 / 显隐 / 时间轴** 等：

- **可能**写在 AFB **非 DDS** 区段；
- **可能**在 **`objectFile`** 或其它资源中；
- **可能**依赖引擎 shader / 脚本与硬编码逻辑。

**结论**：**仅替换或增删 DDS**，往往只能改 **「皮」**；**「骨」**（运动与编排）需要 **单独调研数据所在层**，不能假设与 PenguinTools 的 `convert_stage` 同一套模型。

---

## 6. 若要实现「接近原生」的高级 Stage：建议工作分解

### 6.1 调研（优先）

1. 对目标 **`st_*.afb`**（及同目录 **`nf_*.afb`**）执行 **`mua extract_dds`**，归档各 `_000N.dds` 的尺寸与格式（BC1/BC3 等）。
2. 对比 **简单模板**（`st_dummy`、`st_00011`）与 **高复杂度 stage** 的：DDS 个数、各块大小、`POF0` 分布模式、非 DDS 区域占比。
3. 阅读 **`Stage.xml`**：`objectFile` 等是否非空；在游戏资源树中 **追踪引用文件**。

### 6.2 工具链能力矩阵

| 能力 | `mua` 现状 | 产品侧含义 |
|------|------------|------------|
| AFB → DDS | `extract_dds` | 可做「导入官方 stage → 预览/导出贴图层」 |
| 指定槽写回 DDS | `ReplaceChunks` 思路 | 需保证 **格式与尺寸** 与引擎期望一致，并 **全量游戏内验证** |
| 变长 DDS | 支持调整总长度 | 可能破坏 AFB 内其它偏移敏感数据，**必须**对比修改前后行为 |
| 多槽自定义 | `convert_stage` 仅注入 2 类新图 | 要么 **扩展 muautils**，要么 **自研替换器** 并承担兼容成本 |
| 动画 / 运动 | 不在上述 API 语义内 | 需 **独立逆向或社区规范** |

### 6.3 分阶段产品建议

- **阶段 A（低风险）**：封装 **`extract_dds`** — 只读、预览、导出图层，供创作参考。
- **阶段 B（中风险）**：在 **固定官方模板** 上做多槽 **贴图替换**（严格锁定模板版本与 BC 格式）。
- **阶段 C（高风险）**：复现 **时间轴类演出** — 依赖 6.1 的调研结论，再决定是否投入 AFB 二进制逆向或外挂脚本方案。

---

## 7. 命令速查

```text
# 从 AFB 导出内嵌 DDS 到目录
mua extract_dds -s <输入.afb> -d <输出目录>

# 背景图 + 可选最多 4 张特效图 → 基于模板写出新 st.afb
mua convert_stage -b <背景图> -s <st 模板.afb> -d <输出 st.afb> [-f1 <图1>] [-f2 <图2>] [-f3 <图3>] [-f4 <图4>]
```

（CLI 子命令定义见 `muautils` 的 `src/cli/app.cpp`。）

---

## 8. 参考链接

| 说明 | URL |
|------|-----|
| PenguinTools（编排、资源、免责声明） | https://github.com/Foahh/PenguinTools |
| muautils / `mua`（`extract_dds`、`convert_stage`、chunk/dds 实现） | https://github.com/Foahh/muautils |
| PenguinTools 子模块声明（含 muautils 路径） | https://github.com/Foahh/PenguinTools/blob/main/.gitmodules |

---

## 9. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-05-14 | 初版：整合 AFB/DDS 分块规则、`convert_stage` 行为、与高级 stage 差距及实现阶段建议。 |
