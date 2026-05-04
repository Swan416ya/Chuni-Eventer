from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from ..game_data_index import enumerate_game_data_roots
from ..system_voice_pack import (
    LOGICAL_IDS_42,
    allocate_voice_id,
    cue_folder_name,
    cue_numeric_id_for_voice,
    load_doc_descriptions,
    pack_system_voice_to_acus,
    system_voice_dir_name,
    validate_voice_folder,
)
from .fluent_dialogs import fly_critical, fly_message
from .fluent_table import apply_fluent_sheet_table, sheet_list_hint_muted_colors
from .sysvoice_preview_dialog import SysvoicePreviewDialog


class _PackWorker(QObject):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        *,
        acus_root: Path,
        audio_folder: Path,
        voice_id: int,
        display_name: str,
        preview_dds: Path,
    ) -> None:
        super().__init__()
        self._acus_root = acus_root
        self._audio_folder = audio_folder
        self._voice_id = voice_id
        self._display_name = display_name
        self._preview_dds = preview_dds

    def run(self) -> None:
        try:
            sv, cue = pack_system_voice_to_acus(
                acus_root=self._acus_root,
                audio_folder=self._audio_folder,
                voice_id=self._voice_id,
                display_name=self._display_name,
                preview_dds=self._preview_dds,
            )
            self.done.emit(
                f"已写入：\n• {sv}\n• {cue}\n\n"
                f"系统语音 ID：{self._voice_id}（{system_voice_dir_name(self._voice_id)}）\n"
                f"Cue：{cue_folder_name(cue_numeric_id_for_voice(self._voice_id))}"
            )
        except Exception as e:
            self.failed.emit(str(e))


