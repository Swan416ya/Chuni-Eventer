# PenguinTools 图片转 DDS 实现解析

本文基于 `Foahh/PenguinTools` 公开源码，说明它“图片转 DDS”是怎么实现的，以及哪些环节在主仓库里、哪些在外部工具里。

---

## 1. 结论先说

`PenguinTools` 主仓库**没有直接实现 DDS 压缩算法**（例如 BC3/DXT5 的逐块编码）。  
它采用的是“**核心业务层调用外部媒体工具**”架构：

1. C# 代码做参数校验、流程控制、错误汇总
2. 通过 `Manipulate` 统一调用外部命令 `mua`
3. `mua` 负责真正的图片检查/转换

所以“图片转 DDS”的真正编码细节在 `mua`（`muautils`）里，不在 `PenguinTools` 主仓库。

---

## 2. 主仓库里的调用链

### 2.1 入口：Jacket 转换器

`JacketConverter` 只做两件事：

- 检查输入文件是否存在
- 调 `Manipulate.ConvertJacketAsync(InPath, OutPath)`

对应源码：

- `PenguinTools.Core/Media/JacketConverter.cs`

### 2.2 命令封装：Manipulate

`Manipulate` 统一封装了外部命令调用，关键方法：

- `ConvertJacketAsync(src, dst)` -> 执行  
  `mua convert_jacket -s <src> -d <dst>`
- `CheckImageValidAsync(src)` -> 执行  
  `mua image_check -s <src>`

对应源码：

- `PenguinTools.Core/Media/Manipulate.cs`

也就是说：PenguinTools 的“图片转 DDS”在业务层面是**命令转发**，不是库内编码。

### 2.3 Stage 相关也走同一路径

`StageConverter` 会调用：

- `mua convert_stage -b <bg> -s <st_dummy.afb> -d <st_out.afb> ...`

这条主要是“背景图 + 特效图 -> Stage AFB”的流程，不是直接输出 DDS，但同样说明媒体处理在 `mua`。

对应源码：

- `PenguinTools.Core/Media/StageConverter.cs`

---

## 3. 为什么判断“编码实现不在主仓库”

有三条证据：

1. 主仓库只看到命令调用（`convert_jacket` / `image_check` / `convert_stage`），未见 BCn 编码实现类
2. `.gitmodules` 明确声明了外部子模块 `External/muautils`
3. `Manipulate` 默认执行程序名是 `mua`，说明依赖外部可执行工具

对应文件：

- `.gitmodules`
- `PenguinTools.Core/Media/Manipulate.cs`

---

## 4. 对我们项目的可参考点

虽然它没有公开主仓库内的 DDS 算法代码，但其架构很值得参考：

1. **流程分层清晰**：UI/ViewModel -> Converter -> Manipulate(Command Runner)
2. **前置校验**：先 `image_check` 再转换，错误更可读
3. **统一错误模型**：命令 stdout/stderr + exit code 归一化为诊断对象
4. **功能拆分明确**：`convert_jacket`（封面）、`convert_stage`（场景）各走专用命令

这套思路和我们当前 `dds_convert.py`（Pillow/quicktex/compressonator 多后端 fallback）可以结合：

- 我们保留内置多后端 fallback
- 同时可引入“统一命令包装层 + 统一诊断对象”增强可维护性

---

## 5. 当前能确认与不能确认的边界

### 能确认

- PenguinTools 通过 `mua convert_jacket` 完成图片到目标贴图的转换流程
- 主仓库负责 orchestrate（编排）与错误处理

### 不能从主仓库直接确认

- `convert_jacket` 内部是否固定输出 BC3/DXT5（大概率是，但主仓库代码未显示）
- 缩放规则、mipmap 规则、alpha 预乘策略、颜色空间处理细节

这些要去 `muautils` 的实现源码或其文档确认。

---

## 6. 参考链接

- PenguinTools 仓库：<https://github.com/Foahh/PenguinTools>
- Manipulate（命令封装）：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Media/Manipulate.cs>
- JacketConverter：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Media/JacketConverter.cs>
- StageConverter：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Media/StageConverter.cs>
- StageXml：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/PenguinTools.Core/Xml/StageXml.cs>
- .gitmodules（外部依赖）：<https://raw.githubusercontent.com/Foahh/PenguinTools/main/.gitmodules>
- 中文 Wiki：<https://raw.githubusercontent.com/wiki/Foahh/PenguinTools/%E4%B8%AD%E6%96%87.md>

