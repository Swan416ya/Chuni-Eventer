# Chuni Eventer 桌面端 UI 组件与样式现状（盘点）

本文档描述 **当前实现** 中各界面使用的 **PyQt6（Qt 原生）** 与 **qfluentwidgets（PyQt-Fluent-Widgets）** 及 **项目内自定义控件** 的分布情况，供后续统一 UI（目标：尽量仅使用 Fluent 组件或项目自研样式组件）时对照。

> 扫描范围：`chuni_eventer_desktop/ui/` 及直接引用 Qt widgets 的少量模块（如 `app.py`）。  
> 库名以代码中的 `qfluentwidgets` 为准。  
> **弹窗模态、`QProgressDialog` 与 `fly_*` 安全规范**（排查清单、Code Review）：同目录 [桌面端模态弹窗与进度安全_完整指南_zh.md](./桌面端模态弹窗与进度安全_完整指南_zh.md)。

---

## 1. 全局与壳层

| 区域 | 实现 | 代码位置 |
|------|------|----------|
| 应用入口 | `QApplication` + `setTheme(Theme.AUTO)` | `chuni_eventer_desktop/app.py` |
| 主窗口 | `MSFluentWindow`（Fluent 导航壳） | `ui/main_window.py` |
| 工作区容器 | `QWidget` + `QVBoxLayout` / `QHBoxLayout` | `main_window.py` 中 `_workspace` |
| 顶栏控件 | `SubtitleLabel`、`SearchLineEdit`、`PushButton`、`PrimaryPushButton` | Fluent |
| 系统级弹窗 | `QFileDialog` | 选目录/选文件仍为系统原生 |
| 轻量提示 / 确认 | `fly_message` / `fly_critical` / `fly_warning` / `fly_question`；进度条收尾 `safe_dismiss_modal_progress_dialog` | `ui/fluent_dialogs.py`，底层为 `qfluentwidgets.MessageBox`；规范见 [桌面端模态弹窗与进度安全_完整指南_zh.md](./桌面端模态弹窗与进度安全_完整指南_zh.md) |

---

## 2. 信息架构（「页面」= 导航项 + 同一工作区）

侧栏 **9 个数据类** + 底部 **存档装备**、**设置**（不可选中）。除设置与存档装备为独立对话框外，其余共用一个 `MainWindow` 内的 `self._workspace`。

| 导航 routeKey | 中文名 | 主界面表现 |
|---------------|--------|------------|
| `nav_chara` ~ `nav_mapbonus` | 角色 / 地图 / 事件 / 任务 / 歌曲 / 称号 / 名牌 / 奖励 / 加成 | `ManagerWidget` 随 `kind` 切换内容与过滤器 |
| `nav_save_patch` | 存档装备 | 打开 `SavePatchDialog` |
| `nav_settings` | 设置 | 打开 `SettingsDialog` |

**歌曲** 与其它类不同：`ManagerWidget` 内用 `QStackedWidget` 在「表格 + 预览」与 **卡片视图** 之间切换；`Music` 时显示 `MusicCardsView`（stack 索引 1），其它类显示左侧 `TableView` + 右侧预览/属性（索引 0）。逻辑见 `manager_widget.py` 的 `reload()` 与 `_main_stack`。

---

## 3. 主工作区：`ManagerWidget`

### 已使用 Fluent

- 主列表与属性区：`TableView` + `QStandardItemModel`（选择行为等仍通过 `QAbstractItemView` 枚举配置）
- 类型 / 事件 / 奖励筛选：`ComboBox`
- 独立模式顶栏：`CaptionLabel`、`SearchLineEdit`、`PushButton`
- 右侧容器：`CardWidget`
- 角色变体页签：`TabWidget`
- 文案：`BodyLabel`、`CaptionLabel`
- 右键菜单：`RoundMenu`、`Action`、`MenuAnimationType`、`FluentIcon`
- 提示与删除确认：`fly_message` / `fly_critical` / `fly_question`（见 `fluent_dialogs.py`）

### 仍为 Qt 原生或基于 Qt 基类的自定义

- **布局与分栏**：`QWidget`、`QVBoxLayout`、`QHBoxLayout`、`QStackedWidget`、`QSplitter`（库内无 Splitter 件）
- **预览像素图**：`QLabel`（`WidthScaledPreviewLabel`、`CharaDdsPreviewWidget` 内）；边框色随 `isDarkTheme()` 调整
- **数据与协议**：`QStandardItemModel`、`QSortFilterProxyModel`、`QStandardItem`
- **文件选择**：`QFileDialog`（更换封面）

未覆盖项汇总见 [ui_main_workspace_fluent_gaps_zh.md](./ui_main_workspace_fluent_gaps_zh.md)。

### 项目内自定义（非 Fluent 库件）

- `WidthScaledPreviewLabel`：`QLabel` 子类，按宽度缩放 DDS 预览
- `CharaDdsPreviewWidget`：组合多个 `QLabel` 做角色三张贴图布局

---

## 4. 歌曲卡片页：`MusicCardsView`

