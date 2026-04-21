# 弹窗问题排查与修复记录

> **维护说明**：本文件记录**已发生的根因、改动的代码与验证要点**，便于回归与 Code Review。  
> **操作规范与 API 说明**见同目录 [桌面端模态弹窗与进度安全_完整指南_zh.md](./桌面端模态弹窗与进度安全_完整指南_zh.md)。

**最后全量排查**：2026-04（`chuni_eventer_desktop/ui/` 下弹窗相关用法逐项对照）

---

## 1. 问题现象（用户侧）

| 现象 | 可能技术原因 |
|------|----------------|
| 点击无反应，仅系统提示音（Windows） | 模态层级错乱、父窗 `setEnabled(False)` 上叠 `MessageBox`、`QProgressDialog` 残留 `WindowModal` |
| 控制台 `must be a top level window` | `MessageBox` 等使用了非顶层 `QWidget` 作为父对象 |
| 右键菜单后立即弹窗无法点 | `RoundMenu.exec()` 未结束就与同步 `exec()` 抢事件循环 |

---

## 2. 集中封装（长期对策）

| 位置 | 作用 |
|------|------|
| `ui/fluent_dialogs.py` | `fly_message` / `fly_warning` / `fly_critical` / `fly_question` / `fly_message_async`；`_normalize_parent` 向上解析**真正顶层窗口**；`_run_modal_with_enabled_top` 在 `exec` 前启用顶层、结束后 `raise_`/`activateWindow` |
| `safe_dismiss_modal_progress_dialog` | 统一关闭曾 `WindowModal` 的 `QProgressDialog`，避免「隐形模态层」 |

**约定**：业务提示尽量只走 `fly_*`；进度条结束必须走 `safe_dismiss_modal_progress_dialog`。

---

## 3. 修复记录（按时间线，新在上）

### 2026-04 — 全量排查与本轮补丁

**扫描范围**：`chuni_eventer_desktop/ui/*.py` 中 `exec(`、`QMessageBox`、`QProgressDialog`、`fly_*`、`RoundMenu`/`menu.exec`、`setEnabled(False)`。

| 改动 | 文件 | 说明 |
|------|------|------|
| 去除最后两处原生 `QMessageBox` | `map_add_dialog.py` | 「空格子」确认改为 `fly_question`；地图生成完成改为 `fly_message`，与 Fluent 父链及启用逻辑一致 |
| 右键菜单后延迟再打开模态/发信号 | `music_cards_view.py` | 卡片右键：更换封面 / 背景 / 课题称号 / 上传 / 删除 等由 `singleShot(0)` 改为 **`singleShot(80)`**，与菜单关闭动画错开 |
| 角色变体 Tab | `manager_widget.py` | 「编辑此变体」「+ 新增变体」触发对话框由 `0ms` 改为 **`80ms`** |
| 既有（本次确认仍有效） | `manager_widget.py` | 表格右键删除角色/称号/任务等已使用 **`singleShot(80)`** |
| 既有 | `fluent_dialogs.py` | `_normalize_parent` 沿 `parentWidget()` 直至 `isWindow()`；`raise_`/`activateWindow` 仅对顶层调用 |
| 既有 | `dds_progress.py`、`index_progress.py`、`map_add_dialog.py`、`swan_sheet_download_dialog.py` | 进度框统一 `safe_dismiss_modal_progress_dialog` |
| 既有 | `pjsk_hub_dialog.py` | 转写线程期间整窗禁用；提示依赖 `fly_*` 内启用顶层逻辑（曾手写 `setEnabled(True)` 已收敛到封装层） |

**仍保留原生 Qt、属预期**：

- `QFileDialog` / `QInputDialog`：系统对话框，多处使用（如 `main_window.py`、`settings_dialog.py`、各 `*add_dialog.py`）。
- `RoundMenu.exec(...)`：Fluent 右键菜单；**禁止**在 `triggered` 同步路径上立刻 `QDialog.exec()`，应 `QTimer.singleShot(80, ...)` 或等价延迟。
- `QDialog.exec()`：`FluentCaptionDialog` 等业务窗体，父窗口一般为 `MainWindow` 或已设 `parent=self` 的顶层对话框。
- `dds_progress.run_bc3_jobs_with_progress` 内 `QEventLoop.exec()`：配合线程与进度框，结束路径已 `safe_dismiss_modal_progress_dialog`。

**未改代码、仅风险较低或已符合规范**：

- `settings_dialog.py`：`hub.exec()` 子对话框；`QInputDialog.getItem` 在设置窗体内同步调用。
- `pgko_sheet_download_dialog.py`：`_ok_btn.setEnabled(False)` 仅禁用按钮，非整窗；失败/成功仍走 `fly_*`。
- 各 `fly_*` 调用使用 `self` 或 `self.window()`：封装内会归一到顶层，二者均可。

---

### 历史背景（摘要）

| 事项 | 说明 |
|------|------|
| 无边框 + `QProgressDialog` | `FramelessDialog` / `FluentCaptionDialog` 作父时，进度框若未 `reset`/`NonModal`/`deleteLater`/`processEvents`，易残留模态 |
| `manager_widget` 场景更换 | 注释明确：`MessageBox after this flow can lock interaction`，该路径**刻意不弹窗**，仅日志 |
| PJSK 安装对话框 | 整窗 `setEnabled(False)` 期间若直接模态 `MessageBox`，Windows 上易全局无效点击 |

---

## 4. 涉及弹窗的模块索引（便于二次审计）

以下模块含 `dlg.exec()`、`fly_*`、文件对话框或进度框，后续加功能时请对照 [完整指南](./桌面端模态弹窗与进度安全_完整指南_zh.md) §8 Code Review：

`main_window.py`、`manager_widget.py`、`music_cards_view.py`、`settings_dialog.py`、`fluent_dialogs.py`、`fluent_caption_dialog.py`、`dds_progress.py`、`index_progress.py`、`map_add_dialog.py`、`mapbonus_dialogs.py`、`chara_add_dialog.py`、`event_add_dialog.py`、`trophy_add_dialog.py`、`nameplate_add_dialog.py`、`quest_add_dialog.py`、`stage_add_dialog.py`、`save_patch_dialog.py`、`game_music_browser_dialog.py`、`music_trophy_dialog.py`、`works_dialogs.py`、`swan_sheet_download_dialog.py`、`pgko_sheet_download_dialog.py`、`pjsk_hub_dialog.py`、`pjsk_sus_download_dialog.py`、`github_sheet_dialog.py`、`music_add_actions_dialog.py`、`sus_c2s_debug_dialog.py` 等。

---

## 5. 回归建议（冒烟）

1. 主窗口：打开设置 → 保存；打开任意 `FluentCaptionDialog` → 确定/取消。  
2. 管理页：表格右键 **删除角色/称号/任务** → 确认框可点；取消后界面正常。  
3. 歌曲卡片视图：右键 **删除乐曲** → 同上。  
4. 地图编辑：`MapAddDialog` 内点空格 → **空格子** Fluent 确认；保存地图 → **完成** 提示。  
5. 含进度条流程：DDS 批量编码、游戏索引扫描、Swan 列表加载（若有进度条）→ 结束后可正常点主界面与其它弹窗。

---

*若新增 `QProgressDialog` 或绕过 `fly_*` 的 `MessageBox`，请在本文件 §3 追加一行记录并更新 §4 索引（如需要）。*
