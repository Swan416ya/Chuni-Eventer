# chuni eventer desktop（保姆级环境配置 & 首次启动）

这是一个 Python 桌面端工具（**PyQt6**），用于把你的自制资源按 **CHUNITHM A001** 的目录结构写入程序自带的 **`ACUS/` 工作区**，并提供“管理页”快速查看已存在的 XML 内容与 DDS 预览。

**界面**：主窗口使用 [QFluentWidgets](https://qfluentwidgets.com/zh/pages/about)（PyPI：`PyQt6-Fluent-Widgets`）的 Fluent Design 组件。该库对 **非商用** Python 项目采用 **GPLv3**；若你分发本程序的二进制或完整源码，需遵守 GPLv3（用户须能获得对应源代码等）。商用需自行向作者购买商业授权，详见 [QFluentWidgets 简介](https://qfluentwidgets.com/zh/pages/about)。

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
  - 扫描 `ACUS/` 里现有 XML：`Event / Map / Music / Chara / …`
  - **Event** 支持地图解禁 / 宣传(含 DDS) 等分类标注与筛选
  - 支持搜索、查看字段、DDS 预览（会缓存）

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

> 依赖清单见 `requirements.txt`（PyQt6、**PyQt6-Fluent-Widgets**、Pillow、**quicktex**）。

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
  # 说明：预览缓存已迁移到项目根 .cache/dds_preview/
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
5. 选择三张图片（与 `CHU_UI_Character_*_00/_01/_02` 及 ddsFile0/1/2 一致）：
   - **全身**（`_00` / ddsFile0）
   - **半身**（`_01` / ddsFile1）
   - **大头**（`_02` / ddsFile2）
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

切到 **ACUS 管理** 页（或主界面左侧进入对应分类）：

- 选择类型：`Event / Map / Music / Chara / …`
- **Event**：表格「分类」列会标注 `MapUnlock`（`map/mapName` 指向地图）、`Promo+DDS`（`information/image/path` 且同目录下存在该 DDS）、`Other` 等；可用 **Event 分类** 下拉框筛选。
- 用搜索框输入 ID/名称/关键字过滤
- 点击表格某条记录：
  - 右侧显示字段详情
  - 若能定位到 DDS（角色大头、曲绘、**宣传 Event 同目录下的 info 图**等），会尝试预览

> 预览会把 DDS 转成 PNG 缓存到项目根目录的 `.cache/dds_preview/`（不在 ACUS 内）。

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

- 左侧切换：`角色 / 地图 / Event / 歌曲 / 称号 / 名牌`
- 设置页配置 `compressonatorcli`
- 新增一个角色（3 图）
- 新增一个称号（可不选图）
- 新增一个名牌（1 图）
- 地图里添加格子奖励并保存（可选勾选「同时生成地图解锁 Event」）
- 管理页查看列表和预览是否正常

### 6.3 可选：快速清理缓存再测

```bash
cd "/Users/mac/code/chuni eventer/desktop"
rm -rf ".cache/dds_preview"
```

---

## 7. Windows 打包为 EXE（PyInstaller）

> 建议在 **Windows 本机** 打包。单文件产物较大（含 PyQt6 / quicktex），属正常现象。

### 7.1 推荐：独立虚拟环境 + 项目 spec

1. 安装 Python 3.12+（勾选 “Add Python to PATH”）。
2. 在项目根目录执行（PowerShell）：

```powershell
cd "E:\path\to\Chuni-Eventer"
python -m venv .venv-build
.\.venv-build\Scripts\pip install -r requirements-build.txt
.\.venv-build\Scripts\python -m PyInstaller --noconfirm ChuniEventer.spec
```

或使用脚本：`.\scripts\build_windows.ps1`（会自动创建 `.venv-build` 并执行打包）。

3. 产物路径：**`dist\ChuniEventer.exe`**（单文件、无控制台窗口）。

> 若全局 Python 曾安装过与标准库冲突的 `typing` 包，PyInstaller 可能报错；请在该环境中执行  
> `pip uninstall typing` 后重试，或始终只用上面的 **venv** 打包。

### 7.2 入口说明

- 源码启动：`python -m chuni_eventer_desktop` 或 `python run_desktop.py`（仓库根目录）。
- 打包入口为根目录 **`run_desktop.py`**，spec 已包含 **`chuni_eventer_desktop/static/trophy`** 稀有度条图片。

### 7.3 首次运行 EXE

- 在 **exe 同级目录** 自动创建 **`ACUS/`**（与源码运行时“仓库根下的 ACUS”不同，便于分发）。
- **quicktex** 已打进 exe；**compressonatorcli** 仍为可选，在【设置】里填写路径即可。

---

## 8. 发行建议（给别人用）

GitHub Release 可只上传 **`ChuniEventer.exe`**；说明中提醒用户：首次运行在同目录生成 `ACUS/`，按需自备或配置 compressonator。

可选：附简短 `README` 片段或链到本仓库说明。

