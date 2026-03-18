# chuni eventer desktop（保姆级环境配置 & 首次启动）

这是一个 Python 桌面端工具（**PyQt6**），用于把你的自制资源按 **CHUNITHM A001** 的目录结构写入程序自带的 **`ACUS/` 工作区**，并提供“管理页”快速查看已存在的 XML 内容与 DDS 预览（依赖外部工具）。

---

## 功能概览

- **生成器**
  - 导入 3 张角色图片（大头/半身/全身）
  - 输入 **角色基ID** 与 **变体(0-9)**（自动计算最终角色 ID）
  - 一键生成：
    - `ACUS/ddsImage/ddsImage{ID6位}/DDSImage.xml`
    - `ACUS/ddsImage/ddsImage{ID6位}/CHU_UI_Character_{base4}_{variant2}_{00..02}.dds`（BC3/DXT5）
    - `ACUS/chara/chara{ID6位}/Chara.xml`
- **ACUS 管理**
  - 扫描 `ACUS/` 里现有 XML：`Event / Map / Music / Chara / DDSImage`
  - 支持搜索、查看字段
  - 尝试把 DDS 直接预览成图片（会缓存）

---

## 0. 你需要准备什么

- **macOS**
- **Python 3.12+**（建议）
- **DDS 转换工具（必需）**：推荐 `compressonatorcli`
  - 用于：
    - 图片 → **BC3(DXT5)** DDS（生成器）
    - DDS → PNG（管理页预览）

---

## 1. 环境配置（第一次只需要做一次）

### 1.1 安装 Python 依赖

在终端进入 `desktop/`：

```bash
cd "/Users/mac/code/chuni eventer/desktop"
python3 -m pip install -r requirements.txt
```

> 依赖清单见 `requirements.txt`（PyQt6、Pillow）。

### 1.2 安装 DDS 工具：Compressonator CLI（必需）

本项目**默认使用 `compressonatorcli`**。你用任意方式安装都可以，只要最终能拿到一个可执行文件路径即可（例如 `/usr/local/bin/compressonatorcli`）。

生成 DDS 的命令大致长这样：

```bash
compressonatorcli -fd BC3 input.png output.dds
```

#### 为什么不能“纯 Python 内置 BC3 压缩”？

- **BC3(DXT5) 是块压缩纹理格式**，编码器实现复杂且性能敏感。
- 纯 Python 实现/集成成熟编码器通常不现实（速度/依赖/授权/跨平台）。
- 所以当前方案是：**编码/预览都走外部工具**（稳定可控）。

---

## 2. 第一次启动（保姆级步骤）

### 2.1 启动程序

仍在 `desktop/` 目录执行：

```bash
python3 -m chuni_eventer_desktop
```

### 2.2 第一次启动会自动创建 ACUS 工作区

程序会在 `desktop/` 下自动创建：

```
desktop/ACUS/
  chara/
  ddsImage/
  event/
  map/
  mapArea/
  mapBonus/
  music/
  course/
  reward/
  cueFile/
  .cache/dds_preview/        # DDS 预览缓存（已被 .gitignore 忽略）
```

> 以后所有生成/管理都围绕这个 `ACUS/` 进行。

### 2.3 第一次使用必须做的配置：DDS 工具路径

打开程序 → **生成器** 页：

- 在 **DDS 工具** 一栏选择 `compressonatorcli` 可执行文件
- 程序会把路径保存到：`ACUS/.config.json`（不会提交到 git）

---

## 3. 生成一个角色（大头/半身/全身）

在 **生成器** 页按顺序填写：

1. **角色基ID**：例如 `2469`（= 最终角色ID // 10）
2. **变体**：例如 `0`（范围 0-9，= 最终角色ID % 10）
3. **最终角色ID**：自动显示为 `24690`（只读）
4. **角色名**：写入 `Chara.xml` 的 `name.str`
5. 选择三张图片：
   - **大头**（写入 ddsFile0）
   - **半身**（写入 ddsFile1）
   - **全身**（写入 ddsFile2）
6. 点击 **生成 DDS + XML（写入 ACUS）**

生成结果示例：

```
ACUS/
  chara/chara024690/Chara.xml
  ddsImage/ddsImage024690/DDSImage.xml
  ddsImage/ddsImage024690/CHU_UI_Character_2469_00_00.dds
  ddsImage/ddsImage024690/CHU_UI_Character_2469_00_01.dds
  ddsImage/ddsImage024690/CHU_UI_Character_2469_00_02.dds
```

---

## 4. 管理页怎么用（看 XML + 看图）

切到 **ACUS 管理** 页：

- 选择类型：`Event / Map / Music / Chara / DDSImage`
- 用搜索框输入 ID/名称/关键字过滤
- 点击表格某条记录：
  - 右侧显示字段详情
  - 如果能定位到 DDS（角色大头、曲绘等），会尝试生成预览图

> 预览会把 DDS 转成 PNG 缓存到 `ACUS/.cache/dds_preview/`。

---

## 5. 常见问题（排查）

### 5.1 “DDS 工具路径不存在”
- 说明你还没选到 `compressonatorcli`，或路径填错。

### 5.2 “预览失败 / 未配置 compressonatorcli”
- 预览同样依赖 `compressonatorcli`。
- 确认：
  - 工具路径已配置
  - 对应 `.dds` 文件确实存在于 `ACUS/` 目录里

### 5.3 “变体必须在 0-9”
- 这是这套 ID/命名规则约定的变体范围限制。

