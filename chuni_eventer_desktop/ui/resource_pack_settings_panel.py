"""资源导入设置面板 — 设置页中的"资源导入"分段。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    SubtitleLabel,
)

from .fluent_scroll import apply_fluent_transparent_panel
from .fluent_dialogs import fly_message, fly_question
from .resource_pack_import_dialog import ResourcePackImportDialog

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 导入历史记录
# ---------------------------------------------------------------------------

_HISTORY_FILE_NAME = "resource_pack_import_history.json"
_MAX_HISTORY = 50


def _history_path(acus_root: Path) -> Path:
    return acus_root / ".cache" / _HISTORY_FILE_NAME


def _load_history(acus_root: Path) -> list[dict]:
    """加载导入历史记录。"""
    path = _history_path(acus_root)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _save_history(acus_root: Path, history: list[dict]) -> None:
    """保存导入历史记录（最多保留 _MAX_HISTORY 条）。"""
    path = _history_path(acus_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _add_history_entry(
    acus_root: Path,
    package: str,
    resource_count: int,
    remaps: dict,
    success: bool = True,
) -> None:
    """追加一条导入记录。"""
    history = _load_history(acus_root)
    entry = {
        "package": package,
        "time": datetime.now(timezone.utc).isoformat(),
        "resource_count": resource_count,
        "success": success,
        "remaps": {f"{k[0]}:{k[1]}": v for k, v in remaps.items()},
    }
    history.insert(0, entry)
    history = history[:_MAX_HISTORY]
    _save_history(acus_root, history)


def _format_time(iso_str: str) -> str:
    """格式化 ISO 时间字符串为本地时间。"""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str


# ---------------------------------------------------------------------------
# History List Widget
# ---------------------------------------------------------------------------


class _ImportHistoryWidget(QListWidget):
    """导入历史记录列表。"""

    def __init__(
        self,
        history: list[dict],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items: list[QListWidgetItem] = []
        self._populate(history)

    def _populate(self, history: list[dict]) -> None:
        if not history:
            item = QListWidgetItem("暂无导入记录", self)
            item.setToolTip("导入资源包后，历史记录将显示在这里")
            item.setForeground(Qt.GlobalColor.darkGray)
            self._items.append(item)
            return

        for entry in history:
            pkg = entry.get("package", "?")
            time_str = _format_time(entry.get("time", ""))
            res_count = entry.get("resource_count", 0)
            success = entry.get("success", False)

            status_icon = FluentIcon.CHECK_MARK_CIRCLE.icon().pixmap(16, 16) if success else (
                FluentIcon.CANCEL.icon().pixmap(16, 16)
            )
            status_text = "成功" if success else "失败"

            text = f"{pkg}  |  {time_str}  |  {res_count} 个资源  |  {status_text}"
            item = QListWidgetItem(text, self)
            item.setData(Qt.ItemDataRole.DecorationRole, status_icon)
            item.setToolTip(json.dumps(entry, ensure_ascii=False))
            self._items.append(item)

        # 排序：保持时间倒序
        self.sortItems(Qt.SortOrder.DescendingOrder)


# ---------------------------------------------------------------------------
# Main Panel
# ---------------------------------------------------------------------------


class ResourcePackSettingsPanel(QWidget):
    """设置页中的"资源导入"分段。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("resourcePackSettingsPanel")
        apply_fluent_transparent_panel(self)

        self._acus_root = acus_root.resolve()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 8, 24, 16)
        root.setSpacing(12)

        # ---- 标题区 ----
        root.addWidget(SubtitleLabel("资源压缩包快捷导入", self))
        hint = CaptionLabel(
            "导入他人分享的资源压缩包，自动处理 ID 冲突",
            self,
        )
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        root.addWidget(hint)

        # ---- 导入卡片 ----
        import_card = CardWidget(self)
        import_lay = QVBoxLayout(import_card)
        import_lay.setContentsMargins(16, 16, 16, 16)
        import_lay.setSpacing(12)

        import_hint = BodyLabel(
            "选择一个 .zip 资源压缩包导入到当前 ACUS",
            import_card,
        )
        import_hint.setStyleSheet("font-size: 13px;")
        import_lay.addWidget(import_hint)

        self._import_btn = PrimaryPushButton("选择压缩包导入...", import_card)
        self._import_btn.clicked.connect(self._on_import_clicked)
        import_lay.addWidget(self._import_btn)

        root.addWidget(import_card)

        # ---- 导入历史 ----
        root.addWidget(SubtitleLabel("导入历史", self))

        history_card = CardWidget(self)
        history_lay = QVBoxLayout(history_card)
        history_lay.setContentsMargins(16, 16, 16, 16)
        history_lay.setSpacing(8)

        self._history_widget = _ImportHistoryWidget(
            _load_history(self._acus_root),
            parent=history_card,
        )
        history_lay.addWidget(self._history_widget, stretch=1)

        root.addWidget(history_card)
        root.addStretch(1)

    # ---- Actions ----

    def _on_import_clicked(self) -> None:
        from PyQt6.QtWidgets import QFileDialog

        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择资源压缩包",
            "",
            "ZIP (*.zip)",
        )
        if not zip_path:
            return

        # 弹出导入对话框
        dlg = ResourcePackImportDialog(acus_root=self._acus_root, parent=self)
        result = dlg.exec()

        if result == dlg.DialogCode.Accepted:
            # 导入成功 — 刷新历史
            self.refresh_history()
            fly_message(self, "导入完成", "资源包已成功导入到 ACUS。")

    def refresh_history(self) -> None:
        """刷新导入历史记录。"""
        history = _load_history(self._acus_root)
        # 直接重建 widget
        old_widget = self._history_widget
        new_widget = _ImportHistoryWidget(history, parent=old_widget.parent())
        lay = old_widget.parent().layout()
        if lay is not None:
            lay.removeWidget(old_widget)
            old_widget.deleteLater()
        lay.addWidget(new_widget, stretch=1)
        self._history_widget = new_widget