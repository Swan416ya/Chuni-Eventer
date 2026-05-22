# ChuniEventer.exe 本体体积分析（代码级）

> 针对 **Lite 单文件** `dist/ChuniEventer.exe`（实测 **≈ 120.7 MB**），从 **PyInstaller 配置 → 依赖链 → 业务代码引用** 说明每一大块从哪来、能否裁剪。  
> 分析基于 v0.7.5 构建产物与 `ChuniEventer.spec`，数据来自 PyInstaller `CArchiveReader` 解压目录统计。

---

## 1. 结论先说

**121 MB 里，业务 Python 源码和 UI 逻辑几乎可以忽略；体积几乎全是「整包打进来的第三方运行时」。**

| 类别 | 压缩后体积 | 占 exe 比例 | 根因（代码/配置） |
|------|------------|-------------|-------------------|
| **PyQt6 完整轮子** | **≈ 72 MB** | **≈ 60%** | `ChuniEventer.spec` 里 `collect_all("PyQt6")` |
| **自打 static/data 资源** | **≈ 13 MB** | **≈ 11%** | `spec` 的 `datas` + 业务模块硬编码路径 |
| **Pillow 原生编解码** | **≈ 6.7 MB** | **≈ 6%** | `collect_all("PIL")` 带入 AVIF/字体等 pyd |
| **Python 运行时 + 标准库** | **≈ 10 MB** | **≈ 8%** | PyInstaller 固定开销（`python312.dll` + `PYZ.pyz`） |
| **pywin32 / Pythonwin** | **≈ 3.1 MB** | **≈ 3%** | `qframelesswindow` → `win32gui`；PyInstaller 误收 IDE 组件 |
| **qfluentwidgets 资源** | **≈ 1.4 MB** | **≈ 1%** | Fluent UI 图标库 `_rc/resource.py` |
| **quicktex / PyCri / py7zr 等** | **≈ 1 MB** | **≈ 1%** | `collect_all` + 业务音频/DDS/7z 功能 |
| **自研 `.py` 业务代码** | **< 1 MB**（PYZ 内） | **< 1%** | 全部 `chuni_eventer_desktop/**/*.py` 编译进 PYZ |

**自研代码源码合计约 1.3 MB（100 个 `.py` 文件），打包后更小——把 exe 从 121 MB 压到 80 MB，不可能靠「删业务代码」，只能动依赖收集策略和资源文件。**

---

## 2. 体积从哪条打包链路进来

入口与 spec：

```14:35:ChuniEventer.spec
datas = [
    (
        str(ROOT / "chuni_eventer_desktop" / "static"),
        "chuni_eventer_desktop/static",
    ),
    (
        str(ROOT / "chuni_eventer_desktop" / "data"),
        "chuni_eventer_desktop/data",
    ),
]
# ...
for pkg in ("PyQt6", "qfluentwidgets", "qframelesswindow", "quicktex", "PIL", "PyCriCodecsEx"):
    p_d, p_bin, p_hi = collect_all(pkg)
    datas += p_d
    binaries += p_bin
    hiddenimports += p_hi
```

含义：

1. **`datas`**：把整个 `static/`、`data/` 目录原样复制进 exe（与功能绑定的 PNG/字体/AWB 模板）。
2. **`collect_all(包名)`**：把该 pip 包的 **全部** data、binary、hidden import 打进包——**不做「按需 import」裁剪**，这是 121 MB 的主因。
3. **`excludes=[]`**：当前 **没有任何排除项**。

应用启动链（决定哪些第三方一定会被加载）：

```11:19:chuni_eventer_desktop/app.py
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QWidget
# ...
from qfluentwidgets import Theme, setTheme
from .ui.main_window import MainWindow
```

`qfluentwidgets` → 依赖 `qframelesswindow` → Windows 下 `import win32gui`（见下文 §6）。

---

## 3. PyQt6：≈ 72 MB（最大头，约 60%）

### 3.1 业务代码实际用了什么

全仓库 PyQt6 import **只有 4 个子模块**：

