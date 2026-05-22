# Chuni Eventer 包体体积分析

> 基于本机 `dist/` 中 **v0.7.5** 构建产物实测（2026-05-22）。不同版本号之间 exe 与 `.tools` 结构相同，主要差异见文末「版本变化」。

## 1. 分发形式概览

项目通过 `scripts/build_windows.ps1` 产出两种面向用户的形态：

| 形态 | 路径示例 | 压缩包大小 | 解压后大小 | 说明 |
|------|----------|------------|------------|------|
| **Lite 单 exe** | `dist/release/ChuniEventer.exe` | — | **≈ 121 MB** | 仅主程序；首次运行可在 exe 旁自动下载 `.tools` |
| **懒人包 zip** | `dist/Chuni-Eventer-v0.7.5.zip` | **≈ 335 MB** | **≈ 691 MB** | exe + 完整 `.tools`，解压即用 |

懒人包目录结构：

```
Chuni-Eventer-v0.7.5/
├── ChuniEventer.exe          # PyInstaller 单文件主程序
├── README.txt
├── THIRD_PARTY_COMPRESSONATOR.txt
└── .tools/                   # 外部可执行工具（与 exe 同级）
    ├── ffmpeg/
    ├── CompressonatorCLI/
    ├── PenguinToolsCLI/
    └── PenguinTools/
```

**不在发布包里的内容**（仅开发/源码仓库存在）：

| 路径 | 体积（源码树） | 说明 |
|------|----------------|------|
| `backend/` | 很小 | 谱面上传 **服务端**，不随桌面端分发 |
| `docs/` | 很小 | 文档 |
| `tools/PenguinBridge/` | **≈ 134 MB** | 旧版转谱桥接，v0.6.4 起已弃用，**不打入包** |
| `tools/vgmstream/` | **≈ 10 MB** | 开发脚本解码 AWB 用，**不打入包** |
| `.cache/` | 可达数 GB | 本机缓存（FFmpeg 下载、DDS 预览、谱面缓存等），**不打入包** |

---

## 2. 总体积构成（懒人包 v0.7.5）

```
┌─────────────────────────────────────────────────────────────┐
│  懒人包解压后 ≈ 691 MB                                       │
├──────────────────────────┬──────────────────────────────────┤
│  ChuniEventer.exe        │  120.7 MB  (17%)                 │
│  .tools/                 │  570.1 MB  (83%)                 │
│    ├─ ffmpeg             │  386.0 MB  (56%)  ← 最大单项     │
│    ├─ CompressonatorCLI  │  146.5 MB  (21%)                 │
│    ├─ PenguinToolsCLI    │   27.8 MB  (4%)                  │
│    └─ PenguinTools       │    9.8 MB  (1%)                  │
└──────────────────────────┴──────────────────────────────────┘
```

zip 约 335 MB，是因为 `.tools` 里大量 DLL/EXE 可压缩；exe 本身已高度压缩，zip 前后差距不大。

---

## 3. `ChuniEventer.exe` 内部（≈ 121 MB）

PyInstaller **单文件**打包，运行时解压到临时目录。以下为 **写入 exe 的压缩后体积**（PyInstaller CArchive 实测）：

| 组成部分 | 压缩后体积 | 占比 | 用途 / 备注 |
|----------|------------|------|-------------|
| **PyQt6** | **≈ 78 MB** | **65%** | GUI 框架；含 Qt6Core/Gui/Widgets、FFmpeg 插件 DLL（avcodec 等）、OpenGL 软渲染、大量 QML 插件 |
| **bootloader + 其他二进制** | ≈ 19 MB | 16% | `python312.dll`、OpenSSL、部分未归类 pyd/dll |
| **bundled static** | ≈ 10 MB | 8% | UI 图、logo、字体、奖杯模板等（见 §3.1） |
| **PYZ（Python 字节码）** | ≈ 8 MB | 7% | 标准库 + 应用 `.py` 编译产物 |
| **bundled data** | ≈ 3 MB | 2% | 种子 XML/AWB、dummy ACB/AFB 模板（见 §3.2） |
| **qfluentwidgets** | ≈ 1.4 MB | 1% | Fluent 风格 UI 组件 |
| **quicktex** | ≈ 0.5 MB | <1% | BC3 DDS 编解码（内置，替代 Compressonator 的首选） |
| **Pillow / PyCriCodecsEx / py7zr** | ≈ 0.1 MB 量级 | <1% | 图像处理、ACB/AWB、7z 解压；主要体积在 pyd（如 `PIL/_avif.pyd` ≈ 4 MB 压缩） |

### 3.1 内置静态资源 `chuni_eventer_desktop/static/`（源码 ≈ 12.3 MB）

| 子目录 / 文件 | 体积 | 是否可删 | 说明 |
|---------------|------|----------|------|
| `fonts/MiSans-Heavy.ttf` | **7.4 MB** | 可优化 | 仅 PJSK 奖杯生成器用；可换子集字体或系统字体回退 |
| `logo/ChuniEventer.png` | 1.7 MB | 可优化 | 启动/logo 展示；可压图或换 WebP |
| `logo/*` 其余 | ≈ 1.2 MB | 否 | 关于页、PJSK 图标等 |
| `tool/`、`UI/`、`trophy/`、`PJSK Trophy/` | ≈ 2 MB | 否 | 各功能对话框模板图 |
| `help/` | 0.07 MB | 否 | 帮助截图 |

