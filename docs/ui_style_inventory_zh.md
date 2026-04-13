# Chuni Eventer 桌面端 UI 组件与样式现状（盘点）

本文档描述 **当前实现** 中各界面使用的 **PyQt6（Qt 原生）** 与 **qfluentwidgets（PyQt-Fluent-Widgets）** 及 **项目内自定义控件** 的分布情况，供后续统一 UI（目标：尽量仅使用 Fluent 组件或项目自研样式组件）时对照。

> 扫描范围：`chuni_eventer_desktop/ui/` 及直接引用 Qt widgets 的少量模块（如 `app.py`）。  
> 库名以代码中的 `qfluentwidgets` 为准。

---

## 1. 全局与壳层

| 区域 | 实现 | 代码位置 |
|------|------|----------|
| 应用入口 | `QApplication` + `setTheme(Theme.AUTO)` | `chuni_eventer_desktop/app.py` |
| 主窗口 | `MSFluentWindow`（Fluent 导航壳） | `ui/main_window.py` |
| 工作区容器 | `QWidget` + `QVBoxLayout` / `QHBoxLayout` | `main_window.py` 中 `_workspace` |
| 顶栏控件 | `SubtitleLabel`、`SearchLineEdit`、`PushButton`、`PrimaryPushButton` | Fluent |
| 系统级弹窗 | `QFileDialog` | 选目录/选文件仍为系统原生 |
| 轻量提示 / 确认 | `fly_message` / `fly_critical` / `fly_warning` / `fly_question` | `ui/fluent_dialogs.py`，底层为 `qfluentwidgets.MessageBox` |

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

未覆盖项汇总见 `docs/ui_main_workspace_fluent_gaps_zh.md`。

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
| `settings_dialog.py` | `QDialog` | `BodyLabel`、`CardWidget`、`LineEdit`、`PushButton`、`PrimaryPushButton` | `QFileDialog`、`QInputDialog.getItem` |
| `save_patch_dialog.py` | `QDialog` | `TabWidget`、`SearchLineEdit`、`EditableComboBox`、`SpinBox`、`BodyLabel`、`CaptionLabel`、`CardWidget`、按钮、`isDarkTheme` | 各 Tab 内 `QWidget`、`QFormLayout`、`QLabel`（预览） |
| `music_add_actions_dialog.py` | 无边框 `QDialog` | `CardWidget`、`SubtitleLabel`、`PushButton` | `QToolButton`、`QGraphicsDropShadowEffect`、硬编码浅色窗口背景 |
| `game_music_browser_dialog.py` | `QDialog` | 顶部 `BodyLabel` | `QComboBox`、`QLineEdit`、`QTableWidget`、`QPushButton`、`QMessageBox` |
| `chara_add_dialog.py` | `QDialog` | 无 | `QFormLayout`、`QLabel`、`QLineEdit`、`QPushButton`、`QFileDialog`、`QMessageBox` |
| `event_add_dialog.py` | `QDialog` | 无 | 同上 |
| `trophy_add_dialog.py` | `QDialog` | 无 | 同上 + 表单内多种 Qt 控件 |
| `nameplate_add_dialog.py` | `QDialog` | 无 | 同上 |
| `quest_add_dialog.py` | `QDialog` | 无 | `QCheckBox`、`QGroupBox`、`QListWidget`、`QSpinBox` 等 |
| `map_add_dialog.py` | `QDialog`（大表单） | 部分 `FluentLineEdit`（如地图 ID/名称） | `QTabWidget`、`QComboBox`、`QCheckBox`、`QGroupBox`、`QScrollArea`、`QTextEdit`、`QPushButton`、`QMessageBox`、`QProgressDialog`、`QFileDialog` 等；内含 `RewardCreateDialog` 等子流程，以 Qt 控件为主 |
| `mapbonus_dialogs.py` | `QDialog` | 无 | `QLineEdit`、`QComboBox`、`QTableWidget`、`QPushButton`、`QMessageBox` |
| `music_trophy_dialog.py` | `QDialog` | 无 | `QComboBox`、`QLabel`、`QPushButton`、`QMessageBox` |
| `works_dialogs.py` | `QDialog` | 无 | `QComboBox`、`QListWidget`、`QLineEdit`、`QSpinBox`、`QMessageBox` |
| `swan_sheet_download_dialog.py` | `QDialog` + Card | `BodyLabel`、`CardWidget`、Fluent 按钮 | `QProgressDialog`；表格使用 `fluent_table.apply_fluent_sheet_table`（底层 `QTableWidget`） |
| `pgko_sheet_download_dialog.py` | 类似 | 同上 | `QMessageBox.question`；Fluent 表样式封装 |
| `pjsk_hub_dialog.py` | 混合 | `BodyLabel`、`CardWidget`、Fluent 按钮 | 大量 Qt 控件、`QMessageBox`；表格 `apply_fluent_sheet_table` |
| `pjsk_sus_download_dialog.py` | 混合 | Card + Fluent 按钮 | `QTableWidget` + `apply_fluent_sheet_table` |
| `pjsk_vocal_pick_dialog.py` | `QDialog` | `BodyLabel`、Fluent 按钮 | `QListWidget` |
| `sus_c2s_debug_dialog.py` | `QWidget` 独立窗口 | `BodyLabel`、`CardWidget`、Fluent 按钮 | `QLineEdit`、`QPlainTextEdit`、`QFileDialog`；背景取 `QPalette` |
| `index_progress.py` | 进度 | 无 | `QProgressDialog` |
| `dds_progress.py` | 进度 | 无 | `QProgressDialog` |

---

## 6. 小型共享件

| 文件 | 作用 | 主要组件 |
|------|------|----------|
| `name_glyph_preview.py` | 名称输入 + 预览按钮 | `QLineEdit`、`QToolButton` |
| `fluent_table.py` | 自制谱等表格选中行对比度 | `QTableWidget` + `FluentStyleSheet.TABLE_VIEW` + `setCustomStyleSheet` |

---

## 7. 与「仅 Fluent + 自研样式组件」目标的差距摘要

1. **布局与容器**：广泛依赖 `QWidget`、`QVBoxLayout`、`QHBoxLayout`、`QFormLayout`、`QSplitter`、`QStackedWidget`、`QFrame`。Fluent 通常不替代布局；若目标包含「界面代码中不出现 Qt 控件」，需单独定义是否允许 **无外观的布局/容器**。
2. **输入与展示**：大量 `QLineEdit`、`QComboBox`、`QCheckBox`、`QSpinBox`、`QListWidget`、`QTabWidget`、`QTableWidget`、`QScrollArea`、`QGroupBox` 等仍待替换为 Fluent 对应件或项目封装。
3. **系统对话框**：`QFileDialog`、`QInputDialog`、`QProgressDialog`、部分 `QMessageBox` —— 若也要 Fluent 化，需改用库内同类能力或自研，并权衡跨平台外观。
4. **消息与确认**：业务中仍大量 `QMessageBox`，与 `fluent_dialogs` 的 `MessageBox` 封装并存，视觉不统一。
5. **已有自研/半自研**：`FlipMusicCard`、`MusicSheetChannelsDialog` 的硬编码窗口色、`fluent_table` 等 —— 宜纳入统一主题（如 `isDarkTheme`、Fluent 色板）。

---

## 8. 维护说明

改版时可按 **文件 → Fluent / Qt / 自定义** 三列更新本表；重大结构调整后建议同步修改本节与各表中的「代码位置」描述。
