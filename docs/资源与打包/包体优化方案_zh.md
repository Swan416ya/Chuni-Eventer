# Chuni Eventer 包体优化方案（按优先级）

> 基于 [exe本体体积分析_zh.md](./exe本体体积分析_zh.md) 与 [包体体积分析_zh.md](./包体体积分析_zh.md) 的结论，整理为**可执行的优化路线图**。  
> 基准：v0.7.5 — Lite exe **≈ 121 MB**，懒人包 zip **≈ 335 MB**（解压 **≈ 691 MB**）。

---

## 0. 目标与原则

### 优化目标（ realistic ）

| 阶段 | Lite exe | 懒人包 zip | 说明 |
|------|----------|------------|------|
| 当前 | ≈ 121 MB | ≈ 335 MB | 基准 |
| **阶段 A**（低风险，1–2 天） | **≈ 110 MB** | **≈ 145 MB** | 不改 PyQt6 收集策略，主要动 `.tools` 与 spec 排除 |
| **阶段 B**（中风险，3–5 天） | **≈ 85–95 MB** | 随 exe 下降 | 精简 PyQt6 + 资源 |
| **阶段 C**（可选） | **≈ 75–85 MB** | 进一步 | 分发策略拆分、FFmpeg 换源 |

### 原则

1. **先懒人包 / 构建脚本，再 exe spec** — FFmpeg、ffprobe 零风险项收益最大（懒人包 −190 MB 量级）。
2. **每项优化必须可测量** — 改前后对比 `dist/ChuniEventer.exe` 与 zip 大小。
3. **每项优化必须有回归清单** — 见文末 §7。
4. **不要删业务 `.py`** — 对体积几乎无帮助。

---

## 1. 优先级总览

| 优先级 | 编号 | 做什么 | 改哪里 | 预估节省 | 风险 | 工时 |
|--------|------|--------|--------|----------|------|------|
| **P0** | A1 | 懒人包不再复制 `ffprobe.exe` | `scripts/build_windows.ps1` | 懒人包 **−193 MB** 解压 / zip **−~90 MB** | 极低 | ✅ 已实施 |
| **P0** | A2 | 发布策略：默认主推 Lite exe，懒人包作可选 | 文档 + GitHub Release | 用户感知 **−570 MB** | 无 | 文档已更新 |
| **P1** | B3 | 懒人包默认 `-SkipCompressonator` 或单独出「精简懒人包」 | `build_windows.ps1` / CI | 懒人包 **−147 MB** | 低–中 | ✅ 已实施（默认跳过，`-IncludeCompressonator` opt-in） |
| **P1** | B1 | spec 排除 `Pythonwin` + PyQt6 `bindings/` | `ChuniEventer.spec` | exe **−3~4 MB** | 低 | 1 h |
| **P1** | B2 | spec 排除 `PIL/_avif*.pyd` | `ChuniEventer.spec` | exe **−4 MB** | 低 | 1 h |
| **P2** | C1 | 压缩/替换大静态资源 | `static/` + 可选代码 | exe **−5~8 MB** | 低 | 2–4 h |
| **P2** | C2 | 换更小的 FFmpeg 构建 | `build_windows.ps1` + `external_tools.py` URL | 懒人包 **−150~350 MB** | 中 | 4–8 h |
| **P2** | C3 | 精简 PyQt6：不用 `collect_all`，只收 Widgets 链 | `ChuniEventer.spec` + hook | exe **−25~40 MB** | **中–高** | 1–2 天 |
| **P3** | D1 | 评估 `onefolder` 或 UPX | spec / 发布说明 | 启动体验或 **−10~15%** | 中 | 1 天 |
| **P3** | D2 | MiSans 子集字体 | 字体工具 + `static/fonts/` | exe **−5~6 MB** | 低 | 2 h |
| **不做** | — | 删 `map_add_dialog.py` 等大模块 | — | **≈ 0** | — | — |
| **不做** | — | 移除 quicktex / PyCri / py7zr | — | **≈ 1 MB** | 功能损失 | — |

---

## 2. P0：立刻做（高收益、几乎零风险）

### A1. 懒人包去掉 `ffprobe.exe`

**问题**：`build_windows.ps1` 的 `Copy-FfmpegBundle` 在复制 `ffmpeg.exe` 时，若同目录有 `ffprobe.exe` 就一并复制。BtbN GPL 静态构建里 **ffprobe 也约 193 MB**。全仓库 **没有任何业务代码调用 ffprobe**。

**做法**：

