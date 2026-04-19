# 桌面端：模态弹窗与进度条安全 — 完整操作指南

> **归类**：`docs/界面与工作区/` — 与 `ui_style_inventory_zh.md`、`ui_main_workspace_fluent_gaps_zh.md` 同属「桌面 PyQt6 / Fluent UI」文档。  
> **路径约定**：下文凡未写绝对路径的，均相对于**仓库根目录**。

---

## 目录

| 章节 | 内容 |
|------|------|
| [1. 文档目的与适用范围](#1-文档目的与适用范围) | 要解决什么问题、技术栈 |
| [2. 现象与本质](#2-现象与本质) | 「假死」、系统提示音 |
| [3. 集中 API 与必须遵守的操作](#3-集中-api-与必须遵守的操作) | `fluent_dialogs` 全量说明 |
| [4. 根因分类（排查理论）](#4-根因分类排查理论) | 无边框 + 进度条、禁用父窗、连环模态等 |
| [5. 排查清单（接到用户报告时）](#5-排查清单接到用户报告时) | 按顺序检查 |
| [6. 手段小结表](#6-手段小结表) | 不改变 Fluent 外观的修复手段 |
| [7. 源码与调用关系索引](#7-源码与调用关系索引) | 文件职责 |
| [8. Code Review 检查项](#8-code-review-检查项) | 新增功能时自检 |
| [9. 调试与日志](#9-调试与日志) | `logging`、临时打点 |

---

## 1. 文档目的与适用范围

本指南汇总桌面端与**弹窗、模态、`QProgressDialog`**相关的：

- **现象**（点击只响系统音、看似必须杀进程）；
- **根因**（Qt / Win32 模态与启用状态）；
- **仓库内已落地的集中封装**（统一调用方式，减少漏写）；
- **排查步骤**与**Code Review 检查项**。

**技术栈**：PyQt6、`qframelesswindow`（`FramelessDialog`）、`qfluentwidgets`（`MSFluentWindow`、`MessageBox`）、无边框 `FluentCaptionDialog`。

**非目标**：不改变 Fluent 视觉样式；不讨论游戏数据业务规则。

---

## 2. 现象与本质

用户感知为「整个程序死了」，但进程仍在跑；在 Windows 上常表现为：

- 点击主窗口或弹窗区域**无反应**，只有**嘟**一声（系统默认错误音）；
- 任务管理器里进程未崩溃，只能结束任务。

这通常**不是业务死循环**，而是 **输入被 Qt / Win32 的模态或启用状态挡住**：系统认为当前应交给某个模态窗口，但该窗口不可见、被压在下面、或父链处于 `setEnabled(False)`，导致事件无法落到可交互控件上。

---

## 3. 集中 API 与必须遵守的操作

实现位置：**`chuni_eventer_desktop/ui/fluent_dialogs.py`**。

### 3.1 消息框（Fluent `MessageBox`）

| API | 行为摘要 | 何时使用 |
|-----|----------|----------|
| `fly_message(parent, title, text, *, single_button=True)` | 单按钮或双按钮信息框；`WindowModal`；内部经 `_normalize_parent`、`_run_modal_with_enabled_top` | 一般提示、完成说明 |
| `fly_warning` / `fly_critical` | 等价于带单按钮的 `fly_message` | 警告 / 错误文案 |
| `fly_question(parent, title, text, *, yes_text, no_text)` | 是/否；返回 `bool`；同上套壳 | 删除前确认等 |
| `fly_message_async(..., *, window_modal=False)` | `open()` 非阻塞；可选 `WindowModal`；`window_modal` 且顶层禁用时会在 `open` 前启用顶层 | 已有模态 `exec` 时仅需提示、避免再叠一层同步 `exec` |

**内部机制（无需业务重复实现）**：

- **`_normalize_parent(parent)`**  
  使用 `parent.window()` 作为 `MessageBox` 的父对象，避免非顶层窗口上的模态 glitch。

- **`_run_modal_with_enabled_top(parent, fn)`**（`fly_message` / `fly_question` 使用）  
  - 若 `parent.window()` 顶层 **`setEnabled(False)`**，在 `MessageBox.exec()` **之前**对该顶层 **`setEnabled(True)`**。  
  - **不在**关闭后再把顶层设回 `False`（否则提示结束后整窗仍禁用，用户无法点「取消」等）。  
  - 在 `finally` 中对顶层 **`raise_()`、`activateWindow()`**，减轻焦点留在「幽灵层」上的问题。

**开发规范**：

- 业务提示、确认 **一律优先** 使用 `fly_*`，**不要**直接 `MessageBox(...).exec()`（除非有充分理由且自行处理父窗启用与 parent 层级）。
- 在**已有** `QDialog.exec()` 仍打开时，若只需告知、不必阻塞业务逻辑，优先 **`fly_message_async`** 或 **`QTimer.singleShot(0, lambda: fly_*(...))`** 延迟到当前 `exec` 返回后再弹同步框。

### 3.2 进度条（`QProgressDialog` + 无边框父窗）

| API | 行为摘要 | 何时使用 |
|-----|----------|----------|
| `safe_dismiss_modal_progress_dialog(dlg)` | 对非空 `dlg`：`reset()` → `setWindowModality(NonModal)` → `close()` → `deleteLater()` → `QApplication.processEvents()`；任一步对象已销毁则安全返回 | **任何**曾 `setWindowModality(WindowModal)` 的 `QProgressDialog` 在结束路径上**必须**调用，禁止手写半截收尾 |

**当前仓库中的调用方**（新增进度 UI 应对齐）：

- `chuni_eventer_desktop/ui/dds_progress.py` — `run_bc3_jobs_with_progress`
- `chuni_eventer_desktop/ui/index_progress.py` — `run_rebuild_game_index_with_progress` 的 `finally`
- `chuni_eventer_desktop/ui/map_add_dialog.py` — `_warm_game_dds_preview_cache`
- `chuni_eventer_desktop/ui/swan_sheet_download_dialog.py` — `_close_progress`

### 3.3 异步消息框的日志

`fly_message_async` 使用 **`logging.getLogger(__name__).debug`** 打点（创建 / finished / destroyed）。需要排查时把 logger `chuni_eventer_desktop.ui.fluent_dialogs` 调到 DEBUG 即可，无需改代码。

---

## 4. 根因分类（排查理论）

### 4.1 无边框父窗口 + `QProgressDialog` 的 `WindowModal` 残留

无边框主窗口 / 对话框（`FramelessDialog` / `FluentCaptionDialog`）与原生 `QProgressDialog` 组合时，若关闭进度条后未彻底解除模态，可能留下**看不见的模态层**，后续 `MessageBox` 或主界面都无法正常接收点击。

**对策**：一律在结束路径调用 **`safe_dismiss_modal_progress_dialog`**（见 §3.2）。

### 4.2 父窗口 `setEnabled(False)` 期间同步模态 `MessageBox`

整窗禁用（例如后台线程工作时防误触）时，若在禁用状态下仍 `MessageBox.exec()`，在 Windows 上极易出现**模态框无法点击 + 全局提示音**。

**对策**：经 **`fly_*`** 弹出即可；内部由 **`_run_modal_with_enabled_top`** 在 `exec` 前启用顶层（见 §3.1）。典型场景：`pjsk_hub_dialog.py` 的 `PjskInstallToAcusDialog`（`_run` 中 `setEnabled(False)`）。

### 4.3 连环模态（`exec()` 套 `exec()`）

大弹窗 `exec` 未返回时再同步 `fly_message` / `fly_question`，会形成多层模态，部分环境下 **Z-order / 焦点错乱**。

**对策**：见 §3.1 的 `fly_message_async` 与 `QTimer.singleShot`；确认与 **`QProgressDialog` 的 `WindowModal` 不重叠**：先 **`safe_dismiss_modal_progress_dialog`**，再弹 `fly_*`。

### 4.4 `MessageBox` 的 parent 不是顶层

绕过 `_normalize_parent`、把非顶层 widget 当作 parent，可能引发模态与层级问题。

**对策**：统一走 **`fly_*`**。

### 4.5 原生 `QMessageBox` 与 Fluent 混用

`map_add_dialog.py` 等仍使用 `QMessageBox.question` / `information`。一般可用，但在个别系统上与无边框 Fluent 窗体的**激活顺序**可能不一致。若需与 Fluent 父链完全一致，可逐步改为 **`fly_question` / `fly_message`**（视觉仍为 Fluent 消息框）。

### 4.6 非 UI 线程直接弹窗

`fly_*`、`QMessageBox`、`QDialog.exec()` **必须在主线程**调用。工作线程只发 **`pyqtSignal`**，由槽函数在主线程弹窗。

---

## 5. 排查清单（接到用户报告时）

1. **复现路径**：是否刚结束进度条、刚完成线程回调、或刚关掉某个子对话框？  
2. **检索**：`setEnabled(False)`、`QProgressDialog`、`\.exec\(`、`fly_message`、`fly_question` 在同一流程中的先后顺序。  
3. **系统层面**：任务栏 / 工具是否显示仍有不可见顶层模态窗？  
4. **临时诊断**：对 `parent`、`parent.window().isEnabled()`、`QApplication.activeModalWidget()` 打点；或将 `fluent_dialogs` 的 logger 调到 DEBUG（见 §3.3）。  
5. **已知规避案例**：`manager_widget.py` 中更换场景背景流程后，注释说明 **`MessageBox after this flow can lock interaction`**，当前选择**不弹窗**；若未来要加提示，应优先 **`QTimer.singleShot` 延迟** 或 **`fly_message_async`**，并确保前一个对话框已 `deleteLater` 且已 **`safe_dismiss_modal_progress_dialog`**（若刚用过进度条）。

---

## 6. 手段小结表

| 手段 | 作用 | 对 Fluent 外观影响 |
|------|------|-------------------|
| `safe_dismiss_modal_progress_dialog` | 消除进度条隐形模态层 | 无 |
| `fly_*` + `_run_modal_with_enabled_top` | 顶层禁用时先启用再 `exec`；结束后 `raise_` / `activateWindow` | 无 |
| `fly_message_async` / 延迟 `fly_*` | 减轻连环模态 | 无 |
| `fly_*` + `_normalize_parent` | 稳定 parent / 顶层 | 无 |
| 禁止在工作线程直接弹窗 | 避免未定义行为 | 无 |

---

## 7. 源码与调用关系索引

| 路径 | 说明 |
|------|------|
| `chuni_eventer_desktop/ui/fluent_dialogs.py` | `fly_*`、`safe_dismiss_modal_progress_dialog`、`_normalize_parent`、`_run_modal_with_enabled_top` |
| `chuni_eventer_desktop/ui/fluent_caption_dialog.py` | `FluentCaptionDialog` → `FramelessDialog` |
| `chuni_eventer_desktop/ui/dds_progress.py` | BC3 进度；结束处 `safe_dismiss_modal_progress_dialog` |
| `chuni_eventer_desktop/ui/index_progress.py` | 游戏索引扫描进度；同上 |
| `chuni_eventer_desktop/ui/map_add_dialog.py` | ddsMap 预览缓存进度；同上 |
| `chuni_eventer_desktop/ui/swan_sheet_download_dialog.py` | 列表/安装进度；`_close_progress` |
| `chuni_eventer_desktop/ui/pjsk_hub_dialog.py` | `PjskInstallToAcusDialog`：整窗 `setEnabled(False)` 期间依赖 `fly_*` 集中保险 |
| `chuni_eventer_desktop/ui/manager_widget.py` | 场景更换后刻意避免 MessageBox 的注释与实现 |

---

## 8. Code Review 检查项

新增或修改涉及 UI 的代码时，建议逐项确认：

- [ ] 用户可见提示是否走 **`fly_*`**（或已论证为何不走且父窗启用正确）？  
- [ ] 凡 `QProgressDialog` 曾设为 **`WindowModal`**，结束路径是否调用 **`safe_dismiss_modal_progress_dialog`**？  
- [ ] 是否在**工作线程**里调用了任何 `fly_*` / `exec` / `QMessageBox`？（应为否）  
- [ ] 在**已有** `exec()` 未返回时，是否叠了同步 `fly_message`？（若仅需告知，改为 `fly_message_async` 或 `QTimer.singleShot`）  
- [ ] 若仍使用原生 `QMessageBox`，是否评估过与无边框父窗的焦点行为？

---

## 9. 调试与日志

- 将 logger **`chuni_eventer_desktop.ui.fluent_dialogs`** 设为 **DEBUG**，可观察 `fly_message_async` 的生命周期日志。  
- 若怀疑残留模态，可在关键点打印 **`QApplication.activeModalWidget()`** 的类型与 `windowTitle`。

---

*本文与 `chuni_eventer_desktop/ui/fluent_dialogs.py` 当前实现同步维护；修改集中封装时请同步更新 §3、§7。*
