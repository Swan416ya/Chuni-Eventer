# Chuni Eventer Desktop v0.1.0

首个公开版本，面向 **CHUNITHM** 自制资源维护：在本地管理类 **A001** 的 `ACUS` 目录结构，并支持部分资源的生成与预览。

## 下载与运行（Windows）

1. 从 Release 附件下载 **`ChuniEventer.exe`**。
2. 将 exe 放在任意文件夹，**双击运行**（无需安装 Python）。
3. 首次启动会在 **exe 同目录** 自动创建 **`ACUS/`** 工作区及子目录；你的地图、称号、乐曲等数据请放入或生成到该目录下。

> **可选**：在程序【设置】中配置 `compressonatorcli` 路径，作为个别 DDS 解码的备选；默认优先使用内置依赖链中的 **quicktex**。

## 主要功能

- **ACUS 浏览器**：按类型浏览 Event / Map / Music / 角色 / **称号** / 名牌 / 奖励 / DDSImage，支持搜索与 **DDS 预览**（quicktex，可配 compressonator）。
- **新增资源**：角色、地图、称号、名牌、奖励；**歌曲页**可生成与官方结构一致的 **课题称号**（Expert 金 / Master 铂 / Ultima，Ultima 仅当该曲存在已启用 Ultima 谱面时生成）。
- **称号预览**：无图称号使用内置稀有度条底图 + 大号居中文字预览；有图称号仅预览 DDS 内容。
- **地图**：列表双击可编辑（读取 Map.xml 与 MapArea）。

## 技术说明

- 图形界面：**PyQt6**
- DDS（BC3 等）：**quicktex** + **Pillow**；可选 AMD Compressonator CLI

## 已知限制

- 本版本定位为本地工具，**不包含**完整游戏资源或商用素材。
- 若杀毒软件误报单文件 exe，可尝试加入信任或自行用仓库脚本重新打包。

---

感谢试用；问题与建议欢迎在 **Issues** 反馈。