1. 编辑 `scripts/build_windows.ps1` → `Copy-FfmpegBundle`：
   - 只复制 `ffmpeg.exe`；
   - **删除**对 `ffprobe.exe` 的 `Copy-Item`（或改为可选开关 `-IncludeFfprobe`）。
2. 重新打包，确认懒人包 `.tools/ffmpeg/bin/` 仅含 `ffmpeg.exe`。
3. 更新 `packaging/BUILD_AND_DISTRIBUTION.md` 与 Release 说明。

**验收**：

- [ ] 系统语音打包（`system_voice_pack.py`）正常
- [ ] PJSK / pgko 音频转 48k WAV（`pjsk_audio_chuni.py`）正常
- [ ] 懒人包 `.tools/ffmpeg` 目录 **< 200 MB**

**预估**：懒人包解压 691 → **≈ 498 MB**；zip 335 → **≈ 240 MB**。

---

### A2. 分发策略：Lite 为主、懒人包为辅

**问题**：v0.7.5 懒人包膨胀主因是 **预装 FFmpeg**；而项目本身已支持 Lite exe + 应用内下载 `.tools`（`external_tools.py`）。

**做法**：

1. **GitHub Release 默认附件**：仅 `ChuniEventer.exe`（Lite）。
2. **懒人包**改名为「离线完整包 / Offline Bundle」，说明含 FFmpeg + PenguinToolsCLI +（可选）Compressonator。
3. README / Release note 写清：
   - 只转谱、不做语音 → Lite 足够，按需下载 PenguinToolsCLI；
   - 需要离线开箱 → 下懒人包。

**验收**：新用户下载体积从 335 MB 降到 **121 MB**（若只下 Lite）。

**预估**：不改变构建产物，但 **默认下载量 −214 MB**。

---

## 3. P1：短期做（改 spec / 构建参数，低风险）

### B1. 排除 Pythonwin 与 PyQt6 bindings

**问题**：

- `qframelesswindow` 只需 `win32gui` / `win32api`，PyInstaller 误收 **Pythonwin**（含 `mfc140u.dll` ≈ 2.6 MB）。
- `PyQt6/bindings/*.sip`（≈ 0.9 MB）为开发用，运行时不需要。

**做法** — 在 `ChuniEventer.spec` 的 `Analysis(...)` 中：

```python
excludes=[
    "Pythonwin",
],
```

并在 `Analysis` 之后、`PYZ` 之前增加过滤（若 excludes 不够彻底）：

```python
# 从 datas 去掉 PyQt6 bindings（示意，按 PyInstaller 版本调整）
a.datas = [(s, d, t) for s, d, t in a.datas if "/bindings/" not in d.replace("\\", "/")]
a.binaries = [(s, d, t) for s, d, t in a.binaries if "Pythonwin" not in s.replace("\\", "/")]
```

**验收**：

- [ ] 主窗口无边框、最大化、最小化、拖拽正常
- [ ] 任务栏 / Alt+Tab 图标正常（`app.py` HWND 逻辑）
- [ ] exe 减小约 3–4 MB

---

### B2. 排除 Pillow AVIF 扩展

**问题**：`PIL/_avif.cp312-win_amd64.pyd` 约 **4 MB**；业务只处理 png/jpeg/webp/bmp，无 AVIF 路径。

**做法**：

```python
excludes=["Pythonwin"],  # 与 B1 合并
# Analysis 后过滤 binaries：
a.binaries = [
    b for b in a.binaries
    if "_avif" not in b[0].replace("\\", "/").lower()
]
```

**验收**：

- [ ] 地图 / 活动 / 头像 / Stage 图片导入（各 dialog 的 `*.webp` filter）
- [ ] `music_jacket_replace.py` 封面替换
- [ ] exe 减小约 4 MB

---

### B3. 懒人包默认不打包 Compressonator

**问题**：CompressonatorCLI **147 MB**；应用已内置 **quicktex**（`ChuniEventer.spec`），Compressonator 仅为 `dds_convert.py` 回退（`external_tools.py` 标记 `optional=True`）。

**做法**（二选一）：

1. **构建默认加** `-SkipCompressonator`，Release 懒人包说明「DDS 回退需应用内下载或自带 quicktex」；
2. 或提供两个 zip：`Chuni-Eventer-vX-full.zip` 与 `Chuni-Eventer-vX.zip`（无 Compressonator）。

**验收**：

- [ ] 地图 DDS 预览、称号/头像 BC3 导出（quicktex 路径）
- [ ] 设置页仍可一键下载 Compressonator

**预估**：懒人包再 **−147 MB**（与 A1 叠加后 zip 可至 **≈ 100 MB 量级**）。

---

