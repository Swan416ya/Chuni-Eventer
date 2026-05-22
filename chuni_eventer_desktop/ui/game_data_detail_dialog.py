from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, SubtitleLabel, TabWidget, isDarkTheme

from ..dds_preview import dds_to_pixmap, ensure_dds_preview_png
from ..game_data_assets import (
    export_cue_dir_to_ogg,
    list_chara_variants,
    resolve_chara_variant_dds_files,
    resolve_music_cue_dir,
    resolve_music_jacket_dds,
    resolve_row_image_dds,
)
from .chara_add_dialog import chara_variant_display_name
from .dds_preview_widgets import CharaDdsPreviewWidget, WidthScaledPreviewLabel
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning


def _load_dds_pixmap(
    *,
    acus_root: Path,
    get_tool_path: Callable[[], Path | None],
    dds_path: Path,
) -> QPixmap | None:
    """按需解码 DDS（仅打开预览/导出时调用，索引里只存相对路径）。"""
    pm = dds_to_pixmap(
        acus_root=acus_root,
        compressonatorcli_path=get_tool_path(),
        dds_path=dds_path,
        restrict=False,
    )
    if pm is None or pm.isNull():
        return None
    return pm


class GameDdsImageDialog(FluentCaptionDialog):
    """展示游戏数据包内 DDS 贴图，布局与 ACUS 角色页预览一致。"""

    def __init__(
        self,
        *,
        title: str,
        subtitle: str,
        dds_paths: list[Path],
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(640, 520)
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path
        self._dds_paths = [p for p in dds_paths if p.is_file()]

        head = SubtitleLabel(subtitle, self)
        head.setWordWrap(True)

        preview_wrap = QWidget(self)
        preview_lay = QVBoxLayout(preview_wrap)
        preview_lay.setContentsMargins(0, 0, 0, 0)
        preview_lay.setSpacing(0)

        if not self._dds_paths:
            preview_lay.addWidget(BodyLabel("未找到可用的 DDS 文件。", preview_wrap))
            self._chara_preview: CharaDdsPreviewWidget | None = None
            self._single_preview: WidthScaledPreviewLabel | None = None
        elif len(self._dds_paths) >= 3:
            self._chara_preview = CharaDdsPreviewWidget(preview_wrap)
            self._single_preview = None
            pms: list[QPixmap | None] = []
            for dds in self._dds_paths[:3]:
                pms.append(_load_dds_pixmap(acus_root=acus_root, get_tool_path=get_tool_path, dds_path=dds))
            while len(pms) < 3:
                pms.append(None)
            self._chara_preview.set_pixmaps(pms[0], pms[1], pms[2])
            preview_lay.addWidget(self._chara_preview)
        else:
            self._chara_preview = None
            self._single_preview = WidthScaledPreviewLabel(preview_wrap)
            pm = _load_dds_pixmap(
                acus_root=acus_root,
                get_tool_path=get_tool_path,
                dds_path=self._dds_paths[0],
            )
            if pm is None:
                self._single_preview.setText(f"无法预览：\n{self._dds_paths[0].name}")
                self._single_preview.setWordWrap(True)
            else:
                self._single_preview.setSourcePixmap(pm)
            preview_lay.addWidget(self._single_preview)

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        if self._dds_paths:
            if len(self._dds_paths) >= 3:
                labels = ("导出 ddsFile0…", "导出 ddsFile1…", "导出 ddsFile2…")
                for i, dds in enumerate(self._dds_paths[:3]):
                    btn = PushButton(labels[i], self)
                    btn.clicked.connect(lambda _=False, p=dds: self._export_png(p))
                    export_row.addWidget(btn)
            else:
                btn = PushButton("导出 PNG…", self)
                btn.clicked.connect(lambda _=False, p=self._dds_paths[0]: self._export_png(p))
                export_row.addWidget(btn)
        export_row.addStretch(1)

        close = PrimaryPushButton("关闭", self)
        close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(head)
        lay.addWidget(preview_wrap, stretch=1)
        lay.addLayout(export_row)
        lay.addLayout(btns)

    def _export_png(self, dds: Path) -> None:
        tool = self._get_tool_path()
        png_path = ensure_dds_preview_png(
            acus_root=self._acus_root,
            compressonatorcli_path=tool,
            dds_path=dds,
        )
        if png_path is None or not png_path.is_file():
            fly_warning(self, "无法导出", "需要 quicktex 或 compressonatorcli 才能解码 BC3 DDS。")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "导出 PNG",
            str(Path.home() / f"{dds.stem}.png"),
            "PNG (*.png)",
        )
        if not dest:
            return
        try:
            shutil.copy2(png_path, dest)
            fly_message(self, "已导出", dest)
        except OSError as e:
            fly_critical(self, "导出失败", str(e))


