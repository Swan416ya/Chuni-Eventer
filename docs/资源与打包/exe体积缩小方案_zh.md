# ChuniEventer.exe 体积缩小方案（纯 exe 目标）

> **唯一目标**：缩小 `dist/ChuniEventer.exe`（Lite 单文件）体积。  
> **不涉及**懒人包 `.tools`、FFmpeg、Compressonator 等（见 [包体优化方案_zh.md](./包体优化方案_zh.md)）。  
> **基准**：当前构建 **≈ 120.7 MB**（v0.7.5，PyInstaller onefile）。

---

## 1. 现状与理论下限

### 1.1 120 MB 从哪来

| 块 | 体积 | 可否动 |
|----|------|--------|
| `PyQt6/Qt6`（DLL + QML + plugins） | **72 MB** | ✅ 主战场 |
| `PyQt6` 其它（.pyd、bindings） | **6 MB** | ✅ |
| `static/` | **10 MB** | ✅ |
| `PIL/` | **7 MB** | ✅ 部分 |
| `pywin32` / Pythonwin | **3 MB** | ✅ |
| `data/` 种子 | **3 MB** | ⚠️ 仅 AWB 难删 |
| Python 运行时 + PYZ | **10 MB** | ⚠️ 刚性底座 |
| qfluentwidgets | **1 MB** | ❌ 除非重写 UI |

### 1.2 合理目标

| 阶段 | 目标 exe | 做法概要 | 状态 |
|------|----------|----------|------|
| **S1 快赢** | **≈ 105 MB** | spec 排除 + 删 AVIF/Pythonwin，Qt6 二进制裁剪 | ✅ 已实施 |
| **S2 结构** | **≈ 85–95 MB** | 取消 `collect_all(PyQt6)` + Qt6 白名单 | ✅ 已实施（实测 **≈ 56.5 MB**） |
| **S3 资源** | **再 −5~8 MB** | 字体/Logo 瘦身 |
| **S4 可选** | **再 −10~15%** | UPX（需杀软验证） |

**理论下限（仍保留 PyQt6 + Fluent UI）**：约 **75–80 MB**，再低需换 UI 框架或 onefolder（不减小总占用，只加快启动）。

---

## 2. 实施顺序（只做 exe）

按 **投入产出比** 排序；每步完成后执行 §6 测量并跑 §7 回归。

```
S1-a → S1-b → S1-c → S2-a → S2-b → S2-c → S3 → S4
 │      │      │      └─ PyQt6 按需收集（最大单项）
 │      │      └─ 排除 Pythonwin + bindings
 │      └─ 排除 PIL AVIF
 └─ Analysis excludes 空壳模块
```

---

## 3. S1：快赢（改 spec 即可，约 1 天，−12~18 MB）

### S1-a. `excludes` 排除未使用的 PyQt6 子模块

**依据**：全仓库仅 `QtCore` / `QtGui` / `QtWidgets` / `QtSvg`（一处）。

在 `ChuniEventer.spec` 的 `Analysis(..., excludes=[...])` 增加：

```python
PYQT6_UNUSED = [
    "PyQt6.QtDesigner",
    "PyQt6.QtQuick",
    "PyQt6.QtQml",
    "PyQt6.QtMultimedia",
    "PyQt6.QtPdf",
    "PyQt6.QtSql",
    "PyQt6.QtBluetooth",
    "PyQt6.QtNfc",
    "PyQt6.QtDBus",
    "PyQt6.QtWebSockets",
    "PyQt6.QtSerialPort",
    "PyQt6.QtPositioning",
    "PyQt6.QtSensors",
    "PyQt6.QtTextToSpeech",
    "PyQt6.QtRemoteObjects",
    "PyQt6.QtWebChannel",
]
excludes = ["Pythonwin"] + PYQT6_UNUSED
```

**说明**：`excludes` 主要拦 Python 层；**Qt6/bin 里的大 DLL 仍可能被 `collect_all` 整包带入**，所以 S1-a 单独做收益有限（约 **0–3 MB**），但与 S2 叠加必要。

**验收**：启动 + 关于页 SVG（`settings_about_panel.py`）。

---

### S1-b. 过滤 `PIL/_avif*.pyd`（约 −4 MB）

