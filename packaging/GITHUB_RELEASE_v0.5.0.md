# Chuni-Eventer v0.5.0

## 更新内容

### MapBonus（地图加速 / 自定义）

- 支持在 ACUS 内维护 **MapBonus** 相关数据：新建与编辑 MapBonus、与游戏 opt 索引联动等（导航「MapBonus」入口）。
- 地图加速机制与字段说明见仓库文档：`docs/mapBonus_地图加速机制与自定义说明.md`。

### mgxc → c2s（pgko / PenguinTools 转谱）

- **pgko.dev 下载渠道**在「乐曲新增」中恢复可用（不再置灰）。
- 下载完成后会扫描同包内 **多个难度的 `mgxc`**，尽量 **逐个转为 `c2s`**，避免只转其中一张。
- **PenguinBridge** 与 **PenguinTools.Core** 链路加固：
  - 异步解析/转换会正确等待完成，避免半成品谱面。
  - 使用上游 **`assets.json`** 初始化 `AssetManager`，避免解析元数据时空引用。
  - 发行包内附带 **self-contained** 的 `PenguinBridge`（`win-x64` 单文件发布），分发给他人时 **一般无需再装 .NET Runtime/SDK**（与 `packaging/BUILD_AND_DISTRIBUTION.md` 一致）。
- Python 侧会优先探测 `tools/PenguinBridge/.../win-x64/publish/PenguinBridge.exe`，并与 `.tools/PenguinBridge` 分发布局对齐。

### 贴图：Pillow 源转 BC3 DDS

- 图片 → **BC3(DXT5) DDS** 时，**默认优先走 Pillow 内置 DDS（DXT5）**，不依赖外部 exe，提升打包版与离线环境的成功率。
- 失败时仍可按顺序回退 **quicktex**、以及设置中配置的 **Compressonator CLI**。
- 实现见 `chuni_eventer_desktop/dds_convert.py` 中 `convert_to_bc3_dds`。

### 其它（依据近期 git 记录）

- **字库预览**：字体预览相关能力完成（便于核对字符显示）。
- **转谱与 Bridge**：持续修复 PenguinBridge / Core 加载与调用问题，并与 vendored `PenguinTools` 子模块、子依赖构建对齐。
- **版本号**：应用内显示版本与发行说明统一为 **0.5.0**（`chuni_eventer_desktop/version.py`）。

### pgko 弹窗与 UGC 引导（本版追加）

- 主弹窗顶部注明 **pgko.dev 列表**与 **mgxc→c2s** 参考作者 **[Foahh](https://github.com/Foahh)**（可点击跳转）。
- **「UGC → mgxc 说明 / 本地缓存」**：分步说明 Margrete 与 [UMIGURI 官方下载页](https://umgr.inonote.jp/en/docs/releases)；演示图为 **悬停「鼠标移到这里查看演示截图」** 时再显示；帮助文字整段展示、不再用内嵌滚动框。
- 可浏览 **`.cache/pgko_downloads`** 下含 `mgxc` 的文件夹并 **双击** 走与线上下载一致的转谱/导入流程。
- 已移除主弹窗 **「重转本地 pgko_downloads」** 一键批量按钮。

### pgko 导入封面（本版追加）

- 导入 ACUS 时封面 **必须** 来自邻近 **`.ugc`** 中的 **`@JACKET <文件名>`**，并在 **mgxc 同目录** 找到该图片；与是否经 PenguinBridge 转 `c2s` 无关，**始终在本工具内**按该文件重生成 `CHU_UI_Jacket_*.dds`（覆盖同名输出）。
- 转 DDS 前将图源 **规范为 300×300**（与「更换封面」相同流程：裁切填满再缩放），再压 BC3。

### 管理页与预览缓存（本版追加）

- **删除乐曲**时，同步删除 **`.cache/dds_preview`** 中与该曲 `musicXXXX` 目录下各 **`.dds` 文件名** 对应的预览 PNG，避免删歌后界面仍显示旧封面解码缓存。

## 打包说明

- Windows 一键打包：

```powershell
powershell -ExecutionPolicy Bypass -File ".\scripts\build_windows.ps1" -Version 0.5.0
```

- 详见 `packaging/BUILD_AND_DISTRIBUTION.md`。
- 分发目录中的 `.tools/PenguinBridge/` 为 **self-contained** 发布产物（含 `PenguinBridge.exe`、`assets.json`、`PenguinTools.Core.dll` 等）。

## 已知问题 / 提示

- `PenguinTools` 为上游 vendored 代码，本仓库为 **net8 + 语法兼容** 等本地补丁；若你自行 `git pull` 上游子模块，可能产生合并冲突，需按 `docs/mgxc_to_c2s_penguintools_源码解析与桥接实现.md` 中的构建说明处理。
- 若 Pillow 无法读取个别源图格式，仍会回退 quicktex / Compressonator；请在设置中配置可用的 DDS 工具路径。