class GameMusicDetailDialog(FluentCaptionDialog):
    """游戏乐曲详情：曲绘预览与 cue 音频导出。"""

    def __init__(
        self,
        *,
        row: dict,
        game_root: Path,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        mid = int(row.get("id") or 0)
        title = str(row.get("title") or f"Music{mid}")
        self.setWindowTitle(f"乐曲详情 · {title}")
        self.setModal(True)
        self.resize(640, 560)
        self._row = row
        self._game_root = game_root
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path

        head = SubtitleLabel(f"{mid:05d} · {title}", self)
        artist = str(row.get("artist") or "").strip()
        tag = str(row.get("release_tag_str") or "").strip()
        genres = "、".join(str(x) for x in (row.get("genres") or []))
        meta_lines = [x for x in (artist, tag, genres) if x]
        meta = BodyLabel(" · ".join(meta_lines) if meta_lines else "—", self)
        meta.setWordWrap(True)
        meta.setStyleSheet("color:#6B7280;")

        levels = row.get("levels") or []
        if levels:
            lv = BodyLabel("定数：" + " | ".join(str(x) for x in levels), self)
            lv.setWordWrap(True)
        else:
            lv = None

        self._jacket_preview = WidthScaledPreviewLabel(self)
        self._load_jacket()

        exp_j = PushButton("导出曲绘 PNG…", self)
        exp_j.clicked.connect(self._export_jacket)
        exp_a = PushButton("导出音频 OGG…", self)
        exp_a.clicked.connect(self._export_audio)

        row_btns = QHBoxLayout()
        row_btns.addWidget(exp_j)
        row_btns.addWidget(exp_a)
        row_btns.addStretch(1)

        close = PrimaryPushButton("关闭", self)
        close.clicked.connect(self.accept)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(head)
        lay.addWidget(meta)
        if lv is not None:
            lay.addWidget(lv)
        lay.addWidget(self._jacket_preview, stretch=1)
        lay.addLayout(row_btns)
        lay.addLayout(foot)

    def _load_jacket(self) -> None:
        dds = resolve_music_jacket_dds(game_root=self._game_root, row=self._row)
        if dds is None:
            self._jacket_preview.setText("未找到曲绘（jaketFile）。")
            return
        pm = _load_dds_pixmap(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path,
            dds_path=dds,
        )
        if pm is None:
            self._jacket_preview.setText(f"曲绘解码失败：\n{dds.name}")
            return
        self._jacket_preview.setSourcePixmap(pm)

    def _export_jacket(self) -> None:
        dds = resolve_music_jacket_dds(game_root=self._game_root, row=self._row)
        if dds is None:
            fly_warning(self, "无曲绘", "该乐曲未配置 jaketFile。")
            return
        dlg = GameDdsImageDialog(
            title="曲绘",
            subtitle=dds.name,
            dds_paths=[dds],
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path,
            parent=self,
        )
        dlg.exec()

    def _export_audio(self) -> None:
        cue_dir = resolve_music_cue_dir(game_root=self._game_root, row=self._row)
        if cue_dir is None:
            fly_warning(
                self,
                "无音频",
                "未找到对应的 cueFile 目录。\n"
                "若索引较旧，请在【设置 → 游戏数据】重新扫描后再试。",
            )
            return
        mid = int(self._row.get("id") or 0)
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "导出 OGG",
            str(Path.home() / f"music{mid:05d}.ogg"),
            "OGG (*.ogg)",
        )
        if not dest:
            return
        try:
            export_cue_dir_to_ogg(cue_dir, Path(dest))
            fly_message(self, "已导出", dest)
        except Exception as e:
            fly_critical(self, "导出失败", str(e))