### 3.2 内置种子数据 `chuni_eventer_desktop/data/`（源码 ≈ 4.3 MB）

| 内容 | 体积 | 是否可删 | 说明 |
|------|------|----------|------|
| `system_voice_seed/.../systemvoice0700.awb` | **≈ 2.7 MB** | **否** | 系统语音包模板，功能依赖 |
| `st_dummy.afb` | 1.25 MB | **否** | Stage AFB 生成模板 |
| `acus_seed/`、`chara_works_seed/` | <0.1 MB | 否 | XML 种子 |
| `dummy.acb`、`nf_dummy.afb` | 很小 | 否 | 音频/AFB 占位模板 |

### 3.3 exe 内 PyQt6 的「隐性膨胀」

`collect_all("PyQt6")` 会打入 **完整 PyQt6 轮子**，其中不少模块桌面端并未直接使用，但在 exe 里占体积，例如：

- `Qt6Designer.dll`、`Qt6Pdf.dll`、`Qt6Quick3D*.dll`
- QML 风格插件、`assimp` 场景导入插件
- `opengl32sw.dll`（软件 OpenGL，≈ 7 MB 压缩）

这些是 **PyQt6 打包体积大的主因**，优化需改 `ChuniEventer.spec` 做模块排除（有回归风险，需全量 UI 测试）。

---

## 4. `.tools/` 外部工具（懒人包 ≈ 570 MB）

定义见 `chuni_eventer_desktop/external_tools.py`，路径解析见 `resolve_tool_path()`。

