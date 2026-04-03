from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QProgressDialog, QWidget

from ..game_data_index import GameDataIndex, rebuild_and_save_game_index


def run_rebuild_game_index_with_progress(
    parent: QWidget | None,
    *,
    game_root: Path,
    compressonatorcli_path: Path | None = None,
) -> tuple[GameDataIndex | None, str]:
    """
    执行游戏索引重建并显示进度条。
    progress 回调参数：(说明文字, 当前步, 总步)；总步为 0 时表示不确定进度（忙碌条）。
    """
    prog = QProgressDialog(parent)
    prog.setWindowTitle("扫描游戏数据")
    prog.setLabelText("准备中…")
    prog.setRange(0, 0)
    prog.setCancelButton(None)
    prog.setMinimumDuration(0)
    prog.setWindowModality(Qt.WindowModality.WindowModal)
    prog.show()

    def on_progress(msg: str, cur: int, total: int) -> None:
        prog.setLabelText(msg)
        if total > 0:
            prog.setRange(0, total)
            prog.setValue(min(max(cur, 0), total))
        else:
            prog.setRange(0, 0)
        QApplication.processEvents()

    try:
        return rebuild_and_save_game_index(
            game_root,
            compressonatorcli_path,
            progress=on_progress,
        )
    finally:
        prog.close()
        prog.deleteLater()
