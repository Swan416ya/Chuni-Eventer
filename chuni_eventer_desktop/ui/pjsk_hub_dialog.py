from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QCloseEvent
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

from ..pjsk2chuni import pipeline
from ..pjsk_acus_install import (
    DEFAULT_STAGE_ID,
    DEFAULT_STAGE_STR,
    PjskLocalBundle,
    backfill_bundle_play_levels,
    bundle_play_levels,
    chuni_slot_sources,
    chuni_slots_with_c2s,
    iter_local_pjsk_bundles,
    next_chuni_music_id,
)
from ..penguin_tools_cli import resolve_penguin_tools_cli
from ..pjsk_audio_chuni import find_ffmpeg
from ..pjsk_sheet_client import load_difficulties_index, pjsk_cache_root
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .fluent_table import apply_fluent_sheet_table
from .pjsk_sus_download_dialog import PjskSusDownloadDialog
from .qthread_lifecycle import await_qthreads, finalize_qthread, qthread_running_safe

_SLOT_LABELS: dict[str, str] = {
    "BASIC": "BASIC（PJSK Normal）",
    "ADVANCED": "ADVANCED（PJSK Hard）",
    "EXPERT": "EXPERT",
    "MASTER": "MASTER",
    "ULTIMA": "ULTIMA（PJSK Append）",
}

# 查不到 PJSK 等级（老缓存 + 离线）时的兜底定数
_FALLBACK_LEVELS: dict[str, tuple[int, int]] = {
    "BASIC": (4, 0),
    "ADVANCED": (8, 60),
    "EXPERT": (12, 60),
    "MASTER": (14, 60),
    "ULTIMA": (15, 0),
}


class _LevelIndexThread(QThread):
    """补全老缓存的 PJSK 等级（1..38）：拉一次曲目难度索引。"""

    ok = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.ok.emit(load_difficulties_index())
        except Exception:  # noqa: BLE001 — 离线/镜像不可用时静默降级
            self.ok.emit({})