| 子模块 | 用途 | 典型文件 |
|--------|------|----------|
| `PyQt6.QtCore` | 信号、线程、定时器 | 几乎所有 `ui/*.py` |
| `PyQt6.QtWidgets` | 窗口、布局、控件 | 同上 |
| `PyQt6.QtGui` | 图像、画笔、图标 | 头像合成、地图、卡片视图等 |
| `PyQt6.QtSvg` | SVG 渲染 | **仅** `ui/settings_about_panel.py`（`QSvgRenderer`） |

**没有**任何文件 `import PyQt6.QtQuick`、`QtMultimedia`、`QtPdf`、`QtDesigner`、`QtSql` 等。

### 3.2 但 `collect_all("PyQt6")` 打进了什么

PyQt6 在 exe 内共 **2557 个文件**，其中 `PyQt6/Qt6/` 子树 alone **≈ 72 MB**。下列 DLL **业务未直接引用**，却占体积显著：

| 文件 / 模块 | 压缩后约 | 业务是否用到 | 说明 |
|-------------|----------|--------------|------|
| `Qt6/bin/opengl32sw.dll` | **7.3 MB** | 间接 | 软件 OpenGL 回退；无独显/驱动异常时可能用到 |
| `Qt6/bin/avcodec-61.dll` | **5.8 MB** | **否** | Qt Multimedia 自带 FFmpeg，应用不做视频播放 |
| `Qt6/bin/Qt6Designer.dll` | **3.1 MB** | **否** | Qt Designer 设计器 |
| `Qt6/qml/QtQuick/` 整树 | **≈ 3.2 MB** | **否** | QML/Quick 引擎 |
| `Qt6/bin/Qt6Gui.dll` | 4.0 MB | **是** | 核心 |
| `Qt6/bin/Qt6Core.dll` | 3.5 MB | **是** | 核心 |
| `Qt6/bin/Qt6Widgets.dll` | 2.8 MB | **是** | 核心 |
| `Qt6/bin/Qt6Quick.dll` | 2.7 MB | **否** | Quick 场景 |
| `Qt6/bin/Qt6Pdf.dll` | 2.7 MB | **否** | PDF 渲染 |
| `Qt6/bin/Qt6Quick3D*.dll` | **≈ 4+ MB** | **否** | 3D Quick |
| `Qt6/bin/Qt6Qml.dll` | 2.0 MB | **否** | QML |
| `Qt6/bin/avformat-61.dll` | 1.3 MB | **否** | 同上 Multimedia |
| `Qt6/plugins/sqldrivers/` | 1.3 MB | **否** | SQLite 驱动，应用不用 QtSql |
| `Qt6/plugins/assetimporters/assimp.dll` | 0.9 MB | **否** | 3D 资产 |
| `PyQt6/bindings/*.sip` | **0.9 MB** | **否** | C++ 绑定描述，**运行时不需要** |

另外还打入了 **30+ 个 PyQt6 `.pyd`**（`QtBluetooth`、`QtNfc`、`QtPdf`、`QtDesigner`…），每个 0.02–0.26 MB，代码里均未 import。

### 3.3 代码级原因总结

```
app.py / ui/*
    └── 仅 QtCore + QtGui + QtWidgets (+ 一处 QtSvg)
ChuniEventer.spec
    └── collect_all("PyQt6")  ← 把整个 PyQt6 wheel 当黑盒全收
        └── Qt6/bin + Qt6/qml + plugins + 全部 .pyd + bindings
```

**预估可裁剪空间（需改 spec + 全量 UI 回归）**：排除 Designer / Quick / QML / Pdf / Multimedia / Sql 及相关 plugins，约 **25–40 MB**（压缩后）。

---

## 4. 自打资源：≈ 13 MB（约 11%）

来自 spec 的 `datas`，由业务代码通过固定路径读取。

### 4.1 大文件 ↔ 代码引用