### P1 阶段预期合计

| 产物 | 优化前 | P0+P1 后（估算） |
|------|--------|------------------|
| Lite exe | 121 MB | **≈ 113–115 MB** |
| 懒人包 zip | 335 MB | **≈ 95–110 MB**（A1+B3，不含 exe spec 收益） |
| 懒人包解压 | 691 MB | **≈ 250–280 MB** |

---

## 4. P2：中期做（资源 + FFmpeg + PyQt6 精简）

### C1. 静态资源瘦身

| 文件 | 当前 | 动作 | 节省 |
|------|------|------|------|
| `static/logo/ChuniEventer.png` | ≈ 1.7 MB | 压为 JPG 或 512px PNG；同步改 `app.py` / `settings_about_panel.py` | ≈ 1 MB |
| `static/logo/SwanClub.jpg` | ≈ 0.6 MB | 质量 80 重导 | ≈ 0.2 MB |
| `static/fonts/MiSans-Heavy.ttf` | ≈ 7.4 MB | 见 D2 子集化 | ≈ 5–6 MB |

**注意**：`data/system_voice_seed/.../systemvoice0700.awb`（≈ 2.7 MB）**不能删**。

---

### C2. 更换 FFmpeg 下载源

**问题**：BtbN `ffmpeg-master-latest-win64-gpl` 单文件 **≈ 193 MB**，因静态链接全部编解码器。

**做法**：

1. 调研并固定一版 **essentials** 或 **shared** 构建（需覆盖：flac、mp3、wav、ogg、aac 等 PJSK/语音场景）。
2. 修改 `scripts/build_windows.ps1` 的 `$FfmpegUrl` 与 `external_tools.py` 的 `TOOL_FFMPEG.download_url` **保持一致**。
3. 在干净环境跑 `pjsk_audio_chuni.ffmpeg_trim_to_chuni_wav` 与系统语音转码。

**预估**：懒人包 FFmpeg 部分 386 → **36–150 MB**（取决于选型）。

**风险**：中 — 某冷门格式转码失败需回退或文档说明。

---

### C3. 精简 PyQt6 打包（最大 exe 优化项）

**问题**：`collect_all("PyQt6")` 打入 Quick/QML/Pdf/Designer/Multimedia/Sql 等 **≈ 25–40 MB** 无用内容；业务仅用 `QtCore`、`QtGui`、`QtWidgets`、`QtSvg`（一处）。

**推荐步骤**（分步实施，每步都打 exe 并回归）：

**Step 1 — 加 excludes（不动 collect_all）**

```python
excludes=[
    "Pythonwin",
    "PyQt6.QtDesigner", "PyQt6.QtQuick", "PyQt6.QtQml",
    "PyQt6.QtMultimedia", "PyQt6.QtPdf", "PyQt6.QtSql",
    "PyQt6.QtBluetooth", "PyQt6.QtNfc", "PyQt6.QtDBus",
    "PyQt6.QtWebSockets", "PyQt6.QtSerialPort",
]
```

**Step 2 — 若体积仍大，改为不全量 collect**

```python
from PyInstaller.utils.hooks import collect_submodules

hiddenimports += collect_submodules("PyQt6.QtCore")
hiddenimports += collect_submodules("PyQt6.QtGui")
hiddenimports += collect_submodules("PyQt6.QtWidgets")
hiddenimports += collect_submodules("PyQt6.QtSvg")
# 仅 collect_data_files / collect_dynamic_libs 针对上述子包
# qfluentwidgets / qframelesswindow 仍 collect_all
```

**Step 3 — 手动保留必要 Qt plugins**

至少保留：

- `Qt6/plugins/platforms/qwindows.dll`
- `Qt6/plugins/imageformats/qjpeg.dll`、`qpng.dll` 等
- `Qt6/plugins/styles/`（若 Fluent 依赖）

删除候选：`sqldrivers/`、`assetimporters/`、`sceneparsers/`、`multimedia/`、`qmlls/` 等。

**验收**：全文 §7 回归 + 无 GPU 机器上启动（`opengl32sw.dll` 是否保留需单独评估）。

**预估**：exe **121 → 85–95 MB**。

---

## 5. P3：可选 / 长期

### D1. onefolder 或 UPX

| 方案 | 效果 | 代价 |
|------|------|------|
| **onefolder** | 总大小相近，**启动更快**（免单文件解压） | 分发变为目录；与「单 exe」品牌不一致 |
| **UPX**（`upx=True`） | exe **−10~15%** | 杀软误报、个别 DLL 不兼容 |

建议：仅在 P0–P2 完成后仍不满意时再试；UPX 需在一台「有杀软」的机器上验证。

