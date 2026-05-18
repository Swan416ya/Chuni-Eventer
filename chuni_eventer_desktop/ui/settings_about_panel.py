from __future__ import annotations

from PyQt6.QtCore import QObject, QThread, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, HyperlinkButton, PushButton, SubtitleLabel

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


class _ReleaseCheckWorker(QObject):
    finished = pyqtSignal(object)

    def run(self) -> None:
        try:
            info = fetch_latest_release()
            self.finished.emit(("ok", info))
        except Exception as e:
            self.finished.emit(("err", str(e)))


class SettingsAboutPanel(QWidget):
    """关于：作者链接与 GitHub Release 版本检查。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._check_thread: QThread | None = None
        self._check_worker: _ReleaseCheckWorker | None = None
        self._current_tuple = parse_version_tuple(APP_VERSION)
        self._last_release_url = f"{_GITHUB_REPO}/releases/latest"

        title = SubtitleLabel("Chuni Eventer", self)
        self._version_lbl = BodyLabel(f"当前版本：v{APP_VERSION}", self)
        self._update_lbl = BodyLabel("正在检查更新…", self)
        self._update_lbl.setWordWrap(True)

        recheck = PushButton("重新检查更新", self)
        recheck.clicked.connect(self.check_for_updates)

        ver_card = CardWidget(self)
        ver_lay = QVBoxLayout(ver_card)
        ver_lay.setContentsMargins(16, 16, 16, 16)
        ver_lay.setSpacing(10)
        ver_lay.addWidget(CaptionLabel("版本", self))
        ver_lay.addWidget(self._version_lbl)
        ver_lay.addWidget(self._update_lbl)
        self._open_release_btn = PushButton("打开最新 Release 页面…", self)
        self._open_release_btn.setVisible(False)
        self._open_release_btn.clicked.connect(self._open_release_page)
        ver_lay.addWidget(self._open_release_btn)
        ver_lay.addWidget(recheck)

        links_card = CardWidget(self)
        links_lay = QVBoxLayout(links_card)
        links_lay.setContentsMargins(16, 16, 16, 16)
        links_lay.setSpacing(12)
        links_lay.addWidget(CaptionLabel("链接", self))
        links_lay.addWidget(self._link_button("个人站", _AUTHOR_SITE))
        links_lay.addWidget(self._link_button("Bilibili", _BILIBILI))
        links_lay.addWidget(self._link_button("GitHub 仓库", _GITHUB_REPO))

        hint = BodyLabel(
            "Chuni Eventer 是面向 CHUNITHM 自制 ACUS 内容维护的本地桌面工具。"
            " 更新检查通过 GitHub Releases API 获取最新发行版标签。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#6B7280;font-size:13px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(ver_card)
        layout.addWidget(links_card)
        layout.addStretch(1)

        self.check_for_updates()

    @staticmethod
    def _link_button(text: str, url: str) -> HyperlinkButton:
        return HyperlinkButton(url, text)

    def check_for_updates(self) -> None:
        if self._check_thread is not None:
            return
        self._update_lbl.setText("正在检查更新…")
        self._update_lbl.setStyleSheet("color:#6B7280;font-size:13px;")
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
            self._set_check_failed("检查失败")
            return
        kind, data = payload
        if kind == "err":
            self._set_check_failed(str(data))
            return
        if not isinstance(data, LatestReleaseInfo):
            self._set_check_failed("检查失败")
            return
        latest = data
        cmp = compare_version_tuple(self._current_tuple, latest.version_tuple)
        if cmp < 0:
            self._last_release_url = latest.release_url
            self._open_release_btn.setVisible(True)
        else:
            self._open_release_btn.setVisible(False)
        if cmp < 0:
            self._update_lbl.setText(
                f"有新版本可用：{latest.tag_name}\n"
                f"当前 v{APP_VERSION}，请前往 Releases 下载更新。"
            )
            self._update_lbl.setStyleSheet("color:#CA8A04;font-size:13px;")
        elif cmp == 0:
            self._update_lbl.setText(f"已是最新版本（与 GitHub 最新发行 {latest.tag_name} 一致）。")
            self._update_lbl.setStyleSheet("color:#16A34A;font-size:13px;")
        else:
            self._update_lbl.setText(
                f"当前 v{APP_VERSION} 高于 GitHub 标注的最新发行 {latest.tag_name}（可能为开发构建）。"
            )
            self._update_lbl.setStyleSheet("color:#6B7280;font-size:13px;")

    def _open_release_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self._last_release_url))

    def _set_check_failed(self, err: str) -> None:
        self._open_release_btn.setVisible(False)
        self._update_lbl.setText(f"无法检查更新：{err}")
        self._update_lbl.setStyleSheet("color:#DC2626;font-size:13px;")
