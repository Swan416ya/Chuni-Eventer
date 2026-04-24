# Chuni-Eventer v0.6.4

## 更新内容

### 本版重点

- **弹窗体系已完全重写**：统一交互与生命周期，降低与主窗口事件循环冲突导致的假死概率。若升级后仍遇到**弹窗卡死**，请带上复现步骤与日志再来反馈。
- **转谱链路调整**：自制谱相关转换已从原先自研的 **PenguinBridge** 路径，改为调用 **[PenguinTools](https://github.com/Foahh/PenguinTools)** 官方 **CLI**（与上游工具链对齐，便于跟随社区更新）。仓库说明与构建方式见：[Foahh/PenguinTools](https://github.com/Foahh/PenguinTools)。
- **SUS → C2S**：转换流程仍属实验性质、**整体仍接近不可用**，但本轮对性能做了优化，**耗时会明显缩短**。

### 其他说明

- 分发包内仍会按需附带 PenguinTools CLI 及相关资源（与既有打包策略一致）；具体以 `scripts/build_windows.ps1` 与 `packaging/BUILD_AND_DISTRIBUTION.md` 为准。

## 打包说明

- Windows 一键打包：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.6.4
```

- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 建议升级前备份当前 ACUS 与自定义资源目录。
- 若资源管理器图标显示未即时更新，可刷新或重启资源管理器后再查看。
