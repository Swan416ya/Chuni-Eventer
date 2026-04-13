"""
隐藏调试：SUS → c2s 文本转换（不面向普通用户）。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QVBoxLayout,
)

from qfluentwidgets import BodyLabel, CardWidget, LineEdit, PrimaryPushButton, PushButton

from .. import sus_to_c2s as s2c
from ..pjsk_sheet_client import pjsk_song_cache_dir
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning


class SusC2sDebugDialog(FluentCaptionDialog):
    """SUS→c2s 测试窗口（隐藏入口：PJSK 曲目表 ID 列右键打开；非模态）。"""

    def __init__(
        self,
        *,
        acus_root: Path,
        selected_music_id_fn: Callable[[], int | None],
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("SUS → c2s 调试（隐藏入口）")
        self.resize(920, 660)
        self.setWindowModality(Qt.WindowModality.NonModal)

        self._acus_root = Path(acus_root).resolve()
        self._selected_music_id_fn = selected_music_id_fn

        hint = BodyLabel(
            "从文件或下方文本框读取 SUS，点击「转换」生成 c2s（UTF-8）。"
            "「从缓存加载」使用当前表格选中曲目的 pjsk_cache/…/sus/ 下 expert.sus（若存在）。",
            self,
        )
        hint.setWordWrap(True)

        path_row = QHBoxLayout()
        self._path_edit = LineEdit(self)
        self._path_edit.setPlaceholderText("可选：.sus 文件路径…")
        browse = PushButton("浏览…", self)
        browse.clicked.connect(self._browse_sus)
        path_row.addWidget(self._path_edit, stretch=1)
        path_row.addWidget(browse)

        self._sus_in = QPlainTextEdit(self)
        self._sus_in.setPlaceholderText("在此粘贴 SUS 正文，或使用「从缓存加载」/ 浏览文件…")
        self._sus_out = QPlainTextEdit(self)
        self._sus_out.setReadOnly(True)
        self._sus_out.setPlaceholderText("c2s 输出…")

        load_cache = PushButton("从缓存加载 expert.sus", self)
        load_cache.clicked.connect(self._load_from_cache)
        convert = PrimaryPushButton("转换", self)
        convert.clicked.connect(self._run_convert)
        clear = PushButton("清空", self)
        clear.clicked.connect(self._clear_all)
        close = PushButton("关闭窗口", self)
        close.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.addWidget(load_cache)
        btn_row.addWidget(convert)
        btn_row.addWidget(clear)
        btn_row.addStretch(1)
        btn_row.addWidget(close)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 16, 16, 16)
        cly.setSpacing(10)
        cly.addWidget(hint)
        cly.addLayout(path_row)
        cly.addWidget(BodyLabel("SUS 输入", card))
        cly.addWidget(self._sus_in, stretch=1)
        cly.addLayout(btn_row)
        cly.addWidget(BodyLabel("c2s 输出", card))
        cly.addWidget(self._sus_out, stretch=1)

        root = QVBoxLayout(self)
        root.setContentsMargins(*fluent_caption_content_margins())
        root.setSpacing(12)
        root.addWidget(card)

    def _browse_sus(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self,
            "选择 SUS 文件",
            str(self._acus_root.parent),
            "SUS (*.sus);;文本 (*.txt);;所有 (*.*)",
        )
        if p:
            self._path_edit.setText(p)
            try:
                self._sus_in.setPlainText(Path(p).read_text(encoding="utf-8"))
            except OSError:
                pass

    def _load_from_cache(self) -> None:
        mid = self._selected_music_id_fn()
        if mid is None:
            fly_warning(self, "未选中曲目", "请先在表格中选择一首乐曲。")
            return
        sus = pjsk_song_cache_dir(self._acus_root, mid) / "sus" / "expert.sus"
        if not sus.is_file():
            fly_warning(self, "无缓存文件", f"不存在：\n{sus}")
            return
        self._path_edit.setText(str(sus))
        self._sus_in.setPlainText(sus.read_text(encoding="utf-8"))

    def _run_convert(self) -> None:
        text = self._sus_in.toPlainText()
        if not text.strip():
            fly_warning(self, "无输入", "请先填入 SUS 文本或从缓存/文件加载。")
            return
        try:
            out = s2c.convert_sus_to_c2s(text)
        except Exception as e:
            fly_critical(self, "转换异常", str(e))
            return
        self._sus_out.setPlainText(out)
        fly_message(self, "完成", f"输出约 {len(out)} 字符。")

    def _clear_all(self) -> None:
        self._path_edit.clear()
        self._sus_in.clear()
        self._sus_out.clear()

    def load_sus_path(self, path: Path) -> None:
        path = Path(path)
        if path.is_file():
            self._path_edit.setText(str(path))
            self._sus_in.setPlainText(path.read_text(encoding="utf-8"))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        p = self.parentWidget()
        if p is not None:
            top = p.window()
            g = top.frameGeometry()
            sz = self.size()
            x = g.x() + max(0, (g.width() - sz.width()) // 2)
            y = g.y() + max(0, (g.height() - sz.height()) // 2)
            self.move(x, y)
