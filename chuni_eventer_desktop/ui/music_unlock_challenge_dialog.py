from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..acus_scan import MusicItem
from ..unlock_challenge import (
    create_unlock_challenge_bundle,
    next_custom_unlock_reward_id,
    next_perfect_challenge_course_base_id,
)
from .event_add_dialog import next_custom_event_id


class MusicUnlockChallengeDialog(QDialog):
    """为当前 ACUS 乐曲生成 Reward(2xxxxxxxxx) + 5×Course(31xxxx) + UnlockChallenge + Event(type=16)。"""

    def __init__(self, *, acus_root: Path, item: MusicItem, parent=None) -> None:
        super().__init__(parent=parent)
        self._acus_root = acus_root
        self._item = item
        self.setWindowTitle("创建解锁挑战（完美挑战）")
        self.setModal(True)
        self.resize(520, 320)

        try:
            preview_base = next_perfect_challenge_course_base_id(acus_root)
            preview_reward = next_custom_unlock_reward_id(acus_root)
        except Exception as e:
            preview_base = -1
            preview_reward = -1
            preview_err = str(e)
        else:
            preview_err = ""

        hint = QLabel(
            "将按 A001（unlockChallenge00010002 + course00300005～009 + reward040002705）写入：\n"
            "• 新建乐曲类 Reward，ID 使用 200000000～299999999；\n"
            "• 新建 5 个课题 Course，ID 使用连续 310000～319999；\n"
            "• 课题的 reward/reward2nd、UnlockChallenge 的 rewardList 均指向该 Reward（奖励为当前曲）；\n"
            "• releaseTag / netOpen 与 Music.xml 一致；谱面难度按启用 fumen 在 5 关间分配。\n"
            "完成后乐曲卡片左上角显示蓝底黄锁角标。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b;font-size:12px;")

        prev_txt = (
            f"本次预计：Reward id ≈ {preview_reward}，课题 id ≈ {preview_base}～{preview_base + 4}（若仍空闲）。"
            if preview_base >= 0
            else f"无法预分配 ID：{preview_err}"
        )
        prev = QLabel(prev_txt)
        prev.setStyleSheet("font-size:12px;color:#0f766e;")
        prev.setWordWrap(True)

        self._challenge_title = QLineEdit(item.name.str)
        self._event_title = QLineEdit(f"【Unlock】{item.name.str}")
        self._event_id = QSpinBox()
        self._event_id.setRange(0, 99_999_999)
        self._event_id.setSpecialValueText("自动")
        self._event_id.setValue(0)

        form = QFormLayout()
        form.addRow("挑战标题", self._challenge_title)
        form.addRow("事件标题", self._event_title)
        form.addRow("事件 ID（0=自动）", self._event_id)

        ok = QPushButton("生成")
        cancel = QPushButton("取消")
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(cancel)
        row.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addWidget(prev)
        lay.addLayout(form)
        lay.addLayout(row)

    def _on_ok(self) -> None:
        try:
            eid = None if self._event_id.value() == 0 else int(self._event_id.value())
            _a, _b, ch_id, ev_id, rw_id = create_unlock_challenge_bundle(
                acus_root=self._acus_root,
                item=self._item,
                challenge_title=self._challenge_title.text(),
                event_title=self._event_title.text(),
                event_id=eid,
                next_event_id_fn=next_custom_event_id,
            )
        except Exception as e:
            QMessageBox.critical(self, "失败", str(e))
            return
        QMessageBox.information(
            self,
            "完成",
            f"挑战 ID：{ch_id}\n事件 ID：{ev_id}\n奖励 ID：{rw_id}\n已更新 CourseSort / UnlockChallengeSort / EventSort。",
        )
        self.accept()