- **Fluent**：`ScrollArea`、`RoundMenu`、`Action`、`FluentIcon`、`MenuAnimationType`（卡片右键菜单）
- **Qt / 自绘**：`QWidget`、`QGridLayout`、`QFrame`；`FlipMusicCard`（`QFrame` + `QPainter` + `QPropertyAnimation` 翻转）；颜色等用 `QColor` 等

---

## 5. 对话框与辅助窗口（按文件）

| 模块 | 壳 / 主要结构 | Fluent | 典型 Qt 或其它 |
|------|----------------|--------|----------------|
| `settings_dialog.py` | `FluentCaptionDialog` | `BodyLabel`、`CardWidget`、`LineEdit`、`PushButton`、`PrimaryPushButton`；`fluent_caption_content_margins` | `QFileDialog`、`QInputDialog.getItem`、`QVBoxLayout` / `QHBoxLayout` |
| `save_patch_dialog.py` | `FluentCaptionDialog` | `TabWidget`、`SearchLineEdit`、`EditableComboBox`、`SpinBox`、`BodyLabel`、`CaptionLabel`、`CardWidget`、按钮、`isDarkTheme`；`fluent_caption_content_margins` | 各 Tab 内 `QWidget`、`QFormLayout`、`QLabel`（预览） |
| `music_add_actions_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`SubtitleLabel`、`PushButton`；`fluent_caption_content_margins` | `QToolButton`、`QGraphicsDropShadowEffect`（卡片阴影） |
| `game_music_browser_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`BodyLabel`、`FluentComboBox`、`LineEdit`、`PushButton` / `PrimaryPushButton`；`fluent_table.apply_fluent_sheet_table`；`fly_warning` / `fly_critical`；`fluent_caption_content_margins` | `QTableWidget`、`QLabel`（筛选标签）、`QVBoxLayout` / `QHBoxLayout` |
| `chara_add_dialog.py` | `FluentCaptionDialog` | `LineEdit`、`FluentComboBox`、`PushButton`、`PrimaryPushButton`、`CardWidget`、`BodyLabel`；`isDarkTheme`；`fluent_caption_content_margins`；`fly_message` / `fly_critical` | `QFileDialog`；布局 `QVBoxLayout` / `QHBoxLayout` |
| `event_add_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`BodyLabel`、`LineEdit`、`PushButton`、`PrimaryPushButton`；`fluent_caption_content_margins`；`fly_message` / `fly_critical` | `QFormLayout`、`QFileDialog` |
| `trophy_add_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`BodyLabel`、`LineEdit`、`FluentComboBox`、`PushButton`、`PrimaryPushButton`；`isDarkTheme`；`fly_message` / `fly_critical` | `QFormLayout`、`QLabel`（示例图）、`QFileDialog` |
| `nameplate_add_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`BodyLabel`、`LineEdit`、`PushButton`、`PrimaryPushButton`；`fly_message` / `fly_critical` | `QFormLayout`、`QFileDialog` |
| `quest_add_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`BodyLabel`、`LineEdit`、`FluentComboBox`、`CheckBox`、`SpinBox`、`PushButton`、`PrimaryPushButton`；`fly_critical`；`fluent_caption_content_margins` | `QFormLayout`、`QListWidget` |
| `map_add_dialog.py` | `FluentCaptionDialog`（主窗 + 多个子对话框） | `TabWidget`（含 `tabAddRequested` 新建页签）、`CardWidget`、`SubtitleLabel`、`LineEdit`、`FluentComboBox`、`CheckBox`、`ScrollArea`、`TextEdit`、`PushButton` / `PrimaryPushButton`；`fly_message` / `fly_critical` / `fly_warning` / `fly_question`；`fluent_caption_content_margins` | `QFormLayout`、`QGridLayout`、`QLabel`（说明/警告色文案）、`QProgressDialog`、`QFileDialog`；`MapBonusEditDialog` 等仍来自其它模块 |
| `mapbonus_dialogs.py` | `FluentCaptionDialog`（主窗 + 单条条件子窗） | `CardWidget`、`BodyLabel`、`LineEdit`、`FluentComboBox`、`PushButton`、`PrimaryPushButton`；2×2 槽位 + 子窗编辑；`fly_critical`；`isDarkTheme`（槽位样式） | `QFormLayout`、`QGridLayout` |
| `music_trophy_dialog.py` | `FluentCaptionDialog` | `FluentComboBox`、`BodyLabel`、`PushButton` / `PrimaryPushButton`；`fly_message` / `fly_warning` / `fly_critical`；`fluent_caption_content_margins` | `QLabel`（表单标签）、`QHBoxLayout` / `QVBoxLayout` |
| `works_dialogs.py` | `FluentCaptionDialog`（作品库 / 创建 / 绑定） | `LineEdit`、`FluentComboBox`、`PushButton`、`PrimaryPushButton`；`fluent_caption_content_margins` | `QListWidget`（列表）；工具函数仍接受 `QComboBox \| FluentComboBox` 以兼容旧调用 |
| `swan_sheet_download_dialog.py` | `FluentCaptionDialog` | `BodyLabel`、`CardWidget`、`PushButton` / `PrimaryPushButton`；`fluent_caption_content_margins`；`fly_*` | `QProgressDialog`；`QTableWidget` + `apply_fluent_sheet_table` |
| `pgko_sheet_download_dialog.py` | `FluentCaptionDialog`（主窗 + `_PgkoUgcGuideDialog` + `_PgkoInstallConfigDialog`） | `CardWidget`、`BodyLabel`、`LineEdit`、`FluentComboBox`、`CheckBox`、`PushButton` / `PrimaryPushButton`；`fly_question` / `fly_*`；`fluent_caption_content_margins` | `QTableWidget` + `apply_fluent_sheet_table`、`QLabel`（富文本说明） |
| `pjsk_hub_dialog.py` | `FluentCaptionDialog`（`PjskHubDialog` + `PjskInstallToAcusDialog`） | `BodyLabel`、`CardWidget`、`LineEdit`、`SpinBox`、`CheckBox`、`PushButton` / `PrimaryPushButton`；`fly_question` / `fly_*`；`fluent_caption_content_margins` | `QTableWidget` + `apply_fluent_sheet_table`、`QFormLayout`、`QGridLayout`、`QLabel`、`QProgressBar` |
| `pjsk_sus_download_dialog.py` | `FluentCaptionDialog` | `CardWidget`、`BodyLabel`、`LineEdit`、`PushButton` / `PrimaryPushButton`；`fluent_caption_content_margins`；`fly_*` | `QTableWidget` + `apply_fluent_sheet_table`、`QProgressBar` |
| `pjsk_vocal_pick_dialog.py` | `FluentCaptionDialog` | `BodyLabel`、`PushButton` / `PrimaryPushButton`；`fluent_caption_content_margins` | `QListWidget` |
| `sus_c2s_debug_dialog.py` | `FluentCaptionDialog`（非模态调试窗） | `BodyLabel`、`CardWidget`、`LineEdit`、`PushButton` / `PrimaryPushButton`；`fluent_caption_content_margins`；`fly_*` | `QPlainTextEdit`、`QFileDialog` |
| `index_progress.py` | 进度 | 无 | `QProgressDialog` |
| `dds_progress.py` | 进度 | 无 | `QProgressDialog` |

