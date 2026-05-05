# Chuni-Eventer v0.7.0

## 更新内容

### 本版重点

- **新增系统语音相关功能**，便于在 ACUS 内管理系统语音资源与配置。
- **修复读取文件时卡死的问题**，提升大文件或批量扫描场景下的响应与稳定性。
- **新增单地图打包功能**，可将单张地图及其依赖整理为便于分发或迁移的包。
- **角色变体输入框已锁死**，避免误改变体编号导致与资源目录不一致。

### 视频介绍

- 功能演示与版本介绍见：[Bilibili：Hye?! 中二节奏神人语音包预览 & ChuniEventer 新版本介绍](https://www.bilibili.com/video/BV1soRCBvE5M)

## 打包说明

- Windows 一键打包：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.0
```

- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 建议升级前备份当前 ACUS 与自定义资源目录。