**依据**：无 AVIF 业务路径；对话框 filter 只有 png/jpg/webp/bmp。

在 `Analysis` 之后、`PYZ` 之前：

```python
a.binaries = [
    b for b in a.binaries
    if "_avif" not in b[0].replace("\\", "/").lower()
]
```

**验收**：地图/活动/头像/Stage 各导入一张 webp 与 png。

---

### S1-c. 去掉 Pythonwin + PyQt6 bindings（约 −3.5 MB）

**依据**：

- `qframelesswindow` 只需 `win32gui`，不需要 `Pythonwin/mfc140u.dll`（≈ 2.6 MB）。
- `PyQt6/bindings/*.sip`（≈ 0.9 MB）运行时不用。

```python
def _norm(p: str) -> str:
    return p.replace("\\", "/")

a.binaries = [b for b in a.binaries if "Pythonwin" not in _norm(b[0])]
a.datas = [d for d in a.datas if "/bindings/" not in _norm(d[0])]
```

`excludes` 中已有 `"Pythonwin"`（见 S1-a）。

**验收**：无边框窗口拖拽/最大化；任务栏图标（`app.py`）。

---

### S1 预期

| 步骤 | 预估 −MB |
|------|----------|
| S1-b AVIF | 4 |
| S1-c Pythonwin + bindings | 3.5 |
| S1-a excludes | 0–3 |
| **合计** | **≈ 8–11 MB → exe ≈ 109–112 MB** |

---

## 4. S2：PyQt6 按需收集（约 1–2 天，−25~35 MB，核心）

### 4.1 问题

当前：

```python
for pkg in ("PyQt6", "qfluentwidgets", ...):
    p_d, p_bin, p_hi = collect_all(pkg)
```

`collect_all("PyQt6")` 把 **2557 个文件 / 72 MB Qt6** 全打进 exe，包括：

| 可删 DLL（压缩后约） | 业务 |
|---------------------|------|
| `opengl32sw.dll` | 7.3 MB | 无独显时的软件 GL；**建议 S2-c 再定** |
| `avcodec-61.dll` + `avformat-61.dll` | 7.0 MB | 未用 Qt 视频 |
| `Qt6Designer.dll` | 3.1 MB | 未用 |
| `Qt6Quick.dll` + `Qt6/qml/` | 6+ MB | 未用 QML |
| `Qt6Pdf.dll` | 2.7 MB | 未用 |
| `Qt6Quick3D*.dll` | 4+ MB | 未用 |
| `plugins/sqldrivers/` | 1.3 MB | 未用 QtSql |
| `plugins/assetimporters/assimp.dll` | 0.9 MB | 未用 |

### 4.2 推荐改法（分三步，每步打 exe 测体积）

**Step 1 — PyQt6 移出 `collect_all` 循环**

```python
SMALL_PKGS = ("qfluentwidgets", "qframelesswindow", "quicktex", "PIL", "PyCriCodecsEx")
for pkg in SMALL_PKGS:
    p_d, p_bin, p_hi = collect_all(pkg)
    datas += p_d
    binaries += p_bin
    hiddenimports += p_hi

hiddenimports += [
    "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtSvg",
]
# 仍用 PyInstaller 自带 hook 收集 PyQt6，但配合 excludes + 下面过滤
from PyInstaller.utils.hooks import collect_all as _ca
_p_d, _p_b, _p_hi = _ca("PyQt6")
datas += _p_d
binaries += _p_b
hiddenimports += _p_hi
```

**Step 2 — Analysis 后按路径黑名单删二进制**

```python
QT6_DROP_PREFIXES = (
    "PyQt6/Qt6/bin/Qt6Designer",
    "PyQt6/Qt6/bin/Qt6Quick",
    "PyQt6/Qt6/bin/Qt6Qml",
    "PyQt6/Qt6/bin/Qt6Pdf",
    "PyQt6/Qt6/bin/Qt6Multimedia",
    "PyQt6/Qt6/bin/avcodec-",
    "PyQt6/Qt6/bin/avformat-",
    "PyQt6/Qt6/bin/avutil-",
    "PyQt6/Qt6/bin/Qt6Quick3D",
    "PyQt6/Qt6/qml/",
    "PyQt6/Qt6/plugins/sqldrivers/",
    "PyQt6/Qt6/plugins/assetimporters/",
    "PyQt6/Qt6/plugins/sceneparsers/",
    "PyQt6/Qt6/plugins/multimedia/",
    "PyQt6/Qt6/plugins/qmlls/",
)

def _drop_binaries(binaries):
    out = []
    for entry in binaries:
        src = _norm(entry[0])
        if any(p in src for p in QT6_DROP_PREFIXES):
            continue
        out.append(entry)
    return out

a.binaries = _drop_binaries(a.binaries)
# 与 S1 的 AVIF / Pythonwin 过滤合并为一条 pipeline
```