| 文件 | 压缩后约 | 引用位置 | 能否删 |
|------|----------|----------|--------|
| `static/fonts/MiSans-Heavy.ttf` | **5.1 MB** | `ui/trophy_pjsk_generator_dialog.py` → `_pjsk_font_path()` | 可改子集字体或系统字体回退 |
| `data/.../systemvoice0700.awb` | **2.7 MB** | `system_voice_pack.py` → `_resolve_template_acb()` 42 槽语音模板 | **不可删** |
| `static/logo/ChuniEventer.png` | **1.7 MB** | `app.py` → `_app_icon_path()`；`settings_about_panel.py` | 可压图/换 JPG |
| `static/logo/SwanClub.jpg` | 0.6 MB | 关于页 | 可压图 |
| `data/st_dummy.afb` | 1.25 MB（未进 top 列表，在 data 内） | `stage_afb_convert.py` → Stage AFB 模板 | **不可删** |
| 其余 PNG/小 XML | < 3 MB 合计 | 各 dialog 模板图 | 多数需要 |

### 4.2 配置入口

```14:22:ChuniEventer.spec
datas = [
    (str(ROOT / "chuni_eventer_desktop" / "static"), "chuni_eventer_desktop/static"),
    (str(ROOT / "chuni_eventer_desktop" / "data"), "chuni_eventer_desktop/data"),
]
```

**代码级优化**：不必改逻辑，只需换小资源或把 `MiSans-Heavy.ttf` 子集化，即可从 exe **直接减少约 5–8 MB**。

---

## 5. Pillow：≈ 6.7 MB（约 6%）

`collect_all("PIL")` 带入全部原生扩展。体积 Top：

| 文件 | 压缩后约 | 业务是否需要 |
|------|----------|--------------|
| `PIL/_avif.cp312-win_amd64.pyd` | **4.1 MB** | **基本不需要** — 文件对话框接受 webp/png/jpeg，无 AVIF |
| `PIL/_imaging.cp312-win_amd64.pyd` | 1.0 MB | **需要** — 核心解码 |
| `PIL/_imagingft.cp312-win_amd64.pyd` | 1.0 MB | 部分需要 — FreeType（`trophy_pjsk_generator_dialog` 加载 TTF 后可能走 PIL 字体） |
| `PIL/_webp.cp312-win_amd64.pyd` | 0.2 MB | 可选 — 对话框 filter 含 `*.webp` |

业务引用 Pillow 的文件（均为 **Image 读写/缩放**，不调用 AVIF API）：

- `ui/map_add_dialog.py`、`ui/event_add_dialog.py`、`music_jacket_replace.py`、`stage_from_image.py` 等

**代码级优化**：在 spec 用 `excludes` 或手动 `binaries` 列表 **去掉 `_avif.pyd`**，约 **−4 MB**，需测一遍各图片导入流程。

---

## 6. qfluentwidgets + 无边框窗口 + pywin32：≈ 4.5 MB

### 6.1 qfluentwidgets（≈ 1.4 MB）

- 启动即 `from qfluentwidgets import Theme, setTheme`（`app.py`）。
- 最大单文件：`qfluentwidgets/_rc/resource.py` **≈ 1.21 MB**（内嵌 Fluent 图标/主题资源，**二进制形式打进 exe**）。
- 全 UI 基于 Fluent 组件（`MainWindow`、各 Dialog）。

**不能简单去掉**；若换原生 Qt Widgets 可省 ~1.4 MB，但等于重写 UI 层。

### 6.2 qframelesswindow → pywin32（≈ 3.1 MB）

依赖链：

```
app.py → qfluentwidgets
       → qframelesswindow/windows/__init__.py
       → import win32api, win32con, win32gui   # 无边框窗口、DWM 阴影
       → PyInstaller 顺带收集整个 pywin32
       → 包含 Pythonwin/mfc140u.dll（≈ 2.56 MB）← Python IDE 组件，运行时不需要
```

**代码级优化**：在 spec 里 **exclude `Pythonwin`**，或 hook 只保留 `win32gui`/`win32api`/`win32con` 所需 dll，约 **−2.5 MB**，无边框窗口功能应不受影响。

