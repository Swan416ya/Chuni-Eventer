# PenguinTools.CLI 接入说明

Chuni-Eventer 通过 PenguinTools.CLI 将 MGXC、UGC 和 SUS 转为 c2s，并调用 `option build` 打包谱面与媒体资源。
当前支持官方 UGC v9 和二进制 MGXC v4，格式语义与转换限制见上游[转谱文档](https://github.com/ChuniPingu/PenguinTools/blob/main/docs/chart-conversion.md)。

## 安装与更新

在「设置 → 外部工具」中下载或重新下载 PenguinTools.CLI。应用优先查询上游最新正式版，查询失败时使用代码中指定的兜底版本。
已安装旧版的用户需要重新下载，或手动选择新版 `PenguinTools.CLI.exe`。

手动安装时，从 [PenguinTools Releases](https://github.com/ChuniPingu/PenguinTools/releases) 下载 `PenguinTools.CLI.v*.AOT.zip`，
将整包解压到 `<应用根>/.tools/PenguinToolsCLI/`。Native AOT 包无需单独安装 .NET 运行时。

请保留完整发布目录，包括 `assets/`、原生库与许可证文件。音频使用随包提供的 ffmpeg；图片处理使用 texconv、image-tools 及其 libvips 库。

## CLI 路径

可在「设置 → 外部工具」选择可执行文件，或设置环境变量：

```powershell
$env:CHUNI_PENGUINTOOLS_CLI = "C:\tools\PenguinToolsCLI\PenguinTools.CLI.exe"
```

默认安装位置为 `<应用根>/.tools/PenguinToolsCLI/PenguinTools.CLI.exe`。
源码运行时也会查找 `tools/PenguinToolsCLI/`、仓库内或同级 PenguinTools 的 CLI 发布目录；具体顺序见 `chuni_eventer_desktop/penguin_tools_cli.py`。

## 从源码构建

在 Chuni-Eventer 仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_penguin_tools.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

准备最新 PenguinTools 源码、其要求的 .NET SDK 与 Native AOT 编译环境，详见上游[开发文档](https://github.com/ChuniPingu/PenguinTools/blob/main/docs/development.md)。
`setup_penguin_tools.ps1` 会复用本机已有源码或克隆上游；复用时请先将该源码更新到所需版本。
可通过 `CHUNI_PENGUINTOOLS_ROOT` 指定源码目录。

打包脚本使用 `WinX64-NativeAOT` 发布配置，并复制完整 CLI 发布目录。
使用已解压到 `tools/PenguinToolsCLI/` 的正式发布包时，可传 `-SkipPenguinToolsCli` 跳过源码编译。

## 转谱入口

- PGKO 导入优先选择 MGXC；UGC 直转仍需在「设置」中开启实验性选项。
- 谱面转换调用 `chart convert`；PJSK 打包调用 `option build`。
- 调用结果使用 CLI 的 NDJSON `type=result` 与 `schemaVersion 4`；失败时显示 CLI 诊断。