---

### D2. MiSans 子集字体

**引用**：仅 `ui/trophy_pjsk_generator_dialog.py`。

**做法**：用 `pyftsubset` 或 FontTools 保留奖杯生成常用字符（数字、日文假名/常用汉字、拉丁），替换 `static/fonts/MiSans-Heavy.ttf`。

**验收**：PJSK 奖杯预览文字渲染正常。

---

## 6. 推荐实施顺序（时间线）

```
第 1 天  ── P0: A1 去 ffprobe + A2 发布策略
         ── 重打懒人包，确认 zip 体积

第 2 天  ── P1: B1 + B2 改 ChuniEventer.spec
         ── 全量回归 Lite exe

第 3 天  ── P1: B3 懒人包 SkipCompressonator
         ── 更新 Release 文档

第 4–5 天 ── P2: C1 静态资源压图

第 2 周  ── P2: C2 FFmpeg 换源（需格式测试矩阵）

第 2–3 周 ── P2: C3 PyQt6 精简（分 Step 1→2→3，每步回归）

按需     ── P3: D1/D2
```

---

## 7. 统一回归清单（每项优化后至少跑一遍）

### 启动与壳

- [ ] 双击 `ChuniEventer.exe` 冷启动无报错
- [ ] 无边框窗口：拖拽、最大化、最小化、多显示器
- [ ] 任务栏 / Alt+Tab 图标（ico 路径）
- [ ] 关于页 SVG logo（`QtSvg`）

### DDS / 图像

- [ ] 游戏数据索引 + DDS 缩略图预览
- [ ] 地图 / 称号 / 头像 图片 → BC3 DDS（quicktex 路径）
- [ ] png / jpg / webp 导入各一处

### 音频 / 语音

- [ ] 系统语音包：选 wav → 打包（需 FFmpeg）
- [ ] PJSK：下载谱面 → 音频 ACB（需 FFmpeg + PyCriCodecsEx）

### 转谱 / 安装

- [ ] pgko 或 PJSK 转谱（PenguinToolsCLI）
- [ ] 7z 谱面包解压安装（py7zr）
- [ ] Stage 背景 AFB（mua，若在懒人包内）

### 外部工具

- [ ] Lite：首次启动「下载 FFmpeg / CLI」流程
- [ ] 设置 → 外部工具路径识别 `.tools`

---

## 8. 体积测量命令

每次优化后执行并记入 Release / CHANGELOG：

```powershell
# exe
(Get-Item dist\ChuniEventer.exe).Length / 1MB

# 懒人包目录
$bd = "dist\release\Chuni-Eventer-vX.Y.Z"
(Get-ChildItem $bd -Recurse -File | Measure-Object Length -Sum).Sum / 1MB

# .tools 分项
Get-ChildItem "$bd\.tools" -Directory | ForEach-Object {
  $s = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
  "{0}: {1:N1} MB" -f $_.Name, ($s/1MB)
}

# zip
(Get-Item dist\Chuni-Eventer-vX.Y.Z.zip).Length / 1MB
```

---

## 9. 不建议做的「优化」

| 想法 | 原因 |
|------|------|
| 删除大 `.py` 模块 | 源码 1.3 MB，对 121 MB exe 无意义 |
| 移除 quicktex / PyCriCodecsEx / py7zr | 各 ≈ 1 MB 级，核心功能依赖 |
| 移除 `system_voice_seed` AWB | 系统语音硬依赖 |
| 移除 qfluentwidgets 换原生 Qt | 等于重写 UI，收益仅 ≈ 1.4 MB |
| 仓库内删 `tools/PenguinBridge` | 已不进发布包；删源码对包体无影响 |

---

## 10. 相关文档

- [exe本体体积分析_zh.md](./exe本体体积分析_zh.md) — exe 内 121 MB 逐项来源
- [包体体积分析_zh.md](./包体体积分析_zh.md) — 懒人包 + `.tools` 分析
- [BUILD_AND_DISTRIBUTION.md](../../packaging/BUILD_AND_DISTRIBUTION.md) — 构建命令

---

## 11. 预期最终形态（阶段 A + B 全部完成）

| 产物 | 当前 | 目标 |
|------|------|------|
| Lite exe | 121 MB | **85–95 MB** |
| 懒人包 zip | 335 MB | **80–120 MB** |
| 懒人包解压 | 691 MB | **200–350 MB** |
| GitHub 默认下载 | 335 MB（若下懒人包） | **85–95 MB**（Lite） |

以上为目标区间，实际以改后 `dist/` 实测为准。