---

## 7. 功能型 Python 依赖（体积小但代码有明确用途）

| 包 | exe 内约 | 触发业务代码 | 说明 |
|----|----------|--------------|------|
| **quicktex** + `_quicktex.pyd` | ≈ 0.5 MB | `dds_quicktex.py`、`dds_convert.py`、大量 `ui/*` DDS 预览 | spec 显式 `hiddenimports` + 子进程 worker（`run_desktop.py`） |
| **PyCriCodecsEx** | ≈ 0.03 MB | `pjsk_audio_chuni.py`、`repack_system_voice_acb.py` | PJSK 音频 → ACB/AWB |
| **py7zr** | 在 PYZ 内 | `sheet_install.py` | 7z 谱面包解压，**无 7-Zip  exe 依赖** |
| **Cryptodome** | ≈ 0.96 MB | py7zr 等传递依赖 | 加密库 |

这些 **相对整个 exe 可忽略**，且与功能绑定，不建议为省 1 MB 删除。

---

## 8. 自研 Python 代码：不是体积问题

| 区域 | 源码大小 | 最大单文件 |
|------|----------|------------|
| `ui/` | ≈ 0.85 MB（49 文件） | `map_add_dialog.py` 180 KB |
| 非 UI 核心 | ≈ 0.44 MB（47 文件） | `pgko_to_c2s.py` 62 KB |
| `_suspect/` | ≈ 0.03 MB | sus 解析内部包 |

全部编译进 **7.65 MB 的 `PYZ.pyz`**（含 Python 标准库 + 所有第三方纯 Python 模块 + 应用代码）。应用自身模块在 PYZ 里通常 **只有几百 KB 量级**。

**大文件 `map_add_dialog.py` / `manager_widget.py` 等** 行数多、逻辑重，但对 exe 体积 **几乎无影响**。

---

## 9. 121 MB 结构图

```
ChuniEventer.exe  (~121 MB)
│
├─ PyQt6 完整包 ........................ ~72 MB  (60%)  ← collect_all，最大优化点
│   ├─ Qt6Core/Gui/Widgets ............. ~11 MB   ← 真正需要
│   ├─ opengl32sw ...................... ~7 MB    ← 可能需要的回退
│   ├─ Qt Multimedia (avcodec/…) ....... ~7 MB   ← 可排除
│   ├─ Qt Quick/QML/Pdf/Designer/3D ... ~15 MB  ← 可排除
│   └─ plugins + 无用 .pyd + bindings .. ~32 MB  ← 可排除
│
├─ static + data ....................... ~13 MB  (11%)  ← spec datas；MiSans/AWB/Logo
│
├─ Pillow (含 AVIF pyd) ................ ~7 MB   (6%)   ← 可去掉 AVIF
│
├─ python312.dll + PYZ + 系统 dll ...... ~10 MB  (8%)
│
├─ pywin32 (含 Pythonwin 误收) ......... ~3 MB   (3%)   ← 可 exclude Pythonwin
│
├─ qfluentwidgets 资源 ................. ~1.4 MB (1%)
│
└─ quicktex / PyCri / py7zr / 应用 .py . ~1 MB   (<1%)
```

---

## 10. 按收益排序的优化清单（针对 exe 本体）

