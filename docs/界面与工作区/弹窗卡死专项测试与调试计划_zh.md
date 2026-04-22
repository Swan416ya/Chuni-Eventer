# 弹窗卡死专项测试与调试计划（全局）

> 目标：不删除必要确认弹窗，在保持 Fluent 样式前提下定位并稳定修复「点击只响系统音、必须杀进程」问题。  
> 关联文档：  
> - 规范：`桌面端模态弹窗与进度安全_完整指南_zh.md`  
> - 台账：`弹窗问题排查修复记录_zh.md`

---

## 1. 当前全局策略（已实施）

- **高风险删除链路改为异步确认**：`manager_widget.py` 中删除乐曲/称号/任务/角色统一改用 `fly_question_async(...)`，保留确认弹窗但避免 `exec()` 嵌套。
- **菜单触发链路延迟**：右键菜单动作仍保留 `QTimer.singleShot(80, ...)`，避免 `RoundMenu.exec()` 动画与弹窗抢事件循环。
- **弹窗父窗口收敛**：`_normalize_parent` 仅接受真正顶层窗口（`isWindow()` 且 `parentWidget() is None`）。
- **去掉强制激活窗口**：不再 `raise_()/activateWindow()`，避免触发 `must be a top level window`。
- **缓存预览兜底**：`dds_preview` 按 DDS/PNG 时间戳自动重建，避免旧 pngcache 串图。

---

## 2. 专项测试矩阵（建议按顺序）

### A. 管理页删除链路（最高优先）

1. 角色页：右键角色 -> 删除角色 -> 取消 -> 再次删除 -> 确定。  
2. 称号页：删除称号（仅称号）与“删除称号并删除关联角色”两条路径。  
3. 任务页：删除任务确认 -> 确定。  
4. 歌曲（表格与卡片两个入口）：删除乐曲 -> 确定。  

**通过标准**：确认框始终可点击；关闭后主界面可继续交互；无系统提示音锁死。

### B. 角色变体链路

1. 变体标签右键删除（无确认版）-> 连续删除多个变体。  
2. 变体新增（打开 `CharaAddDialog`）-> 成功写入 -> 返回。  

**通过标准**：流程结束后主窗口可继续点击，Tab 切换正常。

### C. 进度条与弹窗交错

1. 新增角色触发 DDS 编码进度 -> 结束后立即执行删除确认。  
2. 地图编辑保存（含进度/提示）后立刻删除角色或任务。  

**通过标准**：进度结束后不会残留“隐形模态层”；后续确认框可用。

---

## 3. 需要采集的调试信息（已加代码）

### 3.1 一键开启诊断日志

启动前设置环境变量：

- PowerShell（当前会话）：
  - `$env:CHUNI_DIALOG_DEBUG='1'`
  - `python -m chuni_eventer_desktop`

日志输出文件：

- `.cache/logs/dialog_debug.log`

### 3.2 已记录字段

`fluent_dialogs.py` 会记录：

- 创建/结束阶段：`before_modal_exec`、`after_modal_exec`、`fly_*:create/finished`
- `parent` 类型、归一后的 `top` 类型与 `top_enabled`
- 当前 `active_modal` 类型与标题
- `fly_question_async` 的最终 `accepted=True/False`

这些信息足以回答三个关键问题：

1. 弹窗创建时 parent/top 是否异常；
2. 卡死时是否存在残留 activeModal；
3. 用户点击后回调是否实际触发（确认结果是否回传）。

---

## 4. 如果仍复现，下一步执行顺序

1. 先提交复现时刻前后 30 秒的 `dialog_debug.log` 片段。  
2. 对照日志中的 `active_modal` 与 UI 截图，判断是否有隐藏模态残留。  
3. 若残留来自某固定模块（如 `works_dialogs` / `github_sheet_dialog` / `pgko_sheet_download_dialog`），优先把该模块的同步 `fly_question` 迁移到 `fly_question_async`。  
4. 若残留来自系统对话框（`QFileDialog` / `QInputDialog`）后续链路，则对该链路引入 `QTimer.singleShot(80~120, ...)` 过渡再开下一个弹窗。

---

## 5. 验收标准（本阶段）

- 不删必要确认弹窗；  
- `manager_widget` 的删除相关确认路径连续操作 20 次以上无卡死；  
- 日志中无反复 `must be a top level window`；  
- 无“点击只响系统音”且无需杀进程。

---

*维护建议：每次新增确认弹窗路径时，先按本文件 §2 跑最小回归，再更新 `弹窗问题排查修复记录_zh.md` 的“改动表”。*