class SystemVoicePackPage(QWidget):
    """42 条系统语音打包 + 预览图说明。"""

    packed = pyqtSignal()

    def __init__(
        self,
        *,
        acus_root: Path,
        get_tool_path,
        get_game_root,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path
        self._get_game_root = get_game_root
        self._audio_folder: Path | None = None
        self._preview_dds: Path | None = None
        self._voice_id: int | None = None
        self._thread: QThread | None = None
        self._worker: _PackWorker | None = None

        desc_map = load_doc_descriptions()

        title = BodyLabel(
            "请准备恰好 42 条音频，文件名与逻辑序号一致：1～24、35～52（扩展名 mp3/wav/flac 等）。"
            " ID 从 700 起自动避让 ACUS 与已配置游戏目录内已有资源；Cue 目录为 cueFile(10000+ID)。",
            self,
        )
        title.setWordWrap(True)
        title.setTextColor("#374151", "#D1D5DB")

        self._id_label = QLabel(self)
        self._folder_edit = LineEdit(self)
        self._folder_edit.setPlaceholderText("选择含 42 条音频的文件夹…")
        self._name_edit = LineEdit(self)
        self._name_edit.setPlaceholderText("游戏内显示名（写入 SystemVoice.xml）")
        self._name_edit.setText("自定义系统语音")

        browse = PushButton("选择文件夹…", self)
        browse.clicked.connect(self._on_browse)
        refresh_id = PushButton("重新分配 ID", self)
        refresh_id.setToolTip("从 700 / cue 10700 起重新扫描第一个可用组合")
        refresh_id.clicked.connect(self._refresh_ids)

        prev_btn = PushButton("预览图编辑器…", self)
        prev_btn.clicked.connect(self._on_preview_dialog)

        self._pack_btn = PrimaryPushButton("转码并写入 ACUS", self)
        self._pack_btn.clicked.connect(self._on_pack)

        self._status = QLabel("", self)
        self._status.setWordWrap(True)

        table_tip = BodyLabel(
            "共 42 条：左列为建议文件名（示例形如 50.mp4/50.wav，实际任选 mp3、wav、flac 等一种扩展名即可）；"
            "右列为对照表说明。",
            self,
        )
        table_tip.setWordWrap(True)
        sheet_list_hint_muted_colors(table_tip)

        self._table = QTableWidget(self)
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["文件名", "说明"])
        apply_fluent_sheet_table(self._table)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for lid in LOGICAL_IDS_42:
            row = self._table.rowCount()
            self._table.insertRow(row)
            name_cell = QTableWidgetItem(f"{lid}.mp4/{lid}.wav")
            desc_cell = QTableWidgetItem(desc_map.get(lid, ""))
            self._table.setItem(row, 0, name_cell)
            self._table.setItem(row, 1, desc_cell)
        self._table.resizeRowsToContents()

        list_card = CardWidget(self)
        list_lay = QVBoxLayout(list_card)
        list_lay.setContentsMargins(16, 14, 16, 14)
        list_lay.setSpacing(8)
        list_lay.addWidget(table_tip)
        list_lay.addWidget(self._table, stretch=1)

        top_row = QHBoxLayout()
        top_row.addWidget(self._folder_edit, stretch=1)
        top_row.addWidget(browse)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("显示名", self))
        name_row.addWidget(self._name_edit, stretch=1)
        name_row.addWidget(refresh_id)

        card = CardWidget(self)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 14, 16, 14)
        cv.setSpacing(10)
        cv.addWidget(title)
        cv.addWidget(self._id_label)
        cv.addLayout(top_row)
        cv.addLayout(name_row)
        cv.addWidget(prev_btn)
        cv.addWidget(self._status)
        cv.addWidget(self._pack_btn)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(12)
        lay.addWidget(card)
        lay.addWidget(list_card, stretch=1)

        self._refresh_ids()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        if self._voice_id is None:
            self._refresh_ids()

    def _game_roots(self) -> list[Path]:
        raw = (self._get_game_root() or "").strip()
        if not raw:
            return []
        gr = Path(raw).expanduser()
        if not gr.is_dir():
            return []
        return enumerate_game_data_roots(gr)

    def _refresh_ids(self) -> None:
        try:
            vid = allocate_voice_id(acus_root=self._acus_root, game_roots=self._game_roots(), start_voice_id=700)
            self._voice_id = vid
            cid = cue_numeric_id_for_voice(vid)
            self._id_label.setText(
                f"将使用系统语音 ID：{vid}（目录 {system_voice_dir_name(vid)}），"
                f"Cue 目录 {cue_folder_name(cid)}（numeric id {cid}）。"
            )
        except Exception as e:
            self._voice_id = None
            self._id_label.setText(f"分配 ID 失败：{e}")

    def _on_browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择音频文件夹")
        if not d:
            return
        folder = Path(d).expanduser()
        self._audio_folder = folder
        self._folder_edit.setText(str(folder))
        missing, _found, extra = validate_voice_folder(folder)
        if extra:
            self._status.setText(
                f"已选择：{folder}\n警告：存在表外文件（打包时将报错）：" + ", ".join(extra[:12]) + ("…" if len(extra) > 12 else "")
            )
        elif missing:
            self._status.setText(
                f"已选择：{folder}\n缺少 {len(missing)} 个文件，序号：" + ", ".join(missing[:40]) + ("…" if len(missing) > 40 else "")
            )
        else:
            self._status.setText(f"已选择：{folder}\n42 条音频已齐。")

    def _on_preview_dialog(self) -> None:
        dlg = SysvoicePreviewDialog(tool_path=self._get_tool_path(), parent=self.window())
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        if dlg.result_dds_path and dlg.result_dds_path.is_file():
            self._preview_dds = dlg.result_dds_path
            self._status.setText(f"已生成预览 DDS：{self._preview_dds}")

    def _on_pack(self) -> None:
        if self._voice_id is None:
            fly_critical(self.window(), "错误", "无法分配系统语音 ID。")
            return
        if self._audio_folder is None or not self._audio_folder.is_dir():
            fly_critical(self.window(), "错误", "请先选择音频文件夹。")
            return
        missing, _f, extra = validate_voice_folder(self._audio_folder)
        if missing:
            fly_critical(self.window(), "缺文件", "缺少音频：" + ", ".join(missing[:50]))
            return
        if extra:
            fly_critical(self.window(), "多余文件", "请移除表外文件后再打包：" + ", ".join(extra[:30]))
            return
        if self._preview_dds is None or not self._preview_dds.is_file():
            fly_critical(self.window(), "错误", "请先用「预览图编辑器」生成 BC3 DDS。")
            return
        self._pack_btn.setEnabled(False)
        self._thread = QThread(self)
        self._worker = _PackWorker(
            acus_root=self._acus_root,
            audio_folder=self._audio_folder,
            voice_id=self._voice_id,
            display_name=self._name_edit.text().strip(),
            preview_dds=self._preview_dds,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_pack_done)
        self._worker.failed.connect(self._on_pack_failed)
        self._worker.done.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_pack_thread_refs)
        self._thread.start()

    def _on_pack_done(self, msg: str) -> None:
        fly_message(self.window(), "完成", msg)
        self.packed.emit()
        self._refresh_ids()
        self._preview_dds = None

    def _on_pack_failed(self, msg: str) -> None:
        fly_critical(self.window(), "打包失败", msg)

    def _clear_pack_thread_refs(self) -> None:
        self._pack_btn.setEnabled(True)
        self._worker = None
        self._thread = None