**Step 3 — 保留最小 plugins 白名单（若 Step 2 删太狠导致无法启动）**

必须保留（经验值）：

- `PyQt6/Qt6/plugins/platforms/qwindows.dll`
- `PyQt6/Qt6/plugins/imageformats/qjpeg.dll`、`qpng.dll`、`qgif.dll`、`qico.dll`
- `PyQt6/Qt6/plugins/styles/qmodernwindowsstyle.dll`（或当前主题实际加载项）

**`opengl32sw.dll` 决策**：

- **保留**：兼容无硬件 OpenGL 机器；少 7 MB 但可能黑屏/无法启动。
- **删除**：exe 更小；需在核显/独显/远程桌面各测一次。

### 4.3 S2 预期

| 情况 | exe 约 |
|------|--------|
| Step 2 成功（保留 opengl32sw） | **88–95 MB** |
| 再删 opengl32sw | **80–88 MB** |

---

## 5. S3：内置资源瘦身（约半天，−5~8 MB）

只动打进 exe 的 `static/` / `data/`，不改 `.tools`。

| 文件 | 当前 | 动作 | 预估 −MB | 关联代码 |
|------|------|------|----------|----------|
| `static/fonts/MiSans-Heavy.ttf` | 7.4 MB | `pyftsubset` 留奖杯用字集 | **5–6** | `trophy_pjsk_generator_dialog.py` |
| `static/logo/ChuniEventer.png` | 1.7 MB | 压为 512px PNG 或 JPG | **1–1.5** | `app.py`, `settings_about_panel.py` |
| `static/logo/SwanClub.jpg` | 0.6 MB | 质量 80 重导 | **0.2** | 关于页 |
| `data/.../systemvoice0700.awb` | 2.7 MB | **不删** | — | `system_voice_pack.py` |

**注意**：资源变小后无需改 spec，仍走现有 `datas` 整目录复制。

### S3 预期

S2 完成后 **再 −5~8 MB → exe ≈ 80–90 MB**。

---

## 6. S4：可选手段

| 手段 | 预估 | 风险 | 建议 |
|------|------|------|------|
| `upx=True`（spec EXE 段） | **−10~15%** | 杀软误报、个别 pyd 崩溃 | S1–S3 做完仍 >90 MB 再试 |
| `strip=True` | 很小 | Windows 上收益有限 | 可顺手开 |
| **onefolder** | 总占用不变 | 分发形态变化 | **不算减小 exe**，仅加快启动 |
| 换 PySide6 / 去 Fluent | 数十 MB | 重写 UI | 超出「纯 shrink」范围 |

---

## 7. 汇总路线图

| 阶段 | 改动文件 | 预估 exe | 累计 −MB | 风险 |
|------|----------|----------|----------|------|
| 基准 | — | **121 MB** | — | — |
| **S1** | `ChuniEventer.spec` | **109–112 MB** | 9–12 | 低 |
| **S2** | `ChuniEventer.spec` | **85–95 MB** | 25–35 | 中 |
| **S3** | `static/`、`assets/` | **80–90 MB** | 5–8 | 低 |
| **S4** | spec UPX | **72–81 MB** | 10–15% | 中 |

**推荐最小闭环**：**S1 + S2（保留 opengl32sw）+ S3** → 目标 **≈ 82–88 MB**。

---

## 8. spec 改动清单（实施 S1+S2 时）

建议新建 `packaging/pyinstaller_filters.py`，在 spec 里：

```python
from packaging.pyinstaller_filters import apply_exe_size_filters

a = Analysis(...)
a = apply_exe_size_filters(a)  # AVIF、Pythonwin、bindings、Qt6 黑名单
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
```

