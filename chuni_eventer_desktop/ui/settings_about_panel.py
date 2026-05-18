from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, Qt, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QMouseEvent, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, SubtitleLabel, isDarkTheme

from ..github_release import (
    LatestReleaseInfo,
    compare_version_tuple,
    fetch_latest_release,
    parse_version_tuple,
)
from ..version import APP_VERSION

_AUTHOR_SITE = "https://swan416.top/"
_BILIBILI = "https://space.bilibili.com/354312859"
_GITHUB_REPO = "https://github.com/Swan416ya/Chuni-Eventer"

_APP_LOGO = "ChuniEventer.png"
_LINK_LOGO_H = 30
_APP_LOGO_SIDE = 132


def _logo_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "static" / "logo"


def _overlay_fill_color() -> QColor:
    """叠色：浅色主题叠黑，深色主题叠白（仍保留 PNG 原 Alpha）。"""
    return QColor(0, 0, 0) if not isDarkTheme() else QColor(255, 255, 255)


def _black_overlay_pixmap(source: QPixmap) -> QPixmap:
    """
    透明 PNG：先绘原图，再用 SourceIn 在不透明区域叠纯色（保留原 Alpha 与抗锯齿）。
    """
    if source.isNull():
        return QPixmap()
    out = source.copy()
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(out.rect(), _overlay_fill_color())
    painter.end()
    return out


def _pixmap_from_file(path: Path, *, max_height: int) -> QPixmap:
    if not path.is_file():
        return QPixmap()
    if path.suffix.lower() == ".svg":
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return QPixmap()
        w = max(int(renderer.defaultSize().width()), 1)
        h = max(int(renderer.defaultSize().height()), 1)
        scale = max_height / h
        tw, th = max(1, int(w * scale)), max_height
        raw = QPixmap(tw, th)
        raw.fill(Qt.GlobalColor.transparent)
        painter = QPainter(raw)
        renderer.render(painter)
        painter.end()
        return _black_overlay_pixmap(raw)
    pm = QPixmap(str(path))
    if pm.isNull():
        return QPixmap()
    scaled = pm.scaledToHeight(max_height, Qt.TransformationMode.SmoothTransformation)
    return _black_overlay_pixmap(scaled)


class _ReleaseCheckWorker(QObject):
    finished = pyqtSignal(object)

    def run(self) -> None:
        try:
            info = fetch_latest_release()
            self.finished.emit(("ok", info))
        except Exception as e:
            self.finished.emit(("err", str(e)))


