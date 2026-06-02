# Chuni-Eventer v0.7.9

## 更新内容

### 修复

- 修复 [#11](https://github.com/Swan416ya/Chuni-Eventer/issues/11) 报告的问题。
- 修复 [#12](https://github.com/Swan416ya/Chuni-Eventer/issues/12) 报告的问题。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.9
```

- **懒人包**：`dist\Chuni-Eventer-v0.7.9.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`
- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 从 v0.7.8 升级：懒人包建议整包替换；Lite 单 exe 可直接覆盖。
- 建议升级前备份当前 ACUS 与自定义资源目录。
