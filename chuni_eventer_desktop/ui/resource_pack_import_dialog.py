"""资源压缩包导入对话框 — plan-preview-confirm-apply 流程。"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path

import xml.etree.ElementTree as ET

from PyQt6.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QProgressBar,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    IndeterminateProgressBar,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    setCustomStyleSheet,
    SubtitleLabel,
)

from ..resource_pack_import import (
    ConflictReport,
    ImportResult,
    ReferenceGraph,
    apply_and_write,
    cleanup_staging,
    plan_import,
)
from ..resource_xml_rewriter import RemapPlan
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .fluent_table import apply_fluent_sheet_table
from .qthread_lifecycle import await_qthreads, finalize_qthread

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

_STATUS_CONFLICT = "conflict"
_STATUS_CLEAN = "clean"
_STATUS_WARNING = "warning"

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
# Main Dialog
# ---------------------------------------------------------------------------


class ResourcePackImportDialog(FluentCaptionDialog):
    """资源压缩包导入对话框。

    流程：选择压缩包 → 规划(后台) → 预览 → 确认导入(后台) → 完成
    """

    def __init__(
        self,
        *,
        acus_root: Path,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("资源压缩包导入")
        self.setModal(True)
        self.resize(800, 600)

        self._acus_root = acus_root.resolve()
        self._zip_path: Path | None = None
        self._conflict_report: ConflictReport | None = None
        self._plan: RemapPlan | None = None
        self._graph: ReferenceGraph | None = None
        self._staging_root: Path | None = None
        self._plan_thread: QThread | None = None
        self._apply_thread: QThread | None = None

        # ---- Layout ----
        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(12)

        # === 顶部区 ===
        top_lay = QVBoxLayout()
        top_lay.setSpacing(8)

        # 压缩包路径行
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_row.addWidget(CaptionLabel("压缩包路径：", self))
        self._path_edit = LineEdit(self)
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("请选择 .zip 资源压缩包")
        path_row.addWidget(self._path_edit, stretch=1)

        self._select_btn = PrimaryPushButton("选择压缩包", self)
        self._select_btn.clicked.connect(self._on_select_zip)
        path_row.addWidget(self._select_btn)
        top_lay.addLayout(path_row)

        # 统计信息行
        self._stats_label = BodyLabel("", self)
        self._stats_label.setStyleSheet("color: #6b7280; font-size: 12px;")
        top_lay.addWidget(self._stats_label)

        root.addLayout(top_lay)

        # === 中部区 (QStackedWidget) ===
        self._stack = QStackedWidget(self)

        # Page 0: 初始 — 选择压缩包提示
        page0 = QWidget(self)
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
        page1 = QWidget(self)
        p1_lay = QVBoxLayout(page1)
        p1_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plan_label = BodyLabel("正在分析压缩包...", page1)
        self._plan_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._plan_progress = IndeterminateProgressBar(page1)
        self._plan_progress.setFixedSize(300, 6)
        p1_lay.addWidget(self._plan_label, alignment=Qt.AlignmentFlag.AlignCenter)
        p1_lay.addWidget(self._plan_progress, alignment=Qt.AlignmentFlag.AlignCenter)
        self._stack.addWidget(page1)

        # Page 2: 预览
        page2 = QWidget(self)
        self._stack.addWidget(page2)
        self._table_widget: _ResourceTable | None = None

        # Page 3: 导入中
        page3 = QWidget(self)
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
        page4 = QWidget(self)
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

        root.addWidget(self._stack, stretch=1)

        # === 底部区 ===
        bottom_lay = QHBoxLayout()
        bottom_lay.setSpacing(8)
        bottom_lay.addStretch(1)

        self._cancel_btn = PushButton("取消", self)
        self._cancel_btn.clicked.connect(self.reject)
        bottom_lay.addWidget(self._cancel_btn)

        self._import_btn = PrimaryPushButton("确认导入", self)
        self._import_btn.setEnabled(False)
        self._import_btn.clicked.connect(self._on_confirm_import)
        bottom_lay.addWidget(self._import_btn)

        root.addLayout(bottom_lay)

    # ---- Page management ----

    def _set_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

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
        from PyQt6.QtWidgets import QFileDialog

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
        # 启动 plan worker
        self._start_plan()

    def _start_plan(self) -> None:
        assert self._zip_path is not None
        self._set_page(1)  # 规划中
        self._select_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

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
        self._cancel_btn.setEnabled(True)

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
        self._cancel_btn.setEnabled(True)
        self._stats_label.setText("")
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
        self._cancel_btn.setEnabled(False)
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

    # ---- Reset state after import ----

    def _reset_after_import(self) -> None:
        self._zip_path = None
        self._conflict_report = None
        self._plan = None
        self._graph = None
        self._staging_root = None
        self._select_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        self._import_btn.setEnabled(False)
        self._path_edit.clear()
        self._stats_label.setText("")

    # ---- Close handling ----

    def closeEvent(self, event: QCloseEvent) -> None:
        # 等待后台线程
        await_qthreads(self._plan_thread, self._apply_thread)

        # 预览阶段 — 必须清理暂存区
        if self._stack.currentIndex() == 2 and self._staging_root is not None:
            cleanup_staging(self._staging_root)
            self._staging_root = None

        super().closeEvent(event)

    def reject(self) -> None:
        """用户点取消时处理。"""
        await_qthreads(self._plan_thread, self._apply_thread)

        # 清理暂存区
        if self._staging_root is not None:
            cleanup_staging(self._staging_root)
            self._staging_root = None

        super().reject()