| 工具 | 体积 | 必需？ | 用途 | 能否去掉 |
|------|------|--------|------|----------|
| **FFmpeg** | **≈ 386 MB** | 推荐 | 系统语音转码、PJSK/pgko 音频 → 48k WAV → ACB | 见 §5.1 |
| **Compressonator CLI** | **≈ 147 MB** | **可选** | DDS BC3 **备选**转换（quicktex 失败时） | **可**（见 §5.2） |
| **PenguinTools.CLI** | **≈ 28 MB** | 转谱需要 | mgxc/ugc/sus → c2s、PGKO 流程 | Lite 版可不预装，应用内下载 |
| **PenguinTools/**（含 mua.exe） | **≈ 10 MB** | Stage 需要 | 图片 → Stage AFB（`mua.exe` 占 8.5 MB） | 不做 Stage 可不装 |

### 4.1 FFmpeg 为何这么大？

构建脚本 `build_windows.ps1` 使用 BtbN 的 **`ffmpeg-master-latest-win64-gpl.zip`**：

| 文件 | 体积 |
|------|------|
| `ffmpeg.exe` | **≈ 193 MB** |
| `ffprobe.exe` | **≈ 193 MB** |

这是 **GPL 静态链接「全家桶」** 构建，单个 exe 自带几乎全部编解码器，因此体积极大。

**重要：`ffprobe.exe` 在应用代码中未被调用**（全仓库无 `ffprobe` 引用），构建脚本只是「同目录有就一并复制」。**去掉 ffprobe 即可少 ≈ 193 MB 解压体积**，对功能无影响。

### 4.2 Compressonator CLI 构成

| 大文件 | 体积 | 说明 |
|--------|------|------|
| `opencv_world420.dll` | 56 MB | OpenCV 依赖 |
| `dxcompiler.dll` | 19 MB | GPU 编译 |
| `Qt5*.dll` + 资源 | ≈ 30 MB | 旧版 Qt GUI 依赖 |
| `compressonatorcli.exe` | 6 MB | 实际 CLI |

应用已内置 **quicktex**（`ChuniEventer.spec` + `dds_convert.py` 优先 quicktex）。Compressonator 仅在 quicktex 不可用或失败时回退（`external_tools.py` 标记为 `optional=True`）。

---

## 5. 可以去掉 / 缩小的部分（按收益排序）

### 5.1 立即可做、低风险

| 措施 | 预计节省（懒人包解压） | 影响 |
|------|------------------------|------|
| **停止打包 `ffprobe.exe`** | **≈ 193 MB** | 无功能影响（未使用） |
| **改用 Lite 单 exe 发布** | **≈ 570 MB**（用户侧按需下载） | 首次使用转谱/语音需联网下载工具 |
| **懒人包去掉 Compressonator**（`-SkipCompressonator`） | **≈ 147 MB** | quicktex 正常时无影响；极端 DDS 场景可能需手动安装 |
| **分开发布「核心懒人包」**（exe + FFmpeg + PenguinTools，无 Compressonator） | **≈ 147 MB** | 同上 |

### 5.2 中等改动

| 措施 | 预计节省 | 说明 |
|------|----------|------|
| **换用更小的 FFmpeg 构建** | **≈ 150–350 MB** | 例如 BtbN `win64-gpl-shared` 或 `essentials` 版（需测 PJSK flac/系统语音格式是否全覆盖） |
| **压缩/子集 `MiSans-Heavy.ttf`** | **≈ 5–7 MB**（exe 内） | 仅奖杯生成用几个汉字/拉丁字符时可子集化 |
| **压缩 `ChuniEventer.png`** | **≈ 1 MB**（exe 内） | 不影响显示质量太多时可转 JPG/WebP |

### 5.3 较大改动（需专项测试）

| 措施 | 预计节省 | 风险 |
|------|----------|------|
| **PyInstaller 排除未用 PyQt6 模块/插件** | **≈ 10–30 MB**（exe） | 可能某对话框/预览突然缺 DLL |
| **PyQt6 → PySide6 或精简 Qt 部署** | 不定 | 框架迁移成本高 |
| **onefolder 代替 onefile** | 不减小总大小，但**启动更快** | 分发形态变化（多文件目录） |

### 5.4 不建议从包体删除

| 内容 | 原因 |
|------|------|
| `system_voice_seed` AWB 模板 | 系统语音功能硬依赖 |
| `st_dummy.afb` / `dummy.acb` | Stage / 音频打包模板 |
| **PenguinTools.CLI**（若用户需要转谱） | 核心功能后端 |
| **mua.exe**（若用户需要 Stage 背景） | AFB 生成唯一路径 |
| **quicktex**（在 exe 内） | DDS 主路径，体积小 |

---

## 6. 为什么 v0.7.5 比 v0.7.1 大很多？

| 版本 | 懒人包 zip | `.tools` 体积 | 差异原因 |
|------|------------|---------------|----------|
| v0.7.1 | ≈ 197 MB | ≈ 184 MB | 无 FFmpeg；含 Compressonator + PenguinToolsCLI + mua |
| **v0.7.5** | **≈ 335 MB** | **≈ 570 MB** | **新增 FFmpeg 全家桶（≈ 386 MB）** |

v0.7.5 起 `build_windows.ps1` 默认把 FFmpeg 打入懒人包（`Copy-FfmpegBundle`），使用户无需首次下载即可用系统语音 / PJSK 音频流程；代价是 **zip 增大约 138 MB（压缩后）**。

---

## 7. 推荐分发策略

按用户场景：

| 用户类型 | 推荐包 | 体积 |
|----------|--------|------|
| 只做地图/奖杯/UI，不转谱 | Lite exe | ≈ 121 MB |
| 需要转谱 + 语音，可接受首次下载 | Lite exe + 应用内「外部工具」一键下载 | 首次 ≈ 121 MB，完整 ≈ 300+ MB |
| 离线开箱即用 | 懒人包（建议 **去掉 ffprobe** 后再打 zip） | zip 可降至 **≈ 240 MB** 量级 |
| 磁盘极紧 + 有 quicktex | 懒人包 + `-SkipCompressonator` | 再少 ≈ 147 MB |

构建命令示例：

```powershell
# 完整懒人包（当前默认）
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.5

# 不打包 Compressonator（少 ~147 MB）
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.5 -SkipCompressonator

# 仅重组装（已有 exe 时）
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.5 -SkipPyInstaller
```

---

## 8. 相关文件索引

| 文件 | 作用 |
|------|------|
| `ChuniEventer.spec` | PyInstaller：打入 static/data、PyQt6、quicktex 等 |
| `scripts/build_windows.ps1` | 组装 exe、FFmpeg、Compressonator、PenguinToolsCLI |
| `chuni_eventer_desktop/external_tools.py` | 外部工具清单、下载 URL、可选/必需标记 |
| `packaging/BUILD_AND_DISTRIBUTION.md` | 打包流程说明 |

---

## 9. 自测体积命令（Windows PowerShell）

```powershell
# 懒人包各顶层项
Get-ChildItem "dist\release\Chuni-Eventer-v0.7.5" | ForEach-Object {
  $b = if ($_.PSIsContainer) {
    (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
  } else { $_.Length }
  "{0}: {1:N2} MB" -f $_.Name, ($b/1MB)
}

# .tools 分项
Get-ChildItem "dist\release\Chuni-Eventer-v0.7.5\.tools" -Directory | ForEach-Object {
  $b = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
  "{0}: {1:N2} MB" -f $_.Name, ($b/1MB)
}
```

分析 exe 内部组件（需已构建且安装 PyInstaller）：

```powershell
.\.venv-build\Scripts\python.exe -c "
from PyInstaller.archive.readers import CArchiveReader
from collections import defaultdict
r = CArchiveReader('dist/ChuniEventer.exe')
g = defaultdict(float)
for name, ent in r.toc.items():
    if name == 'struct': continue
    ln = ent[1]
    n = name.replace('\\\\', '/')
    if 'PyQt6' in n: k = 'PyQt6'
    elif 'static' in n: k = 'static'
    elif 'data' in n: k = 'data'
    else: k = 'other'
    g[k] += ln
for k, v in sorted(g.items(), key=lambda x: -x[1]):
    print(f'{k}: {v/1024/1024:.1f} MB')
"
```
