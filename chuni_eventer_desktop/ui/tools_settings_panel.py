from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig
from ..external_tools import (
    ALL_TOOLS,
    ExternalToolSpec,
    _BUILTIN_PYTHON,
    apply_resolved_paths_to_config,
    install_tool,
    set_config_path,
    tool_status,
    tools_root_dir,
    write_inventory_file,
)
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .qthread_lifecycle import await_qthreads, finalize_qthread
from .rich_hint import rich_hint_label


class _ToolInstallWorker(QObject):
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, spec: ExternalToolSpec, cfg: AcusConfig) -> None:
        super().__init__()
        self._spec = spec
        self._cfg = cfg

    def run(self) -> None:
        try:
            path = install_tool(
                self._spec,
                self._cfg,
                on_progress=lambda msg: self.progress.emit(msg),
            )
            self.finished.emit(("ok", path))
        except Exception as e:
            self.finished.emit(("err", str(e)))


class ToolsSettingsPanel(QWidget):
    """外部工具：按需下载、路径配置与状态。"""

    def __init__(self, *, cfg: AcusConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._rows: dict[str, tuple[ExternalToolSpec, LineEdit, BodyLabel]] = {}
        self._install_thread: QThread | None = None

        tools_hint_text = (
            "外部程序默认安装在应用目录下的 `.tools/`（不随主程序 exe 打包）。"
            " 可在此一键下载或手动浏览；保存后写入 `ACUS/.config.json`。\n"
            f"安装根目录：`{tools_root_dir()}`"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(14)
        layout.addWidget(rich_hint_label(tools_hint_text, self, color="#6B7280"))

        for spec in ALL_TOOLS:
            layout.addWidget(self._make_tool_card(spec))

        py_card = CardWidget(self)
        py_lay = QVBoxLayout(py_card)
        py_lay.setContentsMargins(16, 16, 16, 16)
        py_lay.setSpacing(8)
        py_lay.addWidget(CaptionLabel("Python 组件（pip / 打包内置）", self))
        for name, desc, _ in _BUILTIN_PYTHON:
            py_lay.addWidget(BodyLabel(f"• {name}：{desc}", self))
        layout.addWidget(py_card)

        row = QHBoxLayout()
        row.addStretch(1)
        open_dir = PushButton("打开 .tools 目录", self)
        open_dir.clicked.connect(self._open_tools_dir)
        doc_btn = PushButton("导出依赖说明…", self)
        doc_btn.clicked.connect(self._export_inventory)
        row.addWidget(open_dir)
        row.addWidget(doc_btn)
        layout.addLayout(row)
        layout.addStretch(1)

        self.refresh_status()

    def _make_tool_card(self, spec: ExternalToolSpec) -> CardWidget:
        card = CardWidget(self)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        title = BodyLabel(f"{spec.name}{'（可选）' if spec.optional else ''}", self)
        title.setStyleSheet("font-weight:600;")
        lay.addWidget(title)
        lay.addWidget(BodyLabel(f"用途：{spec.used_for}", self))
        lay.addWidget(BodyLabel(spec.description, self))

        status_lbl = BodyLabel("", self)
        status_lbl.setWordWrap(True)
        status_lbl.setStyleSheet("color:#6B7280;font-size:12px;")
        lay.addWidget(status_lbl)

        path_edit = LineEdit(self)
        path_edit.setPlaceholderText(f"留空则使用 .tools/{spec.default_rel}")
        raw = getattr(self._cfg, spec.config_field, "") or ""
        if raw:
            path_edit.setText(str(raw))
        lay.addWidget(path_edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        browse = PushButton("浏览…", self)
        browse.clicked.connect(lambda _=False, s=spec, e=path_edit: self._browse(s, e))
        dl_btn = PushButton("下载并安装", self)
        dl_btn.setEnabled(bool(spec.download_url))
        dl_btn.clicked.connect(lambda _=False, s=spec: self._download(s))
        if spec.help_url:
            help_btn = PushButton("说明 / 发布页", self)
            help_btn.clicked.connect(lambda _=False, u=spec.help_url: QDesktopServices.openUrl(QUrl(u)))
            btn_row.addWidget(help_btn)
        btn_row.addWidget(browse)
        btn_row.addWidget(dl_btn)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self._rows[spec.id] = (spec, path_edit, status_lbl)
        return card

    def refresh_status(self) -> None:
        apply_resolved_paths_to_config(self._cfg)
        for spec, edit, status_lbl in self._rows.values():
            if not edit.text().strip():
                p = getattr(self._cfg, spec.config_field, "") or ""
                if p:
                    edit.setText(str(p))
            status_lbl.setText(tool_status(spec, self._cfg))

    def apply_fields(self) -> bool:
        for spec, edit, _ in self._rows.values():
            raw = edit.text().strip()
            if not raw:
                set_config_path(self._cfg, spec, None)
                continue
            p = Path(raw).expanduser()
            if not p.is_file():
                fly_warning(
                    self,
                    "路径无效",
                    f"{spec.name} 必须指向可执行文件：\n{raw}",
                )
                return False
            set_config_path(self._cfg, spec, p)
        self._cfg.save()
        self.refresh_status()
        return True

    def _browse(self, spec: ExternalToolSpec, edit: LineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"选择 {spec.name}",
            "",
            f"可执行文件 ({spec.exe_name});;所有文件 (*.*)",
        )
        if path:
            edit.setText(path)
            set_config_path(self._cfg, spec, Path(path))
            self._cfg.save()
            self.refresh_status()

    def _download(self, spec: ExternalToolSpec) -> None:
        if self._install_thread is not None:
            fly_message(self, "请稍候", "已有下载任务在进行中。")
            return
        if not spec.download_url:
            fly_warning(self, "无法下载", f"{spec.name} 需手动安装，请使用「浏览」或查看发布页。")
            return

        from .fluent_dialogs import safe_dismiss_modal_progress_dialog
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt

        dlg = QProgressDialog(f"正在安装 {spec.name}…", None, 0, 0, self)
        dlg.setWindowTitle("外部工具")
        dlg.setMinimumDuration(0)
        dlg.setCancelButton(None)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.show()

        thread = QThread()
        worker = _ToolInstallWorker(spec, self._cfg)
        worker.moveToThread(thread)

        def on_progress(msg: str) -> None:
            dlg.setLabelText(msg)

        def on_done(payload: object) -> None:
            safe_dismiss_modal_progress_dialog(dlg)
            if isinstance(payload, tuple) and len(payload) == 2:
                kind, data = payload
                if kind == "ok" and isinstance(data, Path):
                    spec_row = self._rows.get(spec.id)
                    if spec_row:
                        spec_row[1].setText(str(data))
                    fly_message(self, "完成", f"{spec.name} 已安装：\n{data}")
                    self.refresh_status()
                    return
                if kind == "err":
                    fly_critical(self, "安装失败", str(data))
                    return
            fly_critical(self, "安装失败", "未知错误")

        def on_stopped() -> None:
            th = self._install_thread
            self._install_thread = None
            finalize_qthread(th)

        worker.progress.connect(on_progress)
        worker.finished.connect(on_done)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(on_stopped)
        self._install_thread = thread
        thread.started.connect(worker.run)
        thread.start()

    def await_bg_threads(self) -> None:
        await_qthreads(self._install_thread)

    def _open_tools_dir(self) -> None:
        d = tools_root_dir()
        d.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(d)))

    def _export_inventory(self) -> None:
        try:
            p = write_inventory_file()
            fly_message(self, "已导出", f"依赖说明已写入：\n{p}")
        except Exception as e:
            fly_critical(self, "导出失败", str(e))
