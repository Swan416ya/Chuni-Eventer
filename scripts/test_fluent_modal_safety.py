#!/usr/bin/env python3
"""Offscreen regression checks for Fluent modal-window lockups."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6 import sip  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402
from qfluentwidgets import Theme, setTheme  # noqa: E402

from chuni_eventer_desktop.ui.music_add_actions_dialog import (  # noqa: E402
    MusicSheetChannelsDialog,
)
from chuni_eventer_desktop.ui.psb_action_dialog import PsbActionDialog  # noqa: E402
from chuni_eventer_desktop.ui.tool_install_progress import (  # noqa: E402
    ToolInstallProgressDialog,
    dismiss_tool_install_progress,
)


def _pump(app: QApplication, rounds: int = 12) -> None:
    for _ in range(rounds):
        app.processEvents()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    setTheme(Theme.DARK)
    parent = QWidget()
    parent.show()
    failures: list[str] = []

    modal = MusicSheetChannelsDialog(parent=parent)
    modal.show()
    _pump(app)
    if modal.titleBar.minBtn.isVisible():
        failures.append("modal Fluent dialog exposes a minimize button")
    modal.reject()
    _pump(app)

    progress = ToolInstallProgressDialog(parent)
    progress.show_progress()
    _pump(app)
    if progress.titleBar.closeBtn.isVisible():
        failures.append("running progress dialog exposes a close button")
    progress.reject()  # Simulate Escape while worker is active.
    _pump(app)
    if sip.isdeleted(progress) or not progress.isVisible():
        failures.append("running progress dialog was dismissed by Escape")
    progress.close()  # Simulate title-bar close / Alt+F4 while worker is active.
    _pump(app)
    if sip.isdeleted(progress):
        failures.append("running progress dialog was destroyed by an early close")
    else:
        try:
            progress.update_progress("late worker signal", 80)
        except RuntimeError as exc:
            failures.append(f"late progress signal touched deleted UI: {exc}")
    if not sip.isdeleted(progress):
        dismiss_tool_install_progress(progress)
        _pump(app)

    mate_dialog = PsbActionDialog(
        acus_root=ROOT / "ACUS",
        freemote_dir=ROOT / "tools" / "FreeMote",
        mate_id=999999,
        parent=parent,
    )
    mate_dialog.show()
    _pump(app)

    class _BusyThread:
        @staticmethod
        def isRunning() -> bool:  # noqa: N802
            return True

    mate_dialog._build_thread = _BusyThread()
    mate_dialog.reject()  # Escape while a GIF/PSB conversion is active.
    mate_dialog.close()  # Title-bar close / Alt+F4 during conversion.
    _pump(app)
    if sip.isdeleted(mate_dialog) or not mate_dialog.isVisible():
        failures.append("Mate conversion dialog closed while its worker was active")
    mate_dialog._build_thread = None
    mate_dialog.reject()
    _pump(app)

    if QApplication.activeModalWidget() is not None:
        failures.append("an active modal widget remained after controlled dismissal")
    if not parent.isEnabled():
        failures.append("parent window remained disabled")
    parent.close()

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("fluent modal safety: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