---

## 6. 小型共享件

| 文件 | 作用 | 主要组件 |
|------|------|----------|
| `name_glyph_preview.py` | 名称行：绑定在 `QLineEdit` 子类（含 Fluent `LineEdit`）旁的预览按钮 | `CardWidget`、`BodyLabel`、`TransparentToolButton`（`FluentIcon`）；弹层为 `QWidget` 顶层窗口 + `QGraphicsDropShadowEffect` |
| `fluent_table.py` | 自制谱等表格选中行对比度 | `QTableWidget` + `FluentStyleSheet.TABLE_VIEW` + `setCustomStyleSheet` |

---

## 7. 与「仅 Fluent + 自研样式组件」目标的差距摘要

1. **布局与容器**：广泛依赖 `QWidget`、`QVBoxLayout`、`QHBoxLayout`、`QFormLayout`、`QSplitter`、`QStackedWidget`、`QFrame`。Fluent 通常不替代布局；若目标包含「界面代码中不出现 Qt 控件」，需单独定义是否允许 **无外观的布局/容器**。
2. **输入与展示**：主流程弹窗已大量改用 Fluent 输入件；工作区内及少数调试界面仍混用 `QTableWidget`、`QListWidget`、`QPlainTextEdit`、原生布局容器等（见上表「典型 Qt」列）。
3. **系统对话框**：`QFileDialog`、`QInputDialog`、`QProgressDialog` 等仍为系统原生；若需完全 Fluent 化需自研封装。
4. **消息与确认**：业务弹窗已统一为 `fly_message` / `fly_critical` / `fly_warning` / `fly_question`（`fluent_dialogs.py`）；`QProgressDialog` 结束须 `safe_dismiss_modal_progress_dialog`。详见 [桌面端模态弹窗与进度安全_完整指南_zh.md](./桌面端模态弹窗与进度安全_完整指南_zh.md)。非 UI 模块或脚本可能仍直接使用 Qt 消息框（若有）。
5. **已有自研/半自研**：`FlipMusicCard`（卡片翻转）、`fluent_table`（表样式）等 —— 与 Fluent 主题并存即可。
6. **已推进模块**：除主窗口与工作区表格外，**上述 §5 表中列出的对话框均已使用 `FluentCaptionDialog`（或同等 Fluent 标题栏壳）+ `fluent_caption_content_margins`**，自制谱 Swan / pgko 全链路及其子窗、设置与存档装备、游戏乐曲浏览、乐曲课题称号、乐曲新增渠道、PJSK 下载/导入/人声选择与 SUS 调试窗等均已纳入；业务提示以 `fly_*` 为主。

---

## 8. 维护说明

改版时可按 **文件 → Fluent / Qt / 自定义** 三列更新本表；重大结构调整后建议同步修改本节与各表中的「代码位置」描述。
