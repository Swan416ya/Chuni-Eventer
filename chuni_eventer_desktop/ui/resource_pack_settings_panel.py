"""资源导入设置面板 — 设置页中的"资源导入"分段（嵌入式面板）。"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

import xml.etree.ElementTree as ET

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FluentIcon,
    IndeterminateProgressBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    setCustomStyleSheet,
    SubtitleLabel,
)

from .fluent_scroll import apply_fluent_transparent_panel
from .fluent_dialogs import fly_critical
from .fluent_table import apply_fluent_sheet_table
from .qthread_lifecycle import await_qthreads, finalize_qthread
from ..resource_pack_import import (
    ConflictReport,
    ImportResult,
    ReferenceGraph,
    apply_and_write,
    cleanup_staging,
    plan_import,
)
from ..resource_xml_rewriter import RemapPlan

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

_STATUS_CONFLICT = "conflict"
_STATUS_CLEAN = "clean"
_STATUS_WARNING = "warning"

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
# Helper: read dataName from XML
# ---------------------------------------------------------------------------


def _read_dataname(xml_path: Path) -> str:
    """从 XML 的 name/str 读取显示名称，失败返回 dir_path.name。"""
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        name_el = root.find("name")
        if name_el is not None:
            str_el = name_el.find("str")
            if str_el is not None and str_el.text:
                return str_el.text.strip()
    except Exception:
        pass
    return xml_path.parent.name


# ---------------------------------------------------------------------------
# Table model data rows
# ---------------------------------------------------------------------------


def _build_table_rows(
    conflict_report: ConflictReport,
    plan: RemapPlan,
    graph: ReferenceGraph,
) -> list[dict]:
    """构建表格行数据。"""
    rows: list[dict] = []

    # 冲突资源
    for entry in conflict_report.conflicts:
        pkg = entry.package_resource
        dataname = _read_dataname(pkg.xml_path)
        new_id = plan.remaps.get((pkg.kind, pkg.resource_id))
        new_id_str = str(new_id) if new_id is not None else ""
        ref_count = len(entry.referencing_files)

        # 检查是否有悬空引用指向此资源
        ref_edges = graph.referencers_of(pkg.kind, pkg.resource_id)
        has_dangling = any(not e.in_package for e in ref_edges)

        if has_dangling and ref_count == 0:
            warning = "悬空引用 (无包内引用者)"
        elif has_dangling:
            warning = f"含悬空引用, {ref_count} 个包内引用"
        else:
            warning = f"{ref_count} 个引用"

        rows.append({
            "kind": pkg.kind,
            "old_id": pkg.resource_id,
            "dataname": dataname,
            "status": _STATUS_CONFLICT,
            "new_id": new_id_str,
            "warning": warning,
        })

    # 干净资源
    for pkg in conflict_report.clean_resources:
        dataname = _read_dataname(pkg.xml_path)

        # 检查此干净资源是否有被冲突资源引用
        ref_edges = graph.referencers_of(pkg.kind, pkg.resource_id)
        ref_count = len(ref_edges)

        rows.append({
            "kind": pkg.kind,
            "old_id": pkg.resource_id,
            "dataname": dataname,
            "status": _STATUS_CLEAN,
            "new_id": "",
            "warning": f"{ref_count} 个引用" if ref_count else "",
        })

    return rows


# ---------------------------------------------------------------------------
# Plan Worker
# ---------------------------------------------------------------------------


class _PlanWorker(QObject):
    """后台执行 plan_import。"""

    finished = pyqtSignal(ConflictReport, RemapPlan, ReferenceGraph, Path)
    failed = pyqtSignal(str)

    def __init__(
        self,
        zip_path: Path,
        acus_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._zip_path = zip_path
        self._acus_root = acus_root

    def run(self) -> None:
        try:
            conflict_report, plan, graph, staging_root = plan_import(
                zip_path=self._zip_path,
                acus_root=self._acus_root,
            )
            self.finished.emit(conflict_report, plan, graph, staging_root)
        except Exception as e:
            self.failed.emit(traceback.format_exc())


# ---------------------------------------------------------------------------
# Apply Worker
# ---------------------------------------------------------------------------


class _ApplyWorker(QObject):
    """后台执行 apply_and_write + cleanup。"""

    finished = pyqtSignal(ImportResult)
    failed = pyqtSignal(str)

    def __init__(
        self,
        staging_root: Path,
        plan: RemapPlan,
        graph: ReferenceGraph,
        acus_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._staging = staging_root
        self._plan = plan
        self._graph = graph
        self._acus_root = acus_root

    def run(self) -> None:
        staging = self._staging
        try:
            result = apply_and_write(
                staging_root=staging,
                plan=self._plan,
                graph=self._graph,
                acus_root=self._acus_root,
            )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(traceback.format_exc())
        finally:
            # 无论成功失败都清理暂存区
            cleanup_staging(staging)


# ---------------------------------------------------------------------------
# Resource Table Widget
# ---------------------------------------------------------------------------

_STATUS_LABELS: dict[str, str] = {
    _STATUS_CONFLICT: "冲突-重映射",
    _STATUS_CLEAN: "保留",
    _STATUS_WARNING: "悬空引用",
}


class _ResourceTable(QWidget):
    """资源预览表格（含明暗主题颜色标记）。"""

    def __init__(
        self,
        rows: list[dict],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self._table = QTableWidget(len(rows), 6, self)
        self._table.setObjectName("ResourcePackImportTable")
        self._table.setHorizontalHeaderLabels(
            ["类型", "原 ID", "dataName", "状态", "新 ID", "警告"]
        )
        apply_fluent_sheet_table(self._table)

        # 列宽
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hh.setDefaultSectionSize(100)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setDefaultSectionSize(80)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.setDefaultSectionSize(120)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hh.setDefaultSectionSize(80)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        # 明暗主题颜色适配 (Fluent QSS 下 QTableWidgetItem 需要 setForeground/setBackground)
        _light_conflict_bg = "rgba(255, 220, 220, 0.5)"
        _light_conflict_fg = "#dc2626"
        _dark_conflict_bg = "rgba(255, 80, 80, 0.15)"
        _dark_conflict_fg = "#fca5a5"
        _light_clean_fg = "#15803d"
        _dark_clean_fg = "#4ade80"
        _light_warn_fg = "#a16207"
        _dark_warn_fg = "#facc15"

        qss = f"""
        QTableWidget#ResourcePackImportTable {{
            alternate-background-color: {_light_conflict_bg};
        }}
        """
        setCustomStyleSheet(
            self._table,
            qss,
            qss.replace(_light_conflict_bg, _dark_conflict_bg),
        )

        lay.addWidget(self._table, stretch=1)
        self._populate(rows)

    def _populate(self, rows: list[dict]) -> None:
        for row, data in enumerate(rows):
            self._set_row(row, data)

    def _set_row(self, row: int, data: dict) -> None:
        table = self._table
        status = data["status"]
        is_conflict = status == _STATUS_CONFLICT
        is_clean = status == _STATUS_CLEAN

        for col, value in enumerate([
            data["kind"],
            str(data["old_id"]),
            data["dataname"],
            _STATUS_LABELS.get(status, status),
            data["new_id"],
            data["warning"],
        ]):
            item = QTableWidgetItem(value)
            item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )
            if is_conflict:
                item.setBackground(Qt.GlobalColor.lightGray)
                item.setForeground(Qt.GlobalColor.darkRed)
            elif is_clean:
                item.setForeground(Qt.GlobalColor.darkGreen)
            table.setItem(row, col, item)


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
    """设置页中的"资源导入"分段 — 嵌入式导入工作区 + 历史记录。

    流程：选择压缩包 → 规划(后台) → 预览 → 确认导入(后台) → 完成
    """

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

        # State
        self._zip_path: Path | None = None
        self._conflict_report: ConflictReport | None = None
        self._plan: RemapPlan | None = None
        self._graph: ReferenceGraph | None = None
        self._staging_root: Path | None = None
        self._plan_thread: QThread | None = None
        self._apply_thread: QThread | None = None

        # ---- Root layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 8, 24, 16)
        root.setSpacing(12)

        # === 标题区 ===
        root.addWidget(SubtitleLabel("资源压缩包快捷导入", self))
        hint = CaptionLabel(
            "导入他人分享的资源压缩包，自动处理 ID 冲突",
            self,
        )
        hint.setStyleSheet("color: #6b7280; font-size: 11px;")
        root.addWidget(hint)

        # === 导入工作区卡片 ===
        import_card = CardWidget(self)
        card_lay = QVBoxLayout(import_card)
        card_lay.setContentsMargins(12, 12, 12, 12)
        card_lay.setSpacing(8)

        # 顶部：压缩包路径行
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addWidget(CaptionLabel("压缩包路径：", import_card))
        self._path_edit = LineEdit(import_card)
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("请选择 .zip 资源压缩包")
        path_row.addWidget(self._path_edit, stretch=1)

        self._select_btn = PrimaryPushButton("选择压缩包", import_card)
        self._select_btn.clicked.connect(self._on_select_zip)
        path_row.addWidget(self._select_btn)
        card_lay.addLayout(path_row)

        # 统计信息行
        self._stats_label = BodyLabel("", import_card)
        self._stats_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        card_lay.addWidget(self._stats_label)

        # QStackedWidget: 5 页
        self._stack = QStackedWidget(import_card)

        # Page 0: 初始 — 选择压缩包提示
        page0 = QWidget(self._stack)
        p0_lay = QVBoxLayout(page0)
        p0_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p0_hint = BodyLabel(
            "请选择一个 .zip 资源压缩包开始导入",
            page0,
        )
        p0_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        p0_hint.setStyleSheet("font-size: 14px; color: #6b7280;")
        p0_lay.addWidget(p0_hint, alignment=Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(page0)

        # Page 1: 规划中
        page1 = QWidget(self._stack)
        p1_lay = QVBoxLayout(page1)
        p1_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plan_label = BodyLabel("正在分析压缩包...", page1)
        self._plan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plan_progress = IndeterminateProgressBar(page1)
        self._plan_progress.setFixedSize(300, 6)
        p1_lay.addWidget(self._plan_label, alignment=Qt.AlignmentFlag.AlignCenter)
        p1_lay.addWidget(self._plan_progress, alignment=Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(page1)

        # Page 2: 预览（动态填充表格）
        page2 = QWidget(self._stack)
        self._stack.addWidget(page2)
        self._table_widget: _ResourceTable | None = None

        # Page 3: 导入中
        page3 = QWidget(self._stack)
        p3_lay = QVBoxLayout(page3)
        p3_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_label = BodyLabel("正在写入 ACUS...", page3)
        self._apply_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._apply_progress = IndeterminateProgressBar(page3)
        self._apply_progress.setFixedSize(300, 6)
        p3_lay.addWidget(self._apply_label, alignment=Qt.AlignmentFlag.AlignCenter)
        p3_lay.addWidget(self._apply_progress, alignment=Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(page3)

        # Page 4: 完成
        page4 = QWidget(self._stack)
        p4_lay = QVBoxLayout(page4)
        p4_lay.setContentsMargins(16, 16, 16, 16)
        self._result_label = SubtitleLabel("导入完成", page4)
        self._result_detail = BodyLabel("", page4)
        self._result_detail.setWordWrap(True)
        self._result_detail.setStyleSheet("color: #374151; font-size: 12px;")
        p4_lay.addWidget(self._result_label)
        p4_lay.addWidget(self._result_detail)
        p4_lay.addStretch(1)
        self._stack.addWidget(page4)

        card_lay.addWidget(self._stack, stretch=1)

        # 底部按钮
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)
        bottom_row.addStretch(1)

        self._cancel_btn = PushButton("取消", import_card)
        self._cancel_btn.clicked.connect(self._on_cancel)
        bottom_row.addWidget(self._cancel_btn)

        self._import_btn = PrimaryPushButton("确认导入", import_card)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_confirm_import)
        bottom_row.addWidget(self._import_btn)

        card_lay.addLayout(bottom_row)

        root.addWidget(import_card, stretch=1)

        # === 导入历史 ===
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

    # ---- Page management ----

    def _set_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._update_buttons()

    def _update_buttons(self) -> None:
        """根据当前页面更新底部按钮可见性/状态。"""
        page = self._stack.currentIndex()
        # Page 2（预览）: 确认按钮可见+启用
        self._import_btn.setVisible(page == 2)
        # 取消按钮：计划/导入阶段禁用
        if page == 1 or page == 3:
            self._cancel_btn.setEnabled(False)
        else:
            self._cancel_btn.setEnabled(True)

    def _show_page_preview(self) -> None:
        """显示预览页并填充表格。"""
        page2 = self._stack.widget(2)
        # 移除旧表格
        if self._table_widget is not None:
            self._table_widget.deleteLater()
        assert self._conflict_report is not None
        assert self._plan is not None
        assert self._graph is not None
        rows = _build_table_rows(self._conflict_report, self._plan, self._graph)
        lay = QVBoxLayout(page2)
        lay.setContentsMargins(12, 12, 12, 12)
        self._table_widget = _ResourceTable(rows, parent=page2)
        lay.addWidget(self._table_widget, stretch=1)

    # ---- Select ZIP ----

    def _on_select_zip(self) -> None:
        zip_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择资源压缩包",
            "",
            "ZIP (*.zip)",
        )
        if not zip_path:
            return
        self._zip_path = Path(zip_path).resolve()
        self._path_edit.setText(self._zip_path.as_posix())
        self._stats_label.setText("")
        self._import_btn.setEnabled(False)
        self._import_btn.setVisible(False)
        # 启动 plan worker
        self._start_plan()

    def _start_plan(self) -> None:
        assert self._zip_path is not None
        self._set_page(1)  # 规划中
        self._select_btn.setEnabled(False)

        self._plan_thread = QThread(parent=self)
        worker = _PlanWorker(self._zip_path, self._acus_root)
        worker.moveToThread(self._plan_thread)

        self._plan_thread.started.connect(worker.run)
        worker.finished.connect(self._on_plan_finished)
        worker.failed.connect(self._on_plan_failed)
        self._plan_thread.finished.connect(
            lambda: finalize_qthread(worker)
        )

        self._plan_thread.start()

    # ---- Plan results ----

    def _on_plan_finished(
        self,
        conflict_report: ConflictReport,
        plan: RemapPlan,
        graph: ReferenceGraph,
        staging_root: Path,
    ) -> None:
        self._conflict_report = conflict_report
        self._plan = plan
        self._graph = graph
        self._staging_root = staging_root

        # 更新统计
        total = len(conflict_report.conflicts) + len(conflict_report.clean_resources)
        conflict_count = len(conflict_report.conflicts)
        warning_count = len(conflict_report.package_warnings)
        self._stats_label.setText(
            f"包内资源数: {total} | "
            f"冲突数: {conflict_count} | "
            f"警告: {warning_count}"
        )

        # 显示预览
        self._set_page(2)
        self._show_page_preview()
        self._select_btn.setEnabled(True)

        # 有错误时禁用确认
        if plan.errors:
            self._stats_label.setText(
                self._stats_label.text() + " | 错误: 重映射计划生成失败"
            )
            self._import_btn.setEnabled(False)
            return

        # 有重映射或有干净资源都可以导入
        self._import_btn.setEnabled(True)

    def _on_plan_failed(self, details: str) -> None:
        self._set_page(0)
        self._select_btn.setEnabled(True)
        self._stats_label.setText("")
        # 清理暂存区
        if self._staging_root is not None:
            cleanup_staging(self._staging_root)
            self._staging_root = None
        fly_critical(
            self,
            "规划失败",
            "无法分析压缩包，详情请查看详细信息。",
            details=details,
        )

    # ---- Confirm Import ----

    def _on_confirm_import(self) -> None:
        assert self._plan is not None
        assert self._graph is not None
        assert self._staging_root is not None

        self._import_btn.setEnabled(False)
        self._select_btn.setEnabled(False)
        self._set_page(3)  # 导入中

        self._apply_thread = QThread(parent=self)
        worker = _ApplyWorker(
            self._staging_root,
            self._plan,
            self._graph,
            self._acus_root,
        )
        worker.moveToThread(self._apply_thread)

        self._apply_thread.started.connect(worker.run)
        worker.finished.connect(self._on_apply_finished)
        worker.failed.connect(self._on_apply_failed)
        self._apply_thread.finished.connect(
            lambda: finalize_qthread(worker)
        )

        self._apply_thread.start()

    # ---- Apply results ----

    def _on_apply_finished(self, result: ImportResult) -> None:
        self._staging_root = None  # apply worker finally 已清理
        self._set_page(4)  # 完成

        if result.success:
            remap_count = len(result.remaps)
            parts = [
                f"成功写入 {result.written_count} 个文件",
                f"重映射 {remap_count} 个资源",
            ]
            if result.warnings:
                parts.append(f"警告: {len(result.warnings)} 条")
            self._result_label.setText("导入成功")
            self._result_label.setStyleSheet("color: #15803d;")
            self._result_detail.setText("\n".join(parts))

            # 刷新历史记录
            package_name = (self._zip_path.name if self._zip_path else "unknown")
            total_count = len(self._conflict_report.conflicts) + len(self._conflict_report.clean_resources) if self._conflict_report else 0
            plan_remaps = dict(self._plan.remaps) if self._plan else {}
            _add_history_entry(
                self._acus_root,
                package=package_name,
                resource_count=total_count,
                remaps=plan_remaps,
                success=True,
            )
            self.refresh_history()
        else:
            self._result_label.setText("导入失败")
            self._result_label.setStyleSheet("color: #dc2626;")
            parts: list[str] = []
            if result.errors:
                parts.append("错误:")
                for err in result.errors:
                    parts.append(f"  - {err}")
            if result.warnings:
                parts.append("警告:")
                for warn in result.warnings:
                    parts.append(f"  - {warn}")
            self._result_detail.setText("\n".join(parts))

            # 刷新历史记录（标记失败）
            package_name = (self._zip_path.name if self._zip_path else "unknown")
            total_count = len(self._conflict_report.conflicts) + len(self._conflict_report.clean_resources) if self._conflict_report else 0
            plan_remaps = dict(self._plan.remaps) if self._plan else {}
            _add_history_entry(
                self._acus_root,
                package=package_name,
                resource_count=total_count,
                remaps=plan_remaps,
                success=False,
            )
            self.refresh_history()

    def _on_apply_failed(self, details: str) -> None:
        self._staging_root = None  # worker finally 里已清理
        fly_critical(
            self,
            "导入失败",
            "写入 ACUS 时发生异常，详情请查看详细信息。",
            details=details,
        )
        # 回到初始页
        self._set_page(0)
        self._reset_after_import()

    # ---- Cancel / Reset ----

    def _on_cancel(self) -> None:
        """用户点取消时处理。"""
        await_qthreads(self._plan_thread, self._apply_thread)

        # 清理暂存区
        if self._staging_root is not None:
            cleanup_staging(self._staging_root)
            self._staging_root = None

        self._set_page(0)
        self._reset_after_import()

    def _reset_after_import(self) -> None:
        self._zip_path = None
        self._conflict_report = None
        self._plan = None
        self._graph = None
        self._staging_root = None
        self._select_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._import_btn.setEnabled(False)
        self._import_btn.setVisible(False)
        self._path_edit.clear()
        self._stats_label.setText("")

    # ---- History refresh ----

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