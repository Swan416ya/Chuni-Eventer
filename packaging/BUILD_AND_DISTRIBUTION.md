# Windows 打包与分发

## 前置条件（PenguinTools.CLI）

`Chuni-Eventer` 现通过 [`Foahh/PenguinTools`](https://github.com/Foahh/PenguinTools) 的 `PenguinTools.CLI` 完成 `mgxc / ugc / sus -> c2s` 转换。首次在本机构建前请执行一次：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\setup_penguin_tools.ps1"
```

该脚本会在仓库根目录准备 `PenguinTools/` 源码，供后续 `dotnet publish PenguinTools.CLI` 使用。若你的 `PenguinTools` 检出不在仓库内，可设置环境变量 `CHUNI_PENGUINTOOLS_ROOT` 指向该检出路径。

`setup_penguin_tools.ps1` 会自动执行 `submodule update --init --recursive`。此外，`build_windows.ps1` 在检测到 `External/muautils/.../mua.exe` 缺失时，会尝试从本仓库 `tools/PenguinTools/mua.exe` 自动兜底复制。

## 一行命令（推荐）

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.5.0
```

该命令会自动完成：

1. 安装/更新 `.venv-build` 构建依赖
2. 用 PyInstaller 构建 `dist/ChuniEventer.exe`
3. 发布 `PenguinTools.CLI`（`WinX64-SelfContained-SingleFile-EmbeddedAssets`）
4. 组装分发目录并打 zip

## 产物位置

- 主程序（Lite）：`dist/ChuniEventer.exe` 与 `dist/release/ChuniEventer.exe`（同一构建，推荐作为 GitHub Release 默认附件）
- 离线懒人包目录：`dist/release/Chuni-Eventer-v0.5.0/`
- 离线懒人包 zip：`dist/Chuni-Eventer-v0.5.0.zip`

### Lite 单 exe

仅 `ChuniEventer.exe`。首次运行可在 exe 同级通过「设置 → 外部工具」按需下载 `.tools`（FFmpeg、PenguinTools.CLI 等）。

### 离线懒人包（zip）

分发目录中会包含：

- `ChuniEventer.exe`
- `.tools/ffmpeg/bin/ffmpeg.exe`（**不含 ffprobe**，应用未使用）
- `.tools/PenguinToolsCLI/`（self-contained，含 `PenguinTools.CLI.exe`）
- `.tools/PenguinTools/`（含 `mua.exe` 等 Stage 资源，若存在）
- （**默认不含**）`.tools/CompressonatorCLI/` — exe 内已带 quicktex；需离线 DDS 回退时用 `-IncludeCompressonator` 构建
- （若存在）对应版本的 `GITHUB_RELEASE_vX.Y.Z.md`

## 可选参数

- `-Version 0.5.0`：设置分发目录和 zip 的版本号
- `-SkipPyInstaller`：跳过主程序构建（仅重组装懒人包）
- `-SkipPenguinToolsCli`：跳过 `PenguinTools.CLI` 发布与打包（保留旧参数名 `-SkipBridge` 作为别名）
- `-IncludeCompressonator`：懒人包额外打入 Compressonator CLI（约 +147 MB；默认关闭）
- `-SkipCompressonator`：与旧脚本兼容；显式跳过 Compressonator（默认已跳过，一般无需再传）

## 校验建议

打包后建议在一台干净环境做最小验证：

1. 启动 `ChuniEventer.exe`
2. 确认静态图片资源正常显示
3. 在 pgko 或 PJSK 转谱流程中确认实际后端显示为 `PenguinTools.CLI`

> 说明：`PenguinTools.CLI` 采用 self-contained 发布，分发给最终用户时通常不需要额外安装 .NET Runtime / SDK。
