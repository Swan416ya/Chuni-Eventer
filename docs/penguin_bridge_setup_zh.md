# PenguinBridge 接入说明

目标：让 `mgxc -> c2s` 优先走 C#（PenguinTools.Core）转换内核，Python 仅调用桥接程序。

参考项目：[`Foahh/PenguinTools`](https://github.com/Foahh/PenguinTools)

## 0. 必须先准备 PenguinTools.Core（重要）

`PenguinBridge.exe` **不是**独立单文件：它依赖 `PenguinTools.Core` 项目编译出的 `PenguinTools.Core.dll` 及传递依赖。若本地没有克隆 Foahh/PenguinTools，你会在运行 bridge 时看到：

- `PenguinTools.Core is not loaded`（退出码 4）

或构建时报：

- `未找到 PenguinTools.Core`（MSBuild 直接失败，避免生成“空壳” exe）

### 一键克隆（推荐）

在仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\setup_penguin_tools.ps1"
```

会在本仓库下创建 `PenguinTools/`（内容来自 GitHub）。

### 手动克隆

任选一种目录布局（二选一即可）：

1. **仓库内**：`Chuni-Eventer/PenguinTools/PenguinTools.Core/PenguinTools.Core.csproj`
2. **与仓库同级**：`<上级目录>/PenguinTools/PenguinTools.Core/PenguinTools.Core.csproj`

## 1. 构建 Bridge

```powershell
dotnet build "tools/PenguinBridge/PenguinBridge.csproj" -c Release
```

输出目录（示例）：

- `tools/PenguinBridge/bin/Release/net8.0/PenguinBridge.exe`
- 同目录下还应有 `PenguinTools.Core.dll` 以及其它依赖 dll（由 dotnet 自动复制）

## 2. Python 侧识别路径

`pgko_cs_bridge.py` 会按顺序查找 `PenguinBridge.exe`：

1. 环境变量 `CHUNI_PENGUIN_BRIDGE`
2. `<应用根>/.tools/PenguinBridge/PenguinBridge.exe`
3. `tools/PenguinBridge/bin/Release/net8.0/PenguinBridge.exe`
4. 以及若干 cwd / exe 目录候选

可选：若你把 `PenguinTools.Core.dll` 放在与 `PenguinBridge.exe` 不同目录，可设置：

- `CHUNI_PENGUIN_TOOLS_CORE_DLL`：指向 `PenguinTools.Core.dll` 的完整路径（bridge 会 `Assembly.LoadFrom`）

## 3. 分发打包注意

使用 `scripts/build_windows.ps1` 时，会把 `net8.0` 输出目录内**除 pdb 外的全部文件**复制到 `.tools/PenguinBridge/`，避免只复制 exe 而漏掉 `PenguinTools.Core.dll`。

## 4. 当前行为

- `convert_pgko_chart_pick_to_c2s(...)` 会先尝试调用 `PenguinBridge.exe`
- bridge 调用失败时，才会回退 Python 实现（开发期兜底）
