# chuni eventer desktop（保姆级环境配置 & 首次启动）

这是一个 Python 桌面端工具（**PyQt6**），用于把你的自制资源按 **CHUNITHM A001** 的目录结构写入程序自带的 **`ACUS/` 工作区**，并提供“管理页”快速查看已存在的 XML 内容与 DDS 预览。

**DDS 预览与 BC3 生成**：默认随依赖安装 **quicktex**（纯 Python 包，内置 C++ 编码器），**可以不装 compressonator**。仍可在【设置】里配置 `compressonatorcli` 作为备选或对照。

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
- **quicktex（随 requirements 安装，推荐）**：BC3(DXT5) 的解码/编码
- **compressonatorcli（可选）**：若 quicktex 解码失败（如个别 DDS 变体）或未安装 quicktex 时作为回退

---

## 1. 环境配置（第一次只需要做一次）

### 1.1 安装 Python 依赖

在终端进入 `desktop/`：

```bash
cd "/Users/mac/code/chuni eventer/desktop"
python3 -m pip install -r requirements.txt
```

> 依赖清单见 `requirements.txt`（PyQt6、Pillow、**quicktex**）。

### 1.2（可选）安装 Compressonator CLI

**不装也可以**：已安装 `quicktex` 时，角色/名牌等 **BC3 生成** 与管理页 **DDS 预览** 会优先走 quicktex。

若你希望与官方工具链完全一致，或 quicktex 无法解码某种 DDS，可再安装 `compressonatorcli`，并在【设置】里填写路径。命令示例：

```bash
compressonatorcli -fd BC3 input.png output.dds
```

#### quicktex 在 macOS 上的说明

官方文档建议 macOS 用户安装 OpenMP 以提升多线程性能（非必须）：

```bash
brew install libomp
```

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

### 2.3（可选）配置 compressonatorcli 路径

若已 `pip install -r requirements.txt`（含 quicktex），**可直接使用新增角色/预览等功能**，不必配置此项。

需要时：左下角 **【设置】** → 选择 `compressonatorcli` 可执行文件 → 保存到 `ACUS/.config.json`（不会提交到 git）。

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

### 5.1 “DDS 工具路径不存在 / 路径无效”
- 仅在使用 **compressonatorcli 回退** 时需要有效路径；若已安装 **quicktex**，可不必配置。

### 5.2 “预览失败”
- 默认用 **quicktex** 解码；失败时会自动尝试 **compressonatorcli**（若已配置）。
- 确认对应 `.dds` 文件存在于 `ACUS/` 内。
- **DX10 头等特殊 DDS**：quicktex 当前不支持，可改配 compressonator 尝试转换。

### 5.3 “变体必须在 0-9”
- 这是这套 ID/命名规则约定的变体范围限制。

### 5.4 `pip install quicktex` 失败
- 查看 PyPI 是否提供你当前 Python 版本与系统的 wheel；必要时升级 pip，或使用与项目一致的 Python 3.12。

---

## 6. 本地测试运行（开发自测）

下面这套命令可作为每次改完代码后的最小自测流程。

### 6.1 启动前检查

```bash
cd "/Users/mac/code/chuni eventer/desktop"
python3 -m pip install -r requirements.txt
python3 -m compileall chuni_eventer_desktop
```

- `compileall` 通过，说明至少没有语法错误。

### 6.2 直接运行（开发模式）

```bash
cd "/Users/mac/code/chuni eventer/desktop"
python3 -m chuni_eventer_desktop
```

建议手动走一遍：

- 左侧切换：`角色 / 地图 / 宣传event / 歌曲 / 称号 / 名牌`
- 设置页配置 `compressonatorcli`
- 新增一个角色（3 图）
- 新增一个称号（可不选图）
- 新增一个名牌（1 图）
- 地图里添加格子奖励并保存
- 管理页查看列表和预览是否正常

### 6.3 可选：快速清理缓存再测

```bash
cd "/Users/mac/code/chuni eventer/desktop"
rm -rf "ACUS/.cache/dds_preview"
```

---

## 7. Windows 打包为 EXE（PyInstaller）

> 建议在 **Windows 本机** 打包 Windows `exe`。  
> 不建议在 macOS 直接交叉打包 Windows 可执行文件。

### 7.1 准备 Windows 环境

1. 安装 Python 3.12+（勾选“Add Python to PATH”）。
2. 打开 PowerShell，进入项目目录：

```powershell
cd "D:\path\to\chuni eventer\desktop"
python -m pip install -r requirements.txt
python -m pip install pyinstaller
```

### 7.2 执行打包

```powershell
cd "D:\path\to\chuni eventer\desktop"
pyinstaller --noconfirm --clean --windowed --name "Chuni-Eventer" -m chuni_eventer_desktop
```

打包结果：

- `dist/Chuni-Eventer/Chuni-Eventer.exe`

### 7.3 使用项目内 spec（一键稳定打包，推荐）

本项目已提供：`Chuni-Eventer.spec`  
建议优先用它，参数更稳定，后续加图标/版本信息也更方便。

```powershell
cd "D:\path\to\chuni eventer\desktop"
pyinstaller --noconfirm --clean ".\Chuni-Eventer.spec"
```

产物同样在：

- `dist/Chuni-Eventer/Chuni-Eventer.exe`

### 7.4 可选：设置 EXE 图标

1. 在 `desktop/assets/` 下放入 `icon.ico`
2. 重新执行 spec 打包命令

> `spec` 已自动检测 `assets/icon.ico`，存在就会应用，不存在则忽略。

### 7.5 首次运行 EXE 注意

- 首次启动会在 EXE 同级目录创建 `ACUS/`。
- 仍需在“设置”里配置 `compressonatorcli` 路径。
- `compressonatorcli.exe` 可以单独放在任意目录，只要路径可选中即可。

---

## 8. 发行建议（给别人用）

建议把以下内容一起打包发给使用者：

- `dist/Chuni-Eventer/` 整个目录
- 一份 `compressonatorcli.exe`（或安装说明）
- 这份 `README.md`

可选做法：

- 你可以再加一个批处理 `run.bat`，内容仅一行：

```bat
Chuni-Eventer.exe
```

