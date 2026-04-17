# 主工作区：qfluentwidgets 未覆盖项（后续自写 QSS / 封装）

主工作区指 `MainWindow` 内 `_workspace`（顶栏 + `ManagerWidget` + 内嵌 `MusicCardsView`）。以下在 **当前 PyQt6-Fluent-Widgets 公开 API** 中**没有等价可替换组件**，或属于**布局/系统能力**，需保留 Qt 或后续用项目内样式封装。

| 类别 | 用途 | 代码位置（主要） |
|------|------|------------------|
| `QSplitter` | 主列表与右侧预览/属性面板可拖拽分栏 | `manager_widget.py` |
| `QFileDialog` | 乐曲卡片「更换封面」选文件；主窗口导入 ZIP 等 | `manager_widget.py`、`main_window.py` |
| `QWidget` + `QVBoxLayout` / `QHBoxLayout` / `QStackedWidget` | 纯布局与页面切换，无 Fluent 替代 | `main_window.py`、`manager_widget.py`、`music_cards_view.py` |
| `QLabel`（子类/组合） | DDS 缩放预览、角色三格立绘占位；仅承载 `QPixmap` | `WidthScaledPreviewLabel`、`CharaDdsPreviewWidget`（`manager_widget.py`） |
| `FlipMusicCard(QFrame)` + `QPainter` | 歌曲卡片翻转与自绘封面/信息 | `music_cards_view.py` |
| `QAbstractItemView` 枚举、`QStandardItemModel` 等 | 模型/视图协议，非控件皮肤 | `manager_widget.py` |
| 子功能 `QDialog` | 双击打开地图编辑等仍为原生 `QDialog` 子类 | 由 `manager_widget` 调用的各 `*Dialog`（本次未改） |

## 已在本轮改为 Fluent（或 Fluent 封装）的项

- 事件/奖励筛选：`ComboBox`
- 独立模式顶栏：`CaptionLabel`、`SearchLineEdit`、`PushButton`
- 角色变体页签：`TabWidget`
- 右侧容器：`CardWidget`
- 属性区：只读 `TableView` + `QStandardItemModel`（与主表一致样式）
- 主工作区内提示/确认：`fly_message` / `fly_critical` / `fly_question`（`MessageBox`）
- 歌曲页滚动：`ScrollArea`（平滑滚动条）

若后续为主题切换修正 `CharaDdsPreviewWidget` 边框色，可在 `Theme` 变化时重算 `isDarkTheme()` 并 `setStyleSheet`，或抽到统一 QSS。
