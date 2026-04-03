# Windows 打包与分发

## 前置条件（PenguinBridge）

`PenguinBridge` 依赖 [`Foahh/PenguinTools`](https://github.com/Foahh/PenguinTools) 中的 `PenguinTools.Core`。首次在本机构建前请执行一次：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\setup_penguin_tools.ps1"
```

若跳过此步骤，`dotnet build tools/PenguinBridge/...` 会直接报错（避免生成不含 Core 的“空壳” `PenguinBridge.exe`）。

## 一行命令（推荐）

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.4.3
```

该命令会自动完成：

1. 安装/更新 `.venv-build` 构建依赖
2. 用 PyInstaller 构建 `dist/ChuniEventer.exe`
3. 构建 `tools/PenguinBridge`（C# bridge，需已准备 PenguinTools）
4. 组装分发目录并打 zip

## 产物位置

- 主程序：`dist/ChuniEventer.exe`
- 分发目录：`dist/release/Chuni-Eventer-v0.4.3/`
- 分发压缩包：`dist/Chuni-Eventer-v0.4.3.zip`

分发目录中会包含：

- `ChuniEventer.exe`
- `.tools/PenguinBridge/` 目录下 **net8.0 发布输出的全部运行文件**（含 `PenguinBridge.exe`、`PenguinTools.Core.dll` 及依赖 dll，不含 pdb）
- （若存在）对应版本的 `GITHUB_RELEASE_vX.Y.Z.md`

## 可选参数

- `-Version 0.4.3`：设置分发目录和 zip 的版本号
- `-SkipPyInstaller`：跳过主程序构建（仅重组装）
- `-SkipBridge`：跳过 bridge 构建（仅在已存在 bridge 产物时使用）

## 校验建议

打包后建议在一台干净环境做最小验证：

1. 启动 `ChuniEventer.exe`
2. 确认静态图片资源正常显示
3. 在 pgko 转码提示中确认后端显示为 `C#(PenguinBridge)`（而非 Python 回退）
