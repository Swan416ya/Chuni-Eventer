# Chuni-Eventer v0.7.1

## 更新内容

### 说明

- **本版分发包中暂时移除主页侧栏「装扮」入口**：装扮相关能力仍在开发中，避免用户误入未完成流程。源码仓库在发布构建后会恢复该入口，便于后续继续开发。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.1
```

- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 建议升级前备份当前 ACUS 与自定义资源目录。