class _AboutLinkTile(QWidget):
    """可点击：上图标、下标题。"""

    def __init__(
        self,
        *,
        icon: QPixmap,
        caption: str,
        url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        logo = QLabel(self)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(icon)
        logo.setFixedHeight(_LINK_LOGO_H + 4)

        self._caption = BodyLabel(caption, self)
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._caption.setStyleSheet("font-size:12px;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(4)
        lay.addWidget(logo)
        lay.addWidget(self._caption)

    def mouseReleaseEvent(self, a0: QMouseEvent | None) -> None:
        if a0 is not None and a0.button() == Qt.MouseButton.LeftButton:
            QDesktopServices.openUrl(QUrl(self._url))
        super().mouseReleaseEvent(a0)


class SettingsAboutPanel(QWidget):
    """关于：居中品牌信息与外链。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._check_thread: QThread | None = None
        self._check_worker: _ReleaseCheckWorker | None = None
        self._current_tuple = parse_version_tuple(APP_VERSION)
        self._last_release_url = f"{_GITHUB_REPO}/releases/latest"
        self._version_state = "checking"

        logo_dir = _logo_dir()
        app_logo = QLabel(self)
        app_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        app_pm = QPixmap(str(logo_dir / _APP_LOGO))
        if not app_pm.isNull():
            app_logo.setPixmap(
                app_pm.scaled(
                    _APP_LOGO_SIDE,
                    _APP_LOGO_SIDE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

        title = SubtitleLabel("ChuniEventer", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._version_lbl = BodyLabel(f"v{APP_VERSION}（正在检查…）", self)
        self._version_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version_lbl.setStyleSheet("font-size:14px;color:#6B7280;")

        links_row = QHBoxLayout()
        links_row.setSpacing(20)
        links_row.addStretch(1)
        links_row.addWidget(
            _AboutLinkTile(
                icon=_pixmap_from_file(logo_dir / "SwanSite.png", max_height=_LINK_LOGO_H),
                caption="个人站",
                url=_AUTHOR_SITE,
                parent=self,
            )
        )
        links_row.addWidget(
            _AboutLinkTile(
                icon=_pixmap_from_file(logo_dir / "Bilibili_2020.png", max_height=_LINK_LOGO_H),
                caption="总被癞蛤蟆吃的天鹅",
                url=_BILIBILI,
                parent=self,
            )
        )
        links_row.addWidget(
            _AboutLinkTile(
                icon=_pixmap_from_file(logo_dir / "github.png", max_height=_LINK_LOGO_H),
                caption="Swan416ya",
                url=_GITHUB_REPO,
                parent=self,
            )
        )
        links_row.addStretch(1)

        brand = QVBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(app_logo, alignment=Qt.AlignmentFlag.AlignHCenter)
        brand.addWidget(title, alignment=Qt.AlignmentFlag.AlignHCenter)
        brand.addWidget(self._version_lbl, alignment=Qt.AlignmentFlag.AlignHCenter)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 20)
        root.addStretch(1)
        root.addLayout(brand)
        root.addStretch(1)
        root.addLayout(links_row)

        self._version_lbl.installEventFilter(self)
        self.check_for_updates()

    def eventFilter(self, watched: QObject, event: object) -> bool:
        if (
            watched is self._version_lbl
            and isinstance(event, QMouseEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self._version_state == "outdated"
        ):
            QDesktopServices.openUrl(QUrl(self._last_release_url))
            return True
        return super().eventFilter(watched, event)

    def check_for_updates(self) -> None:
        if self._check_thread is not None:
            return
        self._set_version_label("checking")
        thread = QThread(self)
        worker = _ReleaseCheckWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_release_check_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_check_thread_stopped)
        self._check_thread = thread
        self._check_worker = worker
        thread.start()

    def _on_check_thread_stopped(self) -> None:
        self._check_thread = None
        self._check_worker = None

    def _on_release_check_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 2:
            self._set_version_label("error")
            return
        kind, data = payload
        if kind == "err":
            self._set_version_label("error")
            return
        if not isinstance(data, LatestReleaseInfo):
            self._set_version_label("error")
            return
        latest = data
        cmp = compare_version_tuple(self._current_tuple, latest.version_tuple)
        if cmp < 0:
            self._last_release_url = latest.release_url
            self._set_version_label("outdated")
        elif cmp == 0:
            self._set_version_label("latest")
        else:
            self._set_version_label("dev")

    def _set_version_label(self, state: str) -> None:
        self._version_state = state
        if state == "checking":
            self._version_lbl.setText(f"v{APP_VERSION}（正在检查…）")
            self._version_lbl.setStyleSheet("font-size:14px;color:#6B7280;")
            self._version_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        elif state == "latest":
            self._version_lbl.setText(f"v{APP_VERSION}（已是最新）")
            self._version_lbl.setStyleSheet("font-size:14px;")
            self._version_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        elif state == "outdated":
            self._version_lbl.setText(f"v{APP_VERSION}（点击更新）")
            self._version_lbl.setStyleSheet("font-size:14px;color:#CA8A04;")
            self._version_lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        elif state == "dev":
            self._version_lbl.setText(f"v{APP_VERSION}（开发构建）")
            self._version_lbl.setStyleSheet("font-size:14px;color:#6B7280;")
            self._version_lbl.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            self._version_lbl.setText(f"v{APP_VERSION}（无法检查更新）")
            self._version_lbl.setStyleSheet("font-size:14px;color:#9CA3AF;")
            self._version_lbl.setCursor(Qt.CursorShape.ArrowCursor)