class _ConvertThread(QThread):
    """转换 + 打包 + 写入 ACUS（全程在子线程，避免界面卡死）。"""

    ok = pyqtSignal(object)
    fail = pyqtSignal(str)
    progress = pyqtSignal(str, float)

    def __init__(
        self,
        *,
        acus_root: Path,
        request: pipeline.BuildRequest,
        create_ultima_event: bool,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self._acus = acus_root
        self._req = request
        self._create_ultima_event = create_ultima_event

    def run(self) -> None:
        result: pipeline.BuildResult | None = None
        try:
            result = pipeline.build_option_package(
                self._req,
                log=lambda m: self.progress.emit(m, -1.0),
                on_progress=lambda m, r: self.progress.emit(m, float(r)),
            )
            pipeline.install_option_package_to_acus(
                self._acus,
                result,
                log=lambda m: self.progress.emit(m, -1.0),
                on_progress=lambda m, r: self.progress.emit(m, float(r)),
                create_ultima_event=self._create_ultima_event,
            )
            self.ok.emit(result)
        except Exception as e:  # noqa: BLE001
            self.fail.emit(str(e))
        finally:
            if result is not None:
                pipeline.cleanup_build_output(result)


class PjskConvertToAcusDialog(FluentCaptionDialog):
    """PJSK 缓存曲目 →（上游转谱逻辑 + PenguinTools）→ 写入 ACUS。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        bundle: PjskLocalBundle,
        default_chuni_id: int,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("PJSK 转谱并写入 ACUS")
        self.setModal(True)
        self.resize(560, 620)
        self._acus_root = acus_root.resolve()
        self._bundle = bundle
        self._thread: _ConvertThread | None = None
        self._pending_accept = False
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
        self._artist.setText(comp or "PJSK")
        self._creator = LineEdit(self)
        self._creator.setText("chunieventer")
        self._creator.setToolTip("写入 c2s 的 CREATOR（谱师）")

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
            BodyLabel("各难度定数（写入 Music.xml 的 level / levelDecimal）", levels_box)
        )
        levels_grid = QGridLayout()
        present = chuni_slots_with_c2s(bundle)
        play_levels = bundle_play_levels(bundle)
        if play_levels:
            levels_hint = (
                "默认定数 = PJSK 等级（1～38）等比映射到中二 1～15.5："
                "定数 = 1 + (PJSK等级 - 1) × 14.5 / 37"
            )
        else:
            levels_hint = "未记录 PJSK 等级（老缓存），已用兜底值；可手工修改"
        hint_lv = BodyLabel(levels_hint, levels_box)
        hint_lv.setWordWrap(True)
        hint_lv.setStyleSheet("color:#6b7280;font-size:12px;")
        levels_lay.addWidget(hint_lv)
        if not present:
            levels_grid.addWidget(
                QLabel("当前缓存无可用 SUS，请先下载谱面后再转谱。", levels_box), 0, 0, 1, 3
            )
        else:
            levels_grid.addWidget(QLabel("难度"), 0, 0)
            levels_grid.addWidget(QLabel("等级"), 0, 1)
            levels_grid.addWidget(QLabel("小数（0～99）"), 0, 2)
        for row, slot in enumerate(present, start=1):
            play_level = play_levels.get(slot)
            if play_level:
                lv, dec = pipeline.const_to_level_pair(
                    pipeline.pjsk_level_to_chuni_const(play_level)
                )
                slot_label = f"{_SLOT_LABELS.get(slot, slot)} · PJSK {play_level}"
            else:
                lv, dec = _FALLBACK_LEVELS.get(slot, (13, 0))
                slot_label = _SLOT_LABELS.get(slot, slot)
            lab = QLabel(slot_label, levels_box)
            w_lv = SpinBox(levels_box)
            w_lv.setRange(1, 15)
            w_dec = SpinBox(levels_box)
            w_dec.setRange(0, 99)
            w_dec.setToolTip("levelDecimal；显示为小数时多为整十，如 50→13.5")
            w_lv.setValue(lv)
            w_dec.setValue(dec)
            levels_grid.addWidget(lab, row, 0)
            levels_grid.addWidget(w_lv, row, 1)
            levels_grid.addWidget(w_dec, row, 2)
            self._level_spins[slot] = (w_lv, w_dec)
        levels_lay.addLayout(levels_grid)

        form = QFormLayout()
        form.addRow("中二乐曲 ID", self._id_spin)
        form.addRow("曲名 (name.str)", self._title)
        form.addRow("艺术家 (artist.str)", self._artist)
        form.addRow("谱师 (c2s CREATOR)", self._creator)
        form.addRow("舞台 ID (stageName.id)", self._stage_id)
        form.addRow("舞台 str (stageName.str)", self._stage_str)
        form.addRow("", self._ult_event)

        hint = BodyLabel(
            "谱面转换使用「PJSK 官谱语义」转换器（装饰音符降级、曲线烘焙、变速保留），"
            "再由 PenguinTools.CLI 打包 c2s / 封面 DDS / HCA 音频与 Music.xml。\n"
            "音频对齐由实测前导静音自动决定（不再固定裁 9 秒）；releaseTag 固定 -2 / PJSK，genre 为 niconico。"
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

        ok = PrimaryPushButton("转换并写入 ACUS", self)
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

    def _build_request(self) -> pipeline.BuildRequest | None:
        mid = int(self._id_spin.value())
        mdir = self._acus_root / "music" / f"music{mid:04d}"
        if mdir.exists():
            fly_warning(self, "ID 冲突", f"目录已存在：{mdir}")
            return None
        sources = chuni_slot_sources(self._bundle)
        if not sources:
            fly_warning(self, "无谱面", "当前缓存没有可用的 SUS，无法转换。")
            return None
        if not any(s.slot in ("BASIC", "ADVANCED", "EXPERT", "MASTER") for s in sources):
            fly_warning(self, "无可用难度", "至少需要 BASIC～MASTER 中一张谱面。")
            return None
        jacket = self._bundle.root / "封面.png"
        if not jacket.is_file():
            fly_warning(self, "缺少封面", f"未找到封面：{jacket}")
            return None
        audio = self._bundle.manifest.get("audio")
        rel = audio.get("file") if isinstance(audio, dict) else None
        audio_path = (self._bundle.root / str(rel)).resolve() if isinstance(rel, str) and rel.strip() else None
        if audio_path is None or not audio_path.is_file():
            fly_warning(
                self,
                "缺少音频",
                "该缓存没有完整音频（下载时未选择人声版本）。\n请重新下载该曲并选择人声版本。",
            )
            return None

        levels: dict[str, float] = {}
        for slot, (w_lv, w_dec) in self._level_spins.items():
            levels[slot] = float(int(w_lv.value())) + float(int(w_dec.value())) / 100.0

        return pipeline.BuildRequest(
            bundle_root=self._bundle.root,
            slots=sources,
            chuni_music_id=mid,
            title=self._title.text().strip() or self._bundle.title or str(mid),
            artist=self._artist.text().strip() or self._bundle.composer or "PJSK",
            creator=self._creator.text().strip() or "chunieventer",
            levels=levels,
            jacket_png=jacket,
            audio_src=audio_path,
            stage_id=int(self._stage_id.value()),
            stage_str=self._stage_str.text().strip() or DEFAULT_STAGE_STR,
        )

    def _run(self) -> None:
        req = self._build_request()
        if req is None:
            return
        if resolve_penguin_tools_cli() is None:
            fly_critical(
                self,
                "缺少 PenguinTools.CLI",
                "本功能需要官方 PenguinTools.CLI（用于 c2s 转换、封面 DDS、HCA 音频与 XML）。\n"
                "请在「设置 → 外部工具」中下载或指定其路径。",
            )
            return
        if find_ffmpeg() is None:
            fly_critical(
                self,
                "缺少 ffmpeg",
                "本功能需要 ffmpeg 解码音频（测量前导静音 / 生成 48k WAV）。\n"
                "请在「设置 → 外部工具」中下载或指定其路径。",
            )
            return
        self._prog_label.show()
        self._prog_bar.show()
        self._prog_bar.setRange(0, 1000)
        self._prog_bar.setValue(0)
        self._prog_label.setText("开始转换…")
        self.setEnabled(False)
        th = _ConvertThread(
            acus_root=self._acus_root,
            request=req,
            create_ultima_event=self._ult_event.isChecked(),
            parent=None,
        )
        self._thread = th
        th.progress.connect(self._on_thread_progress)
        th.ok.connect(self._on_ok)
        th.fail.connect(self._on_fail)
        th.finished.connect(self._on_thread_done)
        th.start()

    def _on_thread_progress(self, msg: str, ratio: float) -> None:
        self._prog_label.setText(msg)
        if ratio < 0:
            return
        self._prog_bar.setRange(0, 1000)
        self._prog_bar.setValue(min(1000, int(max(0.0, min(1.0, ratio)) * 1000)))

    def _on_ok(self, result: object) -> None:
        self._prog_bar.setValue(1000)
        slots = ", ".join(getattr(result, "slots", {}).keys()) if result is not None else ""
        warn = getattr(result, "warnings", []) or []
        text = f"已写入 ACUS。难度：{slots}"
        if warn:
            text += "\n\n注意：\n" + "\n".join(f"· {w}" for w in warn[:5])
        self._prog_label.setText("完成")
        fly_message(self, "完成", text)
        self._pending_accept = True

    def _on_fail(self, msg: str) -> None:
        fly_critical(self, "转换失败", msg)
        self._prog_label.hide()
        self._prog_bar.hide()

    def _on_thread_done(self) -> None:
        th = self._thread
        self._thread = None
        if th is not None:
            finalize_qthread(th)
        if not self.isEnabled():
            self.setEnabled(True)
        if self._pending_accept:
            self._pending_accept = False
            self.accept()

    def closeEvent(self, event: QCloseEvent) -> None:
        await_qthreads(self._thread)
        super().closeEvent(event)

    def reject(self) -> None:
        await_qthreads(self._thread)
        super().reject()


class PjskHubDialog(FluentCaptionDialog):
    """
    乐曲页「新增 → PJSK」入口：本地 pjsk_cache 列表；可打开曲目库下载，或将选中项转换并写入 ACUS。
    """

    def __init__(
        self,
        *,
        acus_root: Path,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("PJSK 谱面 → 中二")
        self.setModal(True)
        self.resize(840, 580)
        self._acus_root = acus_root.resolve()
        self._cache_root = pjsk_cache_root(self._acus_root)
        self._bundles: list[PjskLocalBundle] = []
        self._level_thread: _LevelIndexThread | None = None
        self._level_lookup_started = False

        card = CardWidget(self)
        c2s_unusable = BodyLabel(
            "谱面转换走「PJSK 官谱语义」转换器（装饰音符降级为装饰线、曲线烘焙、变速保留），"
            "再由 PenguinTools.CLI 打包 c2s / 封面 DDS / HCA 音频 / Music.xml。"
            "音频按实测前导静音自动对齐，不再固定裁 9 秒。\n"
            "若未配置 PenguinTools.CLI，「转换并写入 ACUS」会失败——可在「设置 → 外部工具」里安装。"
        )
        c2s_unusable.setWordWrap(True)
        c2s_unusable.setStyleSheet("color: #b45309; font-size: 13px;")

        top = BodyLabel(
            f"下列为已下载到本地的 PJSK 资源（{self._cache_root.as_posix()}）。"
            "选中一行后可「转换并写入 ACUS」；或打开「从网络下载新曲」补充缓存。"
        )
        top.setWordWrap(True)

        self._empty_hint = BodyLabel("", card)
        self._empty_hint.setWordWrap(True)
        self._empty_hint.setStyleSheet("color:#9ca3af;")
        self._empty_hint.hide()

        self._table = QTableWidget(0, 5, card)
        apply_fluent_sheet_table(self._table)
        self._table.setHorizontalHeaderLabels(["PJSK ID", "曲名", "作曲家", "谱面", "音频"])
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
        install = PrimaryPushButton("转换并写入 ACUS…", self)
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

    def showEvent(self, event) -> None:  # noqa: N802 (Qt)
        super().showEvent(event)
        if not self._level_lookup_started:
            self._level_lookup_started = True
            self._maybe_lookup_levels()

    def _maybe_lookup_levels(self) -> None:
        """老缓存没有 PJSK 等级 → 后台拉一次难度索引补进 manifest（离线则静默跳过）。"""
        if qthread_running_safe(self._level_thread):
            return
        if not any(not bundle_play_levels(b) for b in self._bundles):
            return
        th = _LevelIndexThread(parent=None)
        self._level_thread = th
        th.ok.connect(self._on_level_index)
        th.finished.connect(self._on_level_thread_done)
        th.start()

    def _on_level_index(self, index: object) -> None:
        if not isinstance(index, dict):
            return
        changed = False
        for b in self._bundles:
            rows = index.get(b.pjsk_music_id) or []
            levels = {
                r.music_difficulty.strip().lower(): int(r.play_level)
                for r in rows
                if getattr(r, "music_difficulty", "") and int(getattr(r, "play_level", 0)) > 0
            }
            if levels and backfill_bundle_play_levels(b, levels):
                changed = True
        if changed:
            self._reload_local()

    def _on_level_thread_done(self) -> None:
        th = self._level_thread
        self._level_thread = None
        if th is not None:
            finalize_qthread(th)

    def closeEvent(self, event: QCloseEvent) -> None:
        await_qthreads(self._level_thread)
        super().closeEvent(event)

    def reject(self) -> None:
        await_qthreads(self._level_thread)
        super().reject()

    def _reload_local(self) -> None:
        self._bundles = iter_local_pjsk_bundles(self._cache_root)
        self._table.setRowCount(len(self._bundles))
        for i, b in enumerate(self._bundles):
            present_slots = chuni_slots_with_c2s(b)
            has_ult = "ULTIMA" in present_slots
            audio = b.manifest.get("audio")
            has_audio = bool(isinstance(audio, dict) and str(audio.get("file") or "").strip())
            self._table.setItem(i, 0, QTableWidgetItem(str(b.pjsk_music_id)))
            self._table.setItem(i, 1, QTableWidgetItem(b.title))
            self._table.setItem(i, 2, QTableWidgetItem(b.composer))
            slot_txt = f"{len(present_slots)} 档" + (" · ULT" if has_ult else "")
            self._table.setItem(i, 3, QTableWidgetItem(slot_txt))
            self._table.setItem(i, 4, QTableWidgetItem("有" if has_audio else "无"))
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
        default_id = next_chuni_music_id(self._acus_root, start=7000)
        dlg = PjskConvertToAcusDialog(
            acus_root=self._acus_root,
            bundle=b,
            default_chuni_id=default_id,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload_local()
