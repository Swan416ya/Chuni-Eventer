# PenguinBridge 接入说明

目标：让 `mgxc -> c2s` 优先走 C#（PenguinTools.Core）转换内核，Python 仅调用桥接程序。

参考项目：[`Foahh/PenguinTools`](https://github.com/Foahh/PenguinTools)

## 1. 准备目录

推荐将 PenguinTools 仓库放到本项目同级目录，例如：

- `E:/Python Project/Chuni-Eventer`
- `E:/Python Project/PenguinTools`

当前 `tools/PenguinBridge/PenguinBridge.csproj` 默认按此结构引用：

- `../../../PenguinTools/PenguinTools.Core/PenguinTools.Core.csproj`

若目录不同，请手动修改 `ProjectReference` 路径。

## 2. 构建 Bridge

在仓库根目录执行：

```powershell
dotnet build "tools/PenguinBridge/PenguinBridge.csproj" -c Release
```

默认输出：

- `tools/PenguinBridge/bin/Release/net8.0/PenguinBridge.exe`

## 3. Python 侧识别路径

`pgko_cs_bridge.py` 会按顺序查找：

1. 环境变量 `CHUNI_PENGUIN_BRIDGE`
2. `.tools/PenguinBridge/PenguinBridge.exe`
3. `tools/PenguinBridge/bin/Release/net8.0/PenguinBridge.exe`
4. 根目录 `PenguinBridge.exe`

建议设置环境变量最稳：

```powershell
$env:CHUNI_PENGUIN_BRIDGE="E:/Python Project/Chuni-Eventer/tools/PenguinBridge/bin/Release/net8.0/PenguinBridge.exe"
```

## 4. 当前行为

- `convert_pgko_chart_pick_to_c2s(...)` 会先尝试调用 `PenguinBridge.exe`
- bridge 调用失败时，才会回退 Python 实现（开发期兜底）
