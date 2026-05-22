from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QThread,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import Action, FluentIcon as FIF, MenuAnimationType, RoundMenu, ScrollArea

from .fluent_scroll import apply_fluent_transparent_panel, apply_fluent_transparent_scroll
from .qthread_lifecycle import await_qthreads


from ..acus_scan import MusicItem
from ..dds_preview import ensure_dds_preview_png
from ..dds_quicktex import quicktex_available

def _is_dark_ui() -> bool:
    pal = QApplication.palette()
    return pal.color(pal.ColorRole.Window).lightness() < 128


def _cover_pixmap(pm: QPixmap, target_w: int, target_h: int) -> QPixmap:
    if pm.isNull() or target_w < 1 or target_h < 1:
        return QPixmap()
    scaled = pm.scaled(
        target_w,
        target_h,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - target_w) // 2)
    y = max(0, (scaled.height() - target_h) // 2)
    return scaled.copy(x, y, target_w, target_h)


_DIFF_BG: dict[str, QColor] = {
    "BASIC": QColor("#22c55e"),
    "ADVANCED": QColor("#eab308"),
    "EXPERT": QColor("#ef4444"),
    "MASTER": QColor("#a855f7"),
    "ULTIMA": QColor("#18181b"),
}


def _parse_level_chips(levels: tuple[str, ...]) -> list[tuple[str, str, QColor]]:
    chips: list[tuple[str, str, QColor]] = []
    for lv in levels:
        if ":" not in lv:
            continue
        diff, rest = lv.split(":", 1)
        key = diff.strip().upper()
        chips.append((key, rest.strip(), _DIFF_BG.get(key, QColor("#64748b"))))
    return chips


def _pill_text_color(bg: QColor) -> QColor:
    return QColor("#f8fafc") if bg.lightness() < 70 else QColor("#0f172a")


class FlipMusicCard(QFrame):
    """正方形卡片，点击绕 Y 轴翻转；正面封面，背面曲目信息。"""

    doubleClickedMusic = pyqtSignal(object)
    deleteRequested = pyqtSignal(object)
    trophyRequested = pyqtSignal(object)
    jacketReplaceRequested = pyqtSignal(object)
    stageChangeRequested = pyqtSignal(object)
    releaseTagChangeRequested = pyqtSignal(object)

    def __init__(
        self,
        item: MusicItem,
        jacket: QPixmap | None,
        card_size: int,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._item = item
        self._jacket = jacket if jacket is not None and not jacket.isNull() else None
        self._card_size = max(80, card_size)
        self.setFixedSize(self._card_size, self._card_size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._angle = 0.0
        self._anim: QPropertyAnimation | None = None

    def get_angle(self) -> float:
        return self._angle

    def set_angle(self, v: float) -> None:
        self._angle = float(v)
        self.update()

    angle = pyqtProperty(float, fget=get_angle, fset=set_angle)

    def set_jacket(self, jacket: QPixmap | None) -> None:
        if jacket is None or jacket.isNull():
            return
        self._jacket = jacket
        self.update()

    def _target_angle(self) -> float:
        return 180.0 if self._angle < 90.0 else 0.0

    def _toggle_flip(self) -> None:
        if self._anim is not None and self._anim.state() == self._anim.State.Running:
            return
        end = self._target_angle()
        self._anim = QPropertyAnimation(self, b"angle", self)
        self._anim.setDuration(420)
        self._anim.setStartValue(self._angle)
        self._anim.setEndValue(end)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.start()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_flip()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClickedMusic.emit(self._item)
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:
        menu = RoundMenu(parent=self)
        menu.setItemHeight(36)
        vf = menu.view.font()
        vf.setPointSize(max(12, vf.pointSize()))
        menu.view.setFont(vf)

        act_jacket = Action(FIF.PHOTO, "更换封面…", self)
        act_stage = Action(FIF.ALBUM, "修改背景(Stage)…", self)
        act_release_tag = Action(FIF.TAG, "修改分类(releaseTag)…", self)
        act_trophy = Action(FIF.TAG, "生成课题称号…", self)
        act_del = Action(FIF.DELETE, "删除乐曲…", self)
        act_jacket.triggered.connect(
            lambda: QTimer.singleShot(80, lambda: self.jacketReplaceRequested.emit(self._item))
        )
        act_stage.triggered.connect(
            lambda: QTimer.singleShot(80, lambda: self.stageChangeRequested.emit(self._item))
        )
        act_release_tag.triggered.connect(
            lambda: QTimer.singleShot(80, lambda: self.releaseTagChangeRequested.emit(self._item))
        )
        act_trophy.triggered.connect(
            lambda: QTimer.singleShot(80, lambda: self.trophyRequested.emit(self._item))
        )
        # Delay emit to next event loop tick so menu closes first.
        # Otherwise opening a modal dialog immediately here may appear unclickable.
        act_del.triggered.connect(
            lambda: QTimer.singleShot(80, lambda: self.deleteRequested.emit(self._item))
        )
        menu.addAction(act_jacket)
        menu.addAction(act_stage)
        menu.addAction(act_release_tag)
        menu.addAction(act_trophy)
        menu.addAction(act_del)
        menu.exec(
            event.globalPos(),
            ani=True,
            aniType=MenuAnimationType.DROP_DOWN,
        )

    @staticmethod
    def _draw_cover_shadow(
        painter: QPainter, x: int, y: int, w: int, h: int, radius: float
    ) -> None:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(8, 0, -1):
            o = i * 0.55
            a = max(4, int(22 - i * 2.4))
            painter.setBrush(QColor(0, 0, 0, a))
            painter.drawRoundedRect(
                QRectF(x + 4 + o, y + 5 + o, w, h), radius, radius
            )
        painter.restore()

    def _paint_front(self, painter: QPainter, full: QRect, bg: QColor, fg: QColor) -> None:
        """正面与背面共用同一 `full` 区域，曲绘铺满卡片（圆角+阴影），避免翻面后视觉变大。"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRect(full)

        inset = 3
        r = full.adjusted(inset, inset, -inset, -inset)
        fw, fh = r.width(), r.height()
        if fw < 8 or fh < 8:
            return
        x0, y0 = r.x(), r.y()
        radius = max(10.0, min(fw, fh) * 0.06)

        if self._jacket is not None:
            self._draw_cover_shadow(painter, x0, y0, fw, fh, radius)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x0, y0, fw, fh), radius, radius)
            painter.setClipPath(path)
            cov = _cover_pixmap(self._jacket, fw, fh)
            painter.drawPixmap(x0, y0, cov)
            painter.setClipping(False)
            if self._item.has_perfect_challenge:
                bw = max(26, fw // 5)
                bh = max(24, fh // 5)
                br = QRectF(x0 + 3, y0 + 3, float(bw), float(bh))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#2563eb"))
                painter.drawRoundedRect(br, 5.0, 5.0)
                painter.setPen(QColor("#facc15"))
                bf = QFont()
                bf.setPixelSize(max(13, int(bh * 0.55)))
                painter.setFont(bf)
                painter.drawText(br.toRect(), Qt.AlignmentFlag.AlignCenter, "🔒")
        else:
            self._draw_cover_shadow(painter, x0, y0, fw, fh, radius)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x0, y0, fw, fh), radius, radius)
            ph = QColor("#cbd5e1") if bg.lightness() > 120 else QColor("#334155")
            painter.setBrush(ph)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)
            painter.setPen(fg)
            f = painter.font()
            f.setPointSize(max(9, min(fw, fh) // 18))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "无封面")
            if self._item.has_perfect_challenge:
                bw = max(26, fw // 5)
                bh = max(24, fh // 5)
                br = QRectF(x0 + 3, y0 + 3, float(bw), float(bh))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#2563eb"))
                painter.drawRoundedRect(br, 5.0, 5.0)
                painter.setPen(QColor("#facc15"))
                bf = QFont()
                bf.setPixelSize(max(13, int(bh * 0.55)))
                painter.setFont(bf)
                painter.drawText(br.toRect(), Qt.AlignmentFlag.AlignCenter, "🔒")

    def _paint_back(self, painter: QPainter, full: QRect, bg: QColor, fg: QColor) -> None:
        dark = _is_dark_ui()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRect(full)

        pad = max(8, full.width() // 40)
        inner = full.adjusted(pad, pad, -pad, -pad)
        h = inner.height()
        w = inner.width()
        if h < 20 or w < 20:
            return

        bottom_h = max(h // 5, 36)
        top_h = h - bottom_h
        top_rect = QRect(inner.x(), inner.y(), w, top_h)
        bot_rect = QRect(inner.x(), inner.bottom() - bottom_h + 1, w, bottom_h)

        it = self._item
        title = (it.name.str or "—").upper()
        artist = it.artist.str if it.artist else "—"
        genres = " / ".join(it.genres) if it.genres else "—"
        ver = it.release_tag.str if it.release_tag else "—"
        info_lines = [
            f"ID  {it.name.id}",
            f"流派  {genres}",
            f"版本  {ver}",
        ]

        title_h = max(int(top_h * 0.26), 28)
        artist_h = max(int(top_h * 0.16), 22)
        info_h = max(top_h - title_h - artist_h, 24)

        stack_h = title_h + artist_h + info_h
        y_base = top_rect.top() + max(0, (top_h - stack_h) // 2)
        r_title = QRect(top_rect.left(), y_base, w, title_h)
        r_artist = QRect(top_rect.left(), y_base + title_h, w, artist_h)
        r_info = QRect(top_rect.left(), y_base + title_h + artist_h, w, info_h)

        title_max_w = max(12, r_title.width() - 8)
        ft = QFont()
        ft.setBold(True)
        start_pt = max(11, self._card_size // 16)
        min_pt = 6
        title_draw = title
        for p in range(start_pt, min_pt - 1, -1):
            ft.setPointSize(p)
            fm_t = QFontMetrics(ft)
            tw = fm_t.size(Qt.TextFlag.TextSingleLine, title).width()
            if tw <= title_max_w:
                title_draw = title
                break
        else:
            ft.setPointSize(min_pt)
            fm_t = QFontMetrics(ft)
            title_draw = fm_t.elidedText(title, Qt.TextElideMode.ElideRight, title_max_w)
        painter.setFont(ft)
        painter.setPen(fg)
        painter.drawText(
            r_title,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            title_draw,
        )

        fa = QFont()
        fa.setBold(False)
        fa.setPointSize(max(9, self._card_size // 20))
        painter.setFont(fa)
        fm_a = QFontMetrics(fa)
        artist_max_w = max(12, r_artist.width() - 8)
        artist_draw = fm_a.elidedText(artist, Qt.TextElideMode.ElideRight, artist_max_w)
        painter.drawText(
            r_artist,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            artist_draw,
        )

        fi = QFont()
        fi.setPointSize(max(8, self._card_size // 24))
        painter.setFont(fi)
        n_info = len(info_lines)
        ih = max(14, info_h // max(1, n_info))
        iy = r_info.top()
        for line in info_lines:
            rr = QRect(r_info.left(), iy, w, min(ih, r_info.bottom() - iy + 1))
            if rr.height() < 10:
                break
            painter.drawText(
                rr,
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
                line,
            )
            iy += ih

        chips = _parse_level_chips(it.levels)
        margin_p = max(4, w // 50)
        usable_w = w - 2 * margin_p
        row_top = bot_rect.top() + margin_p // 2
        row_h = bot_rect.height() - margin_p
        gap = max(3, w // 80)

        painter.setPen(Qt.PenStyle.NoPen)
        if not chips:
            fp = QFont()
            fp.setPointSize(max(8, self._card_size // 26))
            painter.setFont(fp)
            painter.setPen(fg)
            painter.drawText(
                bot_rect,
                Qt.AlignmentFlag.AlignCenter,
                "无难度数据",
            )
        else:
            n = len(chips)
            pill_w = (usable_w - (n - 1) * gap) // n
            x = inner.left() + margin_p
            fp = QFont()
            fp.setBold(True)
            fp.setPointSize(max(7, self._card_size // 28))
            for name, lvl, bcol in chips:
                pr = QRect(x, row_top, pill_w, row_h)
                rr = 6.0
                painter.setBrush(bcol)
                painter.drawRoundedRect(QRectF(pr), rr, rr)
                painter.setPen(_pill_text_color(bcol))
                painter.setFont(fp)
                block = f"{name}\n{lvl}" if lvl else name
                painter.drawText(
                    pr.adjusted(2, 0, -2, 0),
                    Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                    block,
                )
                painter.setPen(Qt.PenStyle.NoPen)
                x += pill_w + gap

        border_c = QColor("#64748b") if dark else QColor("#94a3b8")
        painter.setPen(QPen(border_c, max(1, pad // 3)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(full).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, h / 2.0
        rad = math.radians(self._angle)
        cos_a = math.cos(rad)
        sx = max(0.04, abs(cos_a))
        painter.translate(cx, cy)
        painter.scale(sx, 1.0)
        painter.translate(-cx, -cy)

        dark = _is_dark_ui()
        bg = QColor("#0f172a") if dark else QColor("#f1f5f9")
        fg = QColor("#e2e8f0") if dark else QColor("#0f172a")

        full = self.rect()
        if self._angle < 90:
            self._paint_front(painter, full, bg, fg)
        else:
            self._paint_back(painter, full, bg, fg)


class _MusicViewportResizeFilter(QObject):
    """首帧 viewport 宽度常为 0；视口 Resize 后再重算列数。"""

    def __init__(self, owner: MusicCardsView) -> None:
        super().__init__(owner._scroll.viewport())
        self._owner = owner

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._owner._relayout_if_geometry_changed)
        return False


class _JacketLoadWorker(QObject):
    loaded = pyqtSignal(int, str)
    finished = pyqtSignal()

    def __init__(
        self,
        *,
        jobs: list[tuple[int, Path]],
        acus_root: Path,
        tool_path: Path | None,
        generation: int,
        generation_ref: list[int],
    ) -> None:
        super().__init__()
        self._jobs = jobs
        self._acus_root = acus_root
        self._tool_path = tool_path
        self._generation = generation
        self._generation_ref = generation_ref

    def run(self) -> None:
        loaded = 0
        for music_id, dds_path in self._jobs:
            if self._generation_ref[0] != self._generation:
                break
            png_path = ensure_dds_preview_png(
                acus_root=self._acus_root,
                compressonatorcli_path=self._tool_path,
                dds_path=dds_path,
            )
            if png_path is not None and self._generation_ref[0] == self._generation:
                self.loaded.emit(music_id, str(png_path))
                loaded += 1
        self.finished.emit()


class MusicCardsView(QWidget):
    """正方形卡片网格，随宽度换列，纵向滚动。"""

    doubleClickedMusic = pyqtSignal(object)
    musicDeleteRequested = pyqtSignal(object)
    musicTrophyRequested = pyqtSignal(object)
    musicJacketReplaceRequested = pyqtSignal(object)
    musicStageChangeRequested = pyqtSignal(object)
    musicReleaseTagChangeRequested = pyqtSignal(object)

    def __init__(
        self,
        *,
        acus_root: Path,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        apply_fluent_transparent_panel(self)
        self._acus_root = acus_root
        self._cards: list[FlipMusicCard] = []
        self._last_items: list[MusicItem] = []
        self._get_tool_path = lambda: None
        self._jacket_cache: dict[int, QPixmap] = {}
        self._last_grid_cols = -1
        self._last_card_size = -1
        self._last_viewport_w = -1
        self._card_by_id: dict[int, FlipMusicCard] = {}
        self._jacket_load_generation_ref: list[int] = [0]
        self._jacket_thread: QThread | None = None
        self._jacket_worker: _JacketLoadWorker | None = None

        self._scroll = ScrollArea(self)
        # False：内容区按网格真实宽高布局，否则视口会把子控件压成单列竖排
        self._scroll.setWidgetResizable(False)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        apply_fluent_transparent_panel(self._content)
        self._grid = QGridLayout(self._content)
        self._grid.setContentsMargins(16, 16, 16, 16)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self._scroll.setWidget(self._content)
        apply_fluent_transparent_scroll(self._scroll)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._scroll)

        self._vp_resize_filter = _MusicViewportResizeFilter(self)
        self._scroll.viewport().installEventFilter(self._vp_resize_filter)
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_for_jackets)

    def _on_scroll_for_jackets(self, _value: int) -> None:
        if self._last_items and self._jacket_thread is None:
            self._schedule_jacket_loads()

    def _stop_jacket_loader(self) -> None:
        self._jacket_load_generation_ref[0] += 1
        thread = self._jacket_thread
        self._jacket_thread = None
        self._jacket_worker = None
        if thread is not None and thread.isRunning():
            thread.quit()
        await_qthreads(thread, timeout_ms=60_000)

    def _prioritized_jacket_jobs(self) -> list[tuple[int, Path]]:
        tool = self._get_tool_path()
        if tool is None and not quicktex_available():
            return []
        jobs: list[tuple[int, Path]] = []
        visible: set[int] = set()
        cols = self._last_grid_cols if self._last_grid_cols > 0 else 4
        card_size = self._last_card_size if self._last_card_size > 0 else 120
        if self._cards and card_size > 0:
            scroll_y = self._scroll.verticalScrollBar().value()
            vp_h = max(1, self._scroll.viewport().height())
            gap = self._grid.verticalSpacing()
            margin = self._grid.contentsMargins().top()
            row_h = card_size + gap
            first_row = max(0, (scroll_y - margin) // max(1, row_h))
            last_row = (scroll_y + vp_h + margin) // max(1, row_h) + 1
            for row in range(first_row, last_row + 1):
                for col in range(cols):
                    idx = row * cols + col
                    if idx < len(self._last_items):
                        visible.add(idx)

        def _append_at(idx: int) -> None:
            it = self._last_items[idx]
            if it.name.id in self._jacket_cache:
                return
            rel = it.jacket_path.strip()
            if not rel:
                return
            dds_path = it.xml_path.parent / rel
            jobs.append((it.name.id, dds_path))

        for idx in sorted(visible):
            _append_at(idx)
        for idx in range(len(self._last_items)):
            if idx not in visible:
                _append_at(idx)
        return jobs

    def _on_jacket_loaded(self, music_id: int, png_path: str) -> None:
        pm = QPixmap(png_path)
        if pm.isNull():
            return
        pm = pm.scaled(900, 900, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self._jacket_cache[music_id] = pm
        card = self._card_by_id.get(music_id)
        if card is not None:
            card.set_jacket(pm)

    def _on_jacket_loader_finished(self) -> None:
        self._jacket_thread = None
        self._jacket_worker = None

    def _schedule_jacket_loads(self) -> None:
        jobs = self._prioritized_jacket_jobs()
        if not jobs:
            return
        self._stop_jacket_loader()
        generation = self._jacket_load_generation_ref[0]
        tool = self._get_tool_path()
        thread = QThread(self)
        worker = _JacketLoadWorker(
            jobs=jobs,
            acus_root=self._acus_root,
            tool_path=tool,
            generation=generation,
            generation_ref=self._jacket_load_generation_ref,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._on_jacket_loaded)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_jacket_loader_finished)
        thread.finished.connect(thread.deleteLater)
        self._jacket_thread = thread
        self._jacket_worker = worker
        thread.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._last_items:
            QTimer.singleShot(0, self._relayout_if_geometry_changed)
            QTimer.singleShot(50, self._relayout_if_geometry_changed)

    def _effective_viewport_width(self) -> int:
        """布局未完成时 viewport 可能为 0，用本控件与滚动条宽度兜底。"""
        vp = self._scroll.viewport().width()
        sw = self._scroll.width()
        ow = self.width()
        return max(1, vp, sw - 2, ow - 2)

    def _relayout_if_geometry_changed(self) -> None:
        if not self._last_items:
            return
        vp_eff = self._effective_viewport_width()
        cols, card_size = self._cols_and_size()
        if (
            cols == self._last_grid_cols
            and card_size == self._last_card_size
            and vp_eff == self._last_viewport_w
        ):
            return
        self._rebuild_grid()

    def clear_cards(self) -> None:
        self._stop_jacket_loader()
        self._card_by_id.clear()
        for c in self._cards:
            c.deleteLater()
        self._cards.clear()
        while self._grid.count():
            it = self._grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def set_items(self, items: list[MusicItem], get_tool_path) -> None:
        self._stop_jacket_loader()
        self._last_items = list(items)
        self._get_tool_path = get_tool_path
        self._jacket_cache.clear()
        self._last_grid_cols = -1
        self._last_card_size = -1
        self._last_viewport_w = -1
        self._rebuild_grid()
        QTimer.singleShot(0, self._relayout_if_geometry_changed)
        QTimer.singleShot(50, self._relayout_if_geometry_changed)

    def _cols_and_size(self) -> tuple[int, int]:
        """优先每行 4 张；宽度不足时依次减列，保证横向排满后再换行。"""
        margin = 16
        gap = self._grid.horizontalSpacing()
        vp_w = self._effective_viewport_width()
        raw = vp_w - 2 * margin
        min_tile = 120
        avail = max(min_tile, raw)
        cols = 4
        while cols > 1:
            tile = (avail - (cols - 1) * gap) // cols
            if tile >= min_tile:
                break
            cols -= 1
        card_size = (avail - (cols - 1) * gap) // cols
        card_size = max(min_tile, card_size)
        return cols, card_size

    def _rebuild_grid(self) -> None:
        self.clear_cards()
        items = self._last_items
        if not items:
            self._content.setMinimumSize(0, 0)
            self._content.resize(self._scroll.viewport().width(), 0)
            return
        cols, card_size = self._cols_and_size()

        for idx, it in enumerate(items):
            jacket: QPixmap | None = self._jacket_cache.get(it.name.id)
            card = FlipMusicCard(it, jacket, card_size)
            self._card_by_id[it.name.id] = card
            card.doubleClickedMusic.connect(self.doubleClickedMusic.emit)
            card.deleteRequested.connect(self.musicDeleteRequested.emit)
            card.trophyRequested.connect(self.musicTrophyRequested.emit)
            card.jacketReplaceRequested.connect(self.musicJacketReplaceRequested.emit)
            card.stageChangeRequested.connect(self.musicStageChangeRequested.emit)
            card.releaseTagChangeRequested.connect(self.musicReleaseTagChangeRequested.emit)
            self._cards.append(card)
            row, col = divmod(idx, cols)
            self._grid.addWidget(
                card, row, col, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
            )
        self._last_grid_cols = cols
        self._last_card_size = card_size
        self._last_viewport_w = self._effective_viewport_width()

        m = self._grid.contentsMargins()
        hs = self._grid.horizontalSpacing()
        vs = self._grid.verticalSpacing()
        n = len(items)
        rows = (n + cols - 1) // cols
        tw = m.left() + m.right() + cols * card_size + max(0, cols - 1) * hs
        th = m.top() + m.bottom() + rows * card_size + max(0, rows - 1) * vs
        self._content.setFixedSize(tw, th)
        self._schedule_jacket_loads()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._last_items:
            QTimer.singleShot(0, self._relayout_if_geometry_changed)
