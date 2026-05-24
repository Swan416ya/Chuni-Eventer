# Chuni-Eventer v0.7.7

## 更新内容

### 修复

- **PenguinTools 报错显示**：修复 CLI 失败时错误信息被转义或无法正确展示的问题，转谱失败时可看到完整诊断内容。
- **音频转码失败**：修复烤谱 / PJSK 音频转中二流程中 FFmpeg 与 PenguinTools 协作导致的转码失败问题。

### 优化

- **烤谱转中二**：优化 Project SEKAI 谱面下载、音频裁切与 c2s 转换流程，提升稳定性与成功率。
- **懒人包 PenguinTools**：内置 **PenguinTools.CLI v1.12.0**（较 v0.7.6 所用版本更新）。

### 其他

- 课程（Course）相关编辑与地图解禁 event 等近期功能随版本一并发布。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.7
```

懒人包需使用最新 PenguinTools 时，可先下载官方 CLI 至 `tools\PenguinToolsCLI\PenguinTools.CLI.exe`，再执行：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.7 -SkipPenguinToolsCli
```

- **懒人包**：`dist\Chuni-Eventer-v0.7.7.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`
- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 从 v0.7.6 升级：建议覆盖懒人包内 `ChuniEventer.exe` 与 `.tools\PenguinToolsCLI` 目录，或整包替换。
- 建议升级前备份当前 ACUS 与自定义资源目录。
