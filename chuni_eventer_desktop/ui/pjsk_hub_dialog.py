from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SpinBox,
)

from ..dds_quicktex import quicktex_available
from ..pjsk_acus_install import (
    DEFAULT_STAGE_ID,
    DEFAULT_STAGE_STR,
    PjskAcusInstallOptions,
    PjskLocalBundle,
    chuni_slots_with_c2s,
    install_pjsk_bundle_to_acus,
    iter_local_pjsk_bundles,
    next_chuni_music_id,
)
from ..pjsk_sheet_client import pjsk_cache_root
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_question, fly_warning
from .fluent_table import apply_fluent_sheet_table
from .pjsk_sus_download_dialog import PjskSusDownloadDialog


class _InstallToAcusThread(QThread):
    ok = pyqtSignal()
    fail = pyqtSignal(str)
    progress = pyqtSignal(str, float)

    def __init__(
        self,
        *,
        acus_root: Path,
        bundle: PjskLocalBundle,
        opts: PjskAcusInstallOptions,
        tool_path: Path | None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus = acus_root
        self._bundle = bundle
        self._opts = opts
        self._tool = tool_path

    def run(self) -> None:
        try:

            def log(_msg: str) -> None:
                return

            def prog(msg: str, t: float) -> None:
                self.progress.emit(msg, float(t))

            install_pjsk_bundle_to_acus(
                self._acus,
                self._bundle,
                self._opts,
                tool_path=self._tool,
                log=log,
                on_progress=prog,
            )
            self.ok.emit()
        except Exception as e:
            self.fail.emit(str(e))


_SLOT_LABELS: dict[str, str] = {
    "BASIC": "BASIC（PJSK Normal）",
    "ADVANCED": "ADVANCED（PJSK Hard）",
    "EXPERT": "EXPERT",
    "MASTER": "MASTER",
    "ULTIMA": "ULTIMA（PJSK Append）",
}


class PjskInstallToAcusDialog(FluentCaptionDialog):
    """将选中的 pjsk_cache 条目写入 ACUS（Music + cueFile + 可选 ULT 事件）。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        bundle: PjskLocalBundle,
        default_chuni_id: int,
        tool_path: Path | None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("转写到 ACUS（中二乐曲）")
        self.setModal(True)
        self.resize(520, 560)
        self._acus_root = acus_root.resolve()
        self._bundle = bundle
        self._tool = tool_path
        self._thread: _InstallToAcusThread | None = None
        self._level_spins: dict[str, tuple[SpinBox, SpinBox]] = {}

        m = bundle.manifest
        title = str(m.get("title") or "").strip()
        comp = str(m.get("composer") or "").strip()

        self._id_spin = SpinBox(self)
        self._id_spin.setRange(1, 999999)
        self._id_spin.setValue(int(default_chuni_id))

        self._title = LineEdit(self)
        self._title.setText(title)
        self._artist = LineEdit(self)
        self._artist.setText(comp)
        self._sort = LineEdit(self)
        self._sort.setText(title)
        self._sort.setPlaceholderText("通常与曲名相同")

        self._stage_id = SpinBox(self)
        self._stage_id.setRange(-1, 999999)
        self._stage_id.setValue(DEFAULT_STAGE_ID)
        self._stage_str = LineEdit(self)
        self._stage_str.setText(DEFAULT_STAGE_STR)

        self._ult_event = CheckBox("存在 ULTIMA 谱面时生成 ULT 解锁事件（type=3）", self)
        self._ult_event.setChecked(True)

        levels_box = CardWidget(self)
        levels_lay = QVBoxLayout(levels_box)
        levels_lay.setContentsMargins(12, 12, 12, 12)
        levels_lay.setSpacing(8)
        levels_lay.addWidget(
            BodyLabel("各难度定数（Music.xml level / levelDecimal）", levels_box)
        )
        levels_grid = QGridLayout()
        present = chuni_slots_with_c2s(bundle)
        if not present:
            levels_grid.addWidget(
                QLabel("当前缓存无可用 SUS/c2s，请先下载谱面后再转写。", levels_box),
                0,
                0,
                1,
                3,
            )
        else:
            levels_grid.addWidget(QLabel("难度"), 0, 0)
            levels_grid.addWidget(QLabel("等级"), 0, 1)
            levels_grid.addWidget(QLabel("levelDecimal（0～99）"), 0, 2)
        for row, slot in enumerate(present, start=1):
            lab = QLabel(_SLOT_LABELS.get(slot, slot), levels_box)
            w_lv = SpinBox(levels_box)
            w_lv.setRange(1, 15)
            w_lv.setValue(13)
            w_dec = SpinBox(levels_box)
            w_dec.setRange(0, 99)
            w_dec.setValue(0)
            w_dec.setToolTip("写入 XML 的 levelDecimal；显示为小数时多为整十，如 50→13.5")
            levels_grid.addWidget(lab, row, 0)
            levels_grid.addWidget(w_lv, row, 1)
            levels_grid.addWidget(w_dec, row, 2)
            self._level_spins[slot] = (w_lv, w_dec)
        levels_lay.addLayout(levels_grid)

        form = QFormLayout()
        form.addRow("中二乐曲 ID", self._id_spin)
        form.addRow("曲名 (name.str)", self._title)
        form.addRow("艺术家 (artist.str)", self._artist)
        form.addRow("排序名 (sortName)", self._sort)
        form.addRow("舞台 ID (stageName.id)", self._stage_id)
        form.addRow("舞台 str (stageName.str)", self._stage_str)
        form.addRow("", self._ult_event)

        hint = BodyLabel(
            "releaseTagName 固定为 -2 / PJSK；音频试听段固定为 0～30 秒。"
            "依赖说明见 docs/pjsk_acus_dependencies_zh.md；需 PyCriCodecsEx、ffmpeg（PATH）、封面 封面.png。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6b7280;font-size:12px;")

        self._prog_label = QLabel("", self)
        self._prog_label.setWordWrap(True)
        self._prog_label.setStyleSheet("color:#374151;font-size:12px;")
        self._prog_label.hide()
        self._prog_bar = QProgressBar(self)
        self._prog_bar.setRange(0, 1000)
        self._prog_bar.setValue(0)
        self._prog_bar.setTextVisible(True)
        self._prog_bar.hide()

        ok = PrimaryPushButton("写入 ACUS", self)
        ok.clicked.connect(self._run)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)

        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(12)
        root.addWidget(hint)
        root.addLayout(form)
        root.addWidget(levels_box)
        root.addWidget(self._prog_label)
        root.addWidget(self._prog_bar)
        root.addLayout(row)

    def _run(self) -> None:
        mid = int(self._id_spin.value())
        mdir = self._acus_root / "music" / f"music{mid:04d}"
        if mdir.exists():
            fly_warning(self, "ID 冲突", f"目录已存在：{mdir}")
            return
        if not self._level_spins:
            fly_warning(self, "无谱面", "当前缓存没有可用的 SUS/c2s，无法转写。")
            return
        fumen_levels: dict[str, tuple[int, int]] = {}
        for slot, (w_lv, w_dec) in self._level_spins.items():
            fumen_levels[slot] = (int(w_lv.value()), int(w_dec.value()))
        opts = PjskAcusInstallOptions(
            chuni_music_id=mid,
            title=self._title.text().strip() or str(mid),
            artist=self._artist.text().strip() or "PJSK",
            sort_name=self._sort.text().strip() or self._title.text().strip() or str(mid),
            stage_id=int(self._stage_id.value()),
            stage_str=self._stage_str.text().strip() or DEFAULT_STAGE_STR,
            fumen_levels=fumen_levels,
            preview_start_sec=0.0,
            preview_stop_sec=30.0,
            create_ultima_event=self._ult_event.isChecked(),
        )
        self._prog_label.show()
        self._prog_bar.show()
        self._prog_bar.setValue(0)
        self._prog_label.setText("开始转换…")
        self.setEnabled(False)
        th = _InstallToAcusThread(
            acus_root=self._acus_root,
            bundle=self._bundle,
            opts=opts,
            tool_path=self._tool,
            parent=self,
        )
        self._thread = th
        th.progress.connect(self._on_thread_progress)
        th.ok.connect(self._on_ok)
        th.fail.connect(self._on_fail)
        th.finished.connect(self._on_thread_done)
        th.start()

    def _on_thread_progress(self, msg: str, ratio: float) -> None:
        self._prog_label.setText(msg)
        self._prog_bar.setValue(min(1000, int(max(0.0, min(1.0, ratio)) * 1000)))

    def _on_ok(self) -> None:
        self._prog_bar.setValue(1000)
        self._prog_label.setText("完成")
        fly_message(self, "完成", "已写入 ACUS。可在管理页刷新查看乐曲与事件。")
        self.accept()

    def _on_fail(self, msg: str) -> None:
        fly_critical(self, "写入失败", msg)
        self._prog_label.hide()
        self._prog_bar.hide()

    def _on_thread_done(self) -> None:
        self._thread = None
        if not self.isEnabled():
            self.setEnabled(True)


class PjskHubDialog(FluentCaptionDialog):
    """
    PJSK 入口：主体为本地 pjsk_cache 列表；可打开曲目库下载，或将选中项转写到 ACUS。
    """

    def __init__(
        self,
        *,
        acus_root: Path,
        get_tool_path,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("Project SEKAI 谱面（本地缓存）")
        self.setModal(True)
        self.resize(840, 580)
        self._acus_root = acus_root.resolve()
        self._get_tool_path = get_tool_path
        self._cache_root = pjsk_cache_root(self._acus_root)
        self._bundles: list[PjskLocalBundle] = []

        card = CardWidget(self)
        c2s_unusable = BodyLabel(
            "SUS→c2s 现改为调用 PenguinTools.CLI。"
            "若本机未正确放置 PenguinTools.CLI 或其 assets 目录，「转写到 ACUS」时会直接报错而不是回退到旧的本地转换器。"
        )
        c2s_unusable.setWordWrap(True)
        c2s_unusable.setStyleSheet("color: #0f766e; font-weight: 600;")

        top = BodyLabel(
            f"下列为已下载到本地的 PJSK 资源（{self._cache_root.as_posix()}）。"
            "选中一行后可「转写到 ACUS」生成 music、cueFile、Music.xml 与 ACB/AWB；"
            "或打开「从网络下载新曲」补充缓存。"
        )
        top.setWordWrap(True)

        self._empty_hint = BodyLabel("", card)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color:#9ca3af;")
        self._empty_hint.hide()

        self._table = QTableWidget(0, 5, card)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(
            ["PJSK ID", "曲名", "作曲家", "谱面", "音频 ACB"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        cly.addWidget(c2s_unusable)
        cly.addWidget(top)
        cly.addWidget(self._empty_hint)
        cly.addWidget(self._table, stretch=1)

        refresh = PushButton("刷新列表", self)
        refresh.clicked.connect(self._reload_local)
        dl = PrimaryPushButton("从网络下载新曲…", self)
        dl.clicked.connect(self._open_catalog)
        install = PrimaryPushButton("转写选中到 ACUS…", self)
        install.clicked.connect(self._open_install)
        close = PushButton("关闭", self)
        close.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addStretch(1)
        row.addWidget(dl)
        row.addWidget(install)
        row.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(card, stretch=1)
        lay.addLayout(row)

        self._reload_local()

    def _reload_local(self) -> None:
        self._bundles = iter_local_pjsk_bundles(self._cache_root)
        self._table.setRowCount(len(self._bundles))
        for i, b in enumerate(self._bundles):
            present_slots = chuni_slots_with_c2s(b)
            n_charts = len(present_slots)
            has_ult = "ULTIMA" in present_slots
            audio = b.manifest.get("audio")
            acb_ok = False
            if isinstance(audio, dict):
                ch = audio.get("chuni")
                if isinstance(ch, dict) and ch.get("acbFile"):
                    acb_ok = True
            self._table.setItem(i, 0, QTableWidgetItem(str(b.pjsk_music_id)))
            self._table.setItem(i, 1, QTableWidgetItem(b.title))
            self._table.setItem(i, 2, QTableWidgetItem(b.composer))
            slot_txt = f"{n_charts} 档" + (" · ULT" if has_ult else "")
            self._table.setItem(i, 3, QTableWidgetItem(slot_txt))
            self._table.setItem(i, 4, QTableWidgetItem("有" if acb_ok else "无"))
            for c in range(5):
                it = self._table.item(i, c)
                if it:
                    it.setData(Qt.ItemDataRole.UserRole, b.pjsk_music_id)
        if not self._bundles:
            self._table.setRowCount(0)
            self._empty_hint.setText("暂无本地缓存，请点击「从网络下载新曲」。")
            self._empty_hint.show()
        else:
            self._empty_hint.hide()

    def _selected_bundle(self) -> PjskLocalBundle | None:
        r = self._table.currentRow()
        if r < 0 or r >= len(self._bundles):
            return None
        return self._bundles[r]

    def _open_catalog(self) -> None:
        dlg = PjskSusDownloadDialog(
            acus_root=self._acus_root,
            parent=self,
            on_installed=lambda: self._reload_local(),
        )
        dlg.exec()
        self._reload_local()

    def _open_install(self) -> None:
        b = self._selected_bundle()
        if b is None:
            fly_warning(self, "未选择", "请先在列表中选择一首本地缓存曲目。")
            return
        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            if not fly_question(
                self,
                "封面转 DDS",
                "未安装 quicktex 且未在设置中配置 compressonatorcli，可能无法将 封面.png 转为 DDS。\n"
                "是否仍继续（若已有工具可稍后在设置中配置后重试）？",
                yes_text="继续",
                no_text="取消",
            ):
                return
        default_id = next_chuni_music_id(self._acus_root, start=7000)
        dlg = PjskInstallToAcusDialog(
            acus_root=self._acus_root,
            bundle=b,
            default_chuni_id=default_id,
            tool_path=tool,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload_local()