| 优先级 | 改动位置 | 做法 | 预估节省 | 风险 |
|--------|----------|------|----------|------|
| ★★★ | `ChuniEventer.spec` | 不用 `collect_all("PyQt6")`，改 `hiddenimports` + 手动列 `QtCore/QtGui/QtWidgets/QtSvg` 与必要 plugins（`platforms/qwindows`、`imageformats`） | **25–40 MB** | 中：漏 plugin 会导致启动/贴图失败 |
| ★★★ | `ChuniEventer.spec` | `excludes` 去掉 PyQt6 的 Quick/Qml/Pdf/Designer/Multimedia/Sql 相关 | 含上项 | 同上 |
| ★★☆ | `ChuniEventer.spec` | 排除 `PIL/_avif*.pyd` | **~4 MB** | 低 |
| ★★☆ | `ChuniEventer.spec` | 排除 `Pythonwin`、PyQt6 `bindings/` | **~3.5 MB** | 低 |
| ★★☆ | 资源文件 | 子集化 `MiSans-Heavy.ttf`；压缩 `ChuniEventer.png` | **~5–7 MB** | 低（仅奖杯/关于页） |
| ★☆☆ | `ChuniEventer.spec` | `upx=True`（若杀软允许） | 10–20% 整体 | 兼容性/误报 |
| ✗ | 删 `map_add_dialog.py` 等 | — | **≈ 0** | 功能损失 |

---

## 11. spec 优化示例（方向性，未在仓库启用）

**当前问题行：**

```python
for pkg in ("PyQt6", "qfluentwidgets", "qframelesswindow", "quicktex", "PIL", "PyCriCodecsEx"):
    p_d, p_bin, p_hi = collect_all(pkg)
```

**更精细的方向（示意）：**

```python
# PyQt6：只 collect 需要的子包，而非整包
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

hiddenimports = [
    "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets", "PyQt6.QtSvg",
    # ...
]
excludes = [
    "PyQt6.QtDesigner", "PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtMultimedia",
    "PyQt6.QtPdf", "PyQt6.QtSql", "PyQt6.QtBluetooth", "PyQt6.QtNfc",
    "Pythonwin",  # pywin32 IDE，qframelesswindow 不需要
]
# datas/binaries 仅合并 qfluentwidgets、quicktex、PyCriCodecsEx、精简后的 PyQt6
```

实施前必须在干净 Windows 上跑：**启动、DDS 预览、PJSK 奖杯字体、关于页 SVG、无边框最大化、系统语音、7z 谱面安装** 全回归。

---

## 12. 自测命令

在项目根目录、已构建 `dist/ChuniEventer.exe` 后：

```powershell
.\.venv-build\Scripts\python.exe -c "
from PyInstaller.archive.readers import CArchiveReader
from collections import defaultdict
r = CArchiveReader('dist/ChuniEventer.exe')
g = defaultdict(float)
for name, ent in r.toc.items():
    if name == 'struct': continue
    n = name.replace('\\', '/')
    if n.startswith('PyQt6/'): k = 'PyQt6'
    elif 'chuni_eventer_desktop/static' in n: k = 'static'
    elif 'chuni_eventer_desktop/data' in n: k = 'data'
    elif n.startswith('PIL/'): k = 'PIL'
    elif n.startswith('qfluentwidgets'): k = 'qfluentwidgets'
    elif 'Pythonwin' in n or n.startswith('win32'): k = 'pywin32'
    elif ent[-1] == 'z': k = 'PYZ'
    else: k = 'other'
    g[k] += ent[1]
for k, v in sorted(g.items(), key=lambda x: -x[1]):
    print(f'{k:16} {v/1024/1024:6.1f} MB')
"
```

---

## 13. 相关文件

| 文件 | 与 exe 体积的关系 |
|------|-------------------|
| `ChuniEventer.spec` | 决定 collect_all / datas / excludes |
| `run_desktop.py` | 入口；quicktex 子进程分流 |
| `chuni_eventer_desktop/app.py` | 拉入 PyQt6 + qfluentwidgets |
| `chuni_eventer_desktop/dds_quicktex.py` | quicktex 子进程与 `_quicktex.pyd` |
| `chuni_eventer_desktop/system_voice_pack.py` | 引用 `data/system_voice_seed` AWB |
| `chuni_eventer_desktop/ui/trophy_pjsk_generator_dialog.py` | 引用 `MiSans-Heavy.ttf` |
| `.venv-build/.../qframelesswindow/windows/__init__.py` | 引入 pywin32 |

更完整的「懒人包 zip + `.tools`」分析见：[包体体积分析_zh.md](./包体体积分析_zh.md)。