便于维护黑名单，避免 spec 过长。

**不要动**：

- `quicktex` / `_quicktex.pyd` 显式打入（`dds_quicktex.py` 子进程）
- `data/system_voice_seed`（系统语音）
- `qfluentwidgets` / `qframelesswindow` 的 `collect_all`（除非接受 UI 重写）

**可继续 `collect_all` 的小包**：`quicktex`、`PyCriCodecsEx`、`py7zr`（在 PyCri 依赖里）、`PIL`（S1 后过滤 AVIF 即可）。

---

## 9. 测量方法

每次改 spec 后：

```powershell
# 构建
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.5 -SkipPenguinToolsCli

# 或仅 PyInstaller
.\.venv-build\Scripts\python.exe -m PyInstaller --noconfirm ChuniEventer.spec

# 体积
[math]::Round((Get-Item dist\ChuniEventer.exe).Length / 1MB, 2)

# 分项（需 venv 内 PyInstaller）
.\.venv-build\Scripts\python.exe -c "
from PyInstaller.archive.readers import CArchiveReader
from collections import defaultdict
r = CArchiveReader('dist/ChuniEventer.exe')
g = defaultdict(float)
for name, ent in r.toc.items():
    if name == 'struct': continue
    n = name.replace(chr(92),'/')
    k = 'PyQt6/Qt6' if n.startswith('PyQt6/Qt6/') else (
        'static' if 'static' in n else 'PIL' if n.startswith('PIL/') else 'other')
    g[k] += ent[1]
for k,v in sorted(g.items(), key=lambda x:-x[1]):
    print(f'{k:16} {v/1024/1024:.1f} MB')
"
```

记录表格：

| 日期 | 阶段 | exe MB | PyQt6/Qt6 MB | static MB | PIL MB | 备注 |
|------|------|--------|--------------|-----------|--------|------|

---

## 10. 回归清单（仅 exe 相关）

### 启动 / 壳

- [ ] 冷启动无报错
- [ ] 无边框：拖拽、最大化、最小化、多屏
- [ ] 任务栏 / Alt+Tab 图标（`.ico` HWND 路径）
- [ ] 关于页 SVG（`QtSvg`）

### 图像 / DDS

- [ ] 游戏索引 + DDS 缩略图
- [ ] 地图/称号/头像：png、jpg、**webp** 导入
- [ ] BC3 DDS 导出（quicktex 子进程，`run_desktop.py --chuni-quicktex-worker`）

### 功能抽样

- [ ] PJSK 奖杯生成器字体渲染（若做了 MiSans 子集）
- [ ] 系统语音包向导（AWB 模板）
- [ ] 7z 谱面安装（py7zr）
- [ ] PJSK 音频 ACB（PyCriCodecsEx，与 exe 内模块相关）

### 无 GPU / 远程桌面（S2 删 opengl32sw 时必测）

- [ ] 界面正常渲染、无全黑窗口

---

## 11. 明确不做（对 exe 几乎无收益）

| 项 | 原因 |
|----|------|
| 删除 `map_add_dialog.py` 等大模块 | 源码 1.3 MB，PYZ 内更小 |
| 移除 quicktex / PyCri / py7zr | 合计约 1 MB，功能必需 |
| 移除 qfluentwidgets | 约 1.4 MB，换框架成本极高 |
| 删 `system_voice_seed` AWB | 功能硬依赖 |

---

## 12. 相关文档

- [exe本体体积分析_zh.md](./exe本体体积分析_zh.md) — 121 MB 逐项来源与代码引用
- [包体优化方案_zh.md](./包体优化方案_zh.md) — 懒人包 / `.tools`（与 exe 无关部分）

---

## 13. 建议执行口令（给维护者）

```text
目标：仅缩小 ChuniEventer.exe
顺序：S1 spec 过滤 → 测 → S2 Qt6 黑名单 → 测 → S3 资源 → 测
不测 .tools / zip
成功标准：exe ≤ 90 MB 且 §10 全绿；理想 ≤ 85 MB
```

若需要，可在下一 PR 中直接落地 **S1**（改 `ChuniEventer.spec` + 可选 `packaging/pyinstaller_filters.py`），通常半天内可见 **−10 MB 左右**。
