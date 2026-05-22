# Chuni-Eventer v0.7.6

## 更新内容

### 修复

- **#7 关于 pgko 的谱面导入**：修复导入后音乐与谱面不同步、总是差一截的问题。
- **#8 pjsk 称号 bug**：修复生成后找不到图片、称号描边粗细无法调整等问题。

### 性能与体积

- **启动速度优化**：缩短冷启动等待时间，减少不必要的初始化开销。
- **包体体积缩小**：精简 PyInstaller 打包内容（排除未使用的 PyQt6 子模块等），Lite exe 与懒人包整体更小；懒人包默认不再预装 Compressonator（exe 内已有 quicktex，需要完整离线 DDS 回退时可使用 `-IncludeCompressonator` 构建）。

### 新功能：游戏内数据

- **游戏内数据读取更新**：设置中可扫描并索引本机游戏安装目录的数据包。
- **预览与提取**：
  - 支持预览、导出游戏内**角色立绘**；
  - 支持预览、导出游戏内**乐曲音频**。

### 其他

- 烤称号生成器回填逻辑修复。
- 部分界面去掉多余灰底，观感更干净。

## 打包说明

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.7.6
```

- **懒人包**：`dist\Chuni-Eventer-v0.7.6.zip`
- **Lite 单 exe**：`dist\release\ChuniEventer.exe`（适合上传 GitHub Release）
- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。

## 升级提示

- 若使用 Lite 版且尚未安装 `.tools`，首次启动可能需联网下载 FFmpeg 等依赖。
- 更换游戏目录或游戏更新后，请在设置 → 游戏数据中重新扫描。
- 建议升级前备份当前 ACUS 与自定义资源目录。