class GameCharaImageDialog(FluentCaptionDialog):
    """角色立绘预览：支持多变体切换（与 ACUS 浏览器角色页一致）。"""

    def __init__(
        self,
        *,
        row: dict,
        game_root: Path,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        name = str(row.get("name") or row.get("id"))
        self.setWindowTitle(f"角色立绘 · {name}")
        self.setModal(True)
        self.resize(640, 560)
        self._row = row
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path
        self._variants = list_chara_variants(game_root=game_root, row=row)
        self._current_dds_paths: list[Path] = []

        head = SubtitleLabel(name, self)
        head.setWordWrap(True)

        self._variant_tabs = TabWidget(self)
        self._variant_tabs.setTabsClosable(False)
        self._variant_tabs.tabBar.setAddButtonVisible(False)
        self._variant_tabs.setVisible(len(self._variants) > 1)
        if isDarkTheme():
            self._variant_tabs.setTabSelectedBackgroundColor("#374151", "#4B5563")
        else:
            self._variant_tabs.setTabSelectedBackgroundColor("#E5E7EB", "#D1D5DB")

        master_xml = None
        for v in self._variants:
            mx = v.get("master_xml")
            if mx is not None:
                master_xml = mx
                break

        for v in self._variants:
            slot = int(v.get("slot") or 0)
            label = ""
            if master_xml is not None:
                label = chara_variant_display_name(master_xml, slot)
            if not label:
                label = f"变体 {slot}"
            page = QWidget(self._variant_tabs)
            self._variant_tabs.addTab(page, label, routeKey=f"chara_var_{slot}")
            idx = self._variant_tabs.count() - 1
            self._variant_tabs.setTabData(idx, slot)
        self._variant_tabs.currentChanged.connect(self._on_variant_changed)

        self._subtitle = BodyLabel("", self)
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet("color:#6B7280;")

        self._chara_preview = CharaDdsPreviewWidget(self)
        self._hint = BodyLabel("", self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color:#9CA3AF;font-size:13px;")
        self._hint.hide()

        self._export_row = QHBoxLayout()
        self._export_row.setSpacing(8)

        close = PrimaryPushButton("关闭", self)
        close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(12)
        lay.addWidget(head)
        if len(self._variants) > 1:
            lay.addWidget(self._variant_tabs)
        lay.addWidget(self._subtitle)
        lay.addWidget(self._chara_preview, stretch=1)
        lay.addWidget(self._hint)
        lay.addLayout(self._export_row)
        lay.addLayout(btns)

        if self._variants:
            self._variant_tabs.setCurrentIndex(0)
            self._load_variant(0)
        else:
            self._show_empty("未找到角色变体数据。")

    def _variant_at(self, tab_index: int) -> dict | None:
        if tab_index < 0 or tab_index >= len(self._variants):
            return None
        return self._variants[tab_index]

    def _on_variant_changed(self, tab_index: int) -> None:
        if tab_index < 0:
            return
        self._load_variant(tab_index)

    def _clear_export_buttons(self) -> None:
        while self._export_row.count():
            item = self._export_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild_export_buttons(self) -> None:
        self._clear_export_buttons()
        if len(self._current_dds_paths) >= 3:
            labels = ("导出 ddsFile0…", "导出 ddsFile1…", "导出 ddsFile2…")
            for i, dds in enumerate(self._current_dds_paths[:3]):
                btn = PushButton(labels[i], self)
                btn.clicked.connect(lambda _=False, p=dds: self._export_png(p))
                self._export_row.addWidget(btn)
        elif self._current_dds_paths:
            btn = PushButton("导出 PNG…", self)
            btn.clicked.connect(lambda _=False, p=self._current_dds_paths[0]: self._export_png(p))
            self._export_row.addWidget(btn)
        self._export_row.addStretch(1)

    def _show_empty(self, msg: str) -> None:
        self._chara_preview.clear()
        self._subtitle.setText("")
        self._hint.setText(msg)
        self._hint.show()
        self._current_dds_paths = []
        self._rebuild_export_buttons()

    def _load_variant(self, tab_index: int) -> None:
        variant = self._variant_at(tab_index)
        if variant is None:
            self._show_empty("变体索引无效。")
            return
        slot = int(variant.get("slot") or 0)
        cid = int(variant.get("chara_id") or 0)
        key = str(variant.get("image_key") or "").strip()
        meta = f"变体 {slot} · ID {cid}"
        if key:
            meta += f" · {key}"
        self._subtitle.setText(meta)

        dds_list = [p for p in resolve_chara_variant_dds_files(variant=variant) if p.is_file()]
        self._current_dds_paths = dds_list
        if not dds_list:
            self._chara_preview.clear()
            self._hint.setText("未找到该变体的 DDS 文件。")
            self._hint.show()
            self._rebuild_export_buttons()
            return

        self._hint.hide()
        pms: list[QPixmap | None] = []
        for dds in dds_list[:3]:
            pms.append(
                _load_dds_pixmap(
                    acus_root=self._acus_root,
                    get_tool_path=self._get_tool_path,
                    dds_path=dds,
                )
            )
        while len(pms) < 3:
            pms.append(None)
        if not any(x is not None for x in pms):
            self._chara_preview.clear()
            self._hint.setText("三张 DDS 均解码失败或路径为空。")
            self._hint.show()
        else:
            self._chara_preview.set_pixmaps(pms[0], pms[1], pms[2])
        self._rebuild_export_buttons()

    def _export_png(self, dds: Path) -> None:
        tool = self._get_tool_path()
        png_path = ensure_dds_preview_png(
            acus_root=self._acus_root,
            compressonatorcli_path=tool,
            dds_path=dds,
        )
        if png_path is None or not png_path.is_file():
            fly_warning(self, "无法导出", "需要 quicktex 或 compressonatorcli 才能解码 BC3 DDS。")
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "导出 PNG",
            str(Path.home() / f"{dds.stem}.png"),
            "PNG (*.png)",
        )
        if not dest:
            return
        try:
            shutil.copy2(png_path, dest)
            fly_message(self, "已导出", dest)
        except OSError as e:
            fly_critical(self, "导出失败", str(e))


def open_chara_image_dialog(
    *,
    row: dict,
    game_root: Path,
    acus_root: Path,
    get_tool_path: Callable[[], Path | None],
    parent,
) -> None:
    GameCharaImageDialog(
        row=row,
        game_root=game_root,
        acus_root=acus_root,
        get_tool_path=get_tool_path,
        parent=parent,
    ).exec()


def open_row_image_dialog(
    *,
    row: dict,
    game_root: Path,
    acus_root: Path,
    get_tool_path: Callable[[], Path | None],
    kind_label: str,
    parent,
) -> None:
    dds = resolve_row_image_dds(game_root=game_root, row=row)
    name = str(row.get("name") or row.get("id"))
    paths = [dds] if dds is not None else []
    dlg = GameDdsImageDialog(
        title=f"{kind_label} · {name}",
        subtitle=str(row.get("image_relpath") or ""),
        dds_paths=paths,
        acus_root=acus_root,
        get_tool_path=get_tool_path,
        parent=parent,
    )
    dlg.exec()
