# PenguinTools 图片转 Stage AFB 实现解析

本文专门解释 `Foahh/PenguinTools` 里“图片转 Stage 的 `afb`”是怎么做的（即 `st_*.afb` 生成流程），不讨论图片转 DDS 封面链路。

---

## 1. 一句话结论

`PenguinTools` 的 Stage 背景转换核心不是在 `StageConverter` 里直接写编码算法，而是调用外部命令：

- `mua convert_stage -b <背景图> -s <st模板.afb> -d <输出st.afb> [-f1..-f4 特效图]`

也就是说，真正“把图片烘进 stage afb”的底层实现由 `mua`（`muautils`）负责，`PenguinTools.Core` 负责编排流程和错误处理。

---

## 2. 调用链（从 UI 到 afb）

### 2.1 UI 输入

`StageViewModel` 收集参数：

- `BackgroundPath`：背景图
- `EffectPath0..3`：可选特效图
- `StageId`
- `NoteFieldsLine`

然后构造 `StageConverter` 并执行。

对应：

- `PenguinTools/ViewModels/StageViewModel.cs`

### 2.2 业务编排

`StageConverter.ActionAsync()` 的关键动作：

1. 构建 `StageXml(stageId, noteFieldLine)`，先生成 Stage 元数据
2. 计算输出目录并准备文件名：
   - `NotesFieldFile`（`nf_custom_stage_{id}.afb`）
   - `BaseFile`（`st_custom_stage_{id}.afb`）
3. 调用：
   - `Manipulate.ConvertStageAsync(BackgroundPath, st_dummy.afb, st_out.afb, EffectPaths, ct)`
4. 复制：
   - `nf_dummy.afb` -> 目标 `nf_*.afb`

对应：

- `PenguinTools.Core/Media/StageConverter.cs`

### 2.3 命令层封装

`Manipulate.ConvertStageAsync(...)` 组装参数后执行：

- `mua convert_stage`
- `-b` 背景图
- `-s` 输入模板 `st`（dummy）
- `-d` 输出 `st`（生成结果）
- 可选 `-f1`~`-f4` 特效图

对应：

- `PenguinTools.Core/Media/Manipulate.cs`

---

## 3. 关键文件与作用

1. `st_dummy.afb`
   - 作为 stage 模板输入（骨架）
   - 在 PenguinTools 资源目录中提供
2. `nf_dummy.afb`
   - 作为 notes field 模板直接复制
3. `Stage.xml`
   - 引用上述输出文件名（`notesFieldFile/baseFile`）

对应资源位置（PenguinTools 仓库）：

- `PenguinTools/Resources/st_dummy.afb`
- `PenguinTools/Resources/nf_dummy.afb`

---

## 4. 校验逻辑

在执行转换前，`StageConverter.ValidateAsync()` 会做：

- Stage ID 是否设置
- 背景图是否存在
- 背景图是否通过 `mua image_check`
- 每个特效图是否存在且通过 `image_check`
- 若目标 stage id 已存在，给 warning

这保证了进入 `convert_stage` 时参数和输入素材是可用的。

---

## 5. 与“图片转 DDS”的区别（避免再混）

- `convert_jacket`：图片 -> DDS（封面）
- `convert_stage`：图片(+fx) -> `st_*.afb`（背景演出资源）

两者都走 `mua`，但目标产物和用途不同。

---

## 6. 对我们仓库实现的直接启示

你当前项目里“图片转 Stage”只做到：

- 生成 `Stage.xml`
- 生成 `CHU_UI_Stage_*.dds` 预览图

**还没做**：

- `st_*.afb` 的真实生成（即上面 `convert_stage` 这条）
- `nf_*.afb` 模板复制链路

要补齐成 PenguinTools 同等级链路，需要新增：

1. 一个 `convert_stage` 执行器（外部工具调用层）
2. 一个资源模板来源（`st_dummy.afb` / `nf_dummy.afb`）
3. Stage 创建流程中“先转 afb，再写 Stage.xml”的顺序控制

---

## 7. 参考链接

- PenguinTools 仓库：<https://github.com/Foahh/PenguinTools>
- StageConverter：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Media/StageConverter.cs>
- Manipulate：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Media/Manipulate.cs>
- StageViewModel：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools/ViewModels/StageViewModel.cs>
- StageXml：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Xml/StageXml.cs>
- 中文 Wiki：<https://raw.githubusercontent.com/wiki/Foahh/PenguinTools/%E4%B8%AD%E6%96%87.md>

