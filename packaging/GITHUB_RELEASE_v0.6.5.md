# Chuni-Eventer v0.6.5

## 更新内容

### 本版重点

- **修复读取游戏目录时闪退的问题**，提升配置游戏数据目录后的稳定性。

## 打包说明

- Windows 一键打包：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.6.5
```

- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 建议升级前备份当前 ACUS 与自定义资源目录。
