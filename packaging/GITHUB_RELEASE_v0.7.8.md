# Chuni-Eventer v0.7.8

## 更新内容

### 新功能

- **企鹅披风（装扮 category=7）**：新增披风合成与写入 ACUS 流程（1024 对齐编辑、Tex/Icon DDS 与 XML）。
- **PGKO 自动导入自定义背景**：从 PGKO 谱面导入时，可一并写入自定义 Stage 背景资源。

### 修复

- **PGKO 转谱**：转谱逻辑全面交由 **PenguinTools** 处理，修复此前本地转换与 CLI 行为不一致的问题。
- **PenguinTools 找不到音频**：修复部分环境下转谱时音频路径解析失败的问题。
- **PenguinTools Stage 参数**：修复舞台相关参数传递错误导致的转换异常。
- **MusicSort**：修复乐曲排序相关逻辑问题。

### 优化

- **启动速度 3.0**：进一步优化冷启动路径（含可选 `CHUNI_STARTUP_PROFILE=1` 启动耗时埋点，便于排查）。
- **组曲弹窗**：调整新增组曲相关弹窗样式。
- **懒人包 PenguinTools**：内置 **PenguinTools.CLI v1.12.1**（较 v0.7.7 的 v1.12.0 更新）。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.8
```

- **懒人包**：`dist\Chuni-Eventer-v0.7.8.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`
- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 从 v0.7.7 升级：若使用懒人包，建议整包替换；Lite 版首次运行可能仍需下载 `.tools`。
- 建议升级前备份当前 ACUS 与自定义资源目录。
