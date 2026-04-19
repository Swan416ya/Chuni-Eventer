# 界面与工作区（桌面端 PyQt6 / Fluent）

本目录存放 **Chuni Eventer 桌面端** 的界面说明、样式清单、交互缺口与**模态/弹窗安全**等与 UI 直接相关的文档，便于与「谱面 / UGC / 资源打包」等主题区分。

---

## 文档一览

| 文档 | 说明 |
|------|------|
| [桌面端模态弹窗与进度安全_完整指南_zh.md](./桌面端模态弹窗与进度安全_完整指南_zh.md) | **弹窗假死、系统提示音、进度条残留模态**；`fluent_dialogs` 全部 API；排查清单与 Code Review 项 |
| [ui_style_inventory_zh.md](./ui_style_inventory_zh.md) | 各窗口/对话框所用 Fluent 组件与 Qt 回退件清单 |
| [ui_main_workspace_fluent_gaps_zh.md](./ui_main_workspace_fluent_gaps_zh.md) | 主工作区与 Fluent 设计之间的已知差距与待办 |

---

## 在整库 `docs/` 中的位置

仓库根目录 **`docs/`** 下按**业务主题**分子目录（如 `谱面转换与格式/`、`UGC与桥接/`、`界面与工作区/` 等）。**桌面端 UI 专项**以本目录为入口；顶层 **`docs/README.md`** 提供全库文档地图。
