from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QToolButton, QWidget


def _is_cp932_char(ch: str) -> bool:
    try:
        ch.encode("cp932")
        return True
    except UnicodeEncodeError:
        return False


def _preview_text(src: str) -> tuple[str, str]:
    shown = "".join(ch for ch in src if _is_cp932_char(ch))
    removed = "".join(ch for ch in src if not _is_cp932_char(ch))
    if not removed:
        msg = f"预览（可显示）:\n{shown}"
    else:
        uniq_removed = "".join(dict.fromkeys(removed))
        msg = (
            f"预览（可显示）:\n{shown}\n\n"
            f"不可显示字符已被过滤:\n{uniq_removed}"
        )
    return shown, msg


def wrap_name_input_with_preview(edit: QLineEdit, *, parent: QWidget | None = None) -> QWidget:
    box = QWidget(parent or edit.parentWidget())
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    row.addWidget(edit, stretch=1)
    btn = QToolButton(box)
    btn.setText("🔍")
    btn.setToolTip("预览日文字库显示效果")
    btn.setFixedWidth(28)
    row.addWidget(btn)

    def _refresh_tip() -> None:
        _shown, tip = _preview_text((edit.text() or "").strip())
        btn.setToolTip(tip)

    edit.textChanged.connect(lambda _=None: _refresh_tip())
    _refresh_tip()
    return box

