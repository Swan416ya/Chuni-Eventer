from __future__ import annotations

from pathlib import Path
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..acus_scan import NamePlateItem, TrophyItem, scan_nameplates, scan_trophies
from ..chusan_save import (
    PENGUIN_ITEM_IDS,
    PENGUIN_ITEM_KIND,
    PENGUIN_ITEM_NAMES,
    load_save,
    save_save,
    set_equipped_nameplate,
    set_equipped_trophies,
    set_penguin_stocks,
    sum_item_stock,
)
from ..dds_preview import dds_to_pixmap
from ..dds_quicktex import quicktex_available


class SavePatchDialog(QDialog):
    """
    上传 ALL.Net 导出存档 JSON，将 userData 中的名牌/称号改为 ACUS 中已有条目（仅改装备字段）。
    """

    def __init__(self, *, acus_root: Path, get_tool_path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("存档装备（名牌 / 称号 / 企鹅）")
        self.setModal(True)
        self.resize(720, 640)
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path
        self._save_path: Path | None = None
        self._data: dict | None = None

        self._nameplates = scan_nameplates(acus_root)
        self._trophies = scan_trophies(acus_root)

        self.path_label = QLabel("未选择文件")
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet("color:#6B7280;")

        pick_btn = QPushButton("选择存档 JSON…")
        pick_btn.clicked.connect(self._pick_save)

        self.tabs = QTabWidget()

        # --- 名牌 ---
        np_page = QWidget()
        np_lay = QVBoxLayout(np_page)
        self.np_current_id_label = QLabel("当前存档名牌 ID：-")
        self.np_current_id_label.setStyleSheet("color:#6B7280;")
        self.np_filter = QLineEdit()
        self.np_filter.setPlaceholderText("筛选名牌：ID 或名称")
        self.np_filter.textChanged.connect(self._filter_nameplates)
        self.np_combo = QComboBox()
        self.np_combo.setEditable(True)
        self.np_combo.setMaxVisibleItems(30)
        for np in self._nameplates:
            self.np_combo.addItem(f"{np.name.id} | {np.name.str}", np)
        np_lay.addWidget(self.np_current_id_label)
        np_lay.addWidget(self.np_filter)
        np_lay.addWidget(self.np_combo)
        self.np_preview = QLabel("预览")
        self.np_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.np_preview.setMinimumHeight(200)
        self.np_preview.setStyleSheet("border:1px solid #444;")
        np_lay.addWidget(self.np_preview)
        self.np_combo.currentIndexChanged.connect(self._on_np_changed)
        self.tabs.addTab(np_page, "名牌")

        # --- 称号 三槽 ---
        tr_page = QWidget()
        tr_lay = QVBoxLayout(tr_page)
        self.tr_current_ids_label = QLabel("当前存档称号 ID：主 - / 副1 - / 副2 -")
        self.tr_current_ids_label.setStyleSheet("color:#6B7280;")
        form = QFormLayout()
        self.tr_main = QComboBox()
        self.tr_sub1 = QComboBox()
        self.tr_sub2 = QComboBox()
        for cb in (self.tr_main, self.tr_sub1, self.tr_sub2):
            cb.setEditable(True)
            cb.setMaxVisibleItems(30)
        self._fill_trophy_combo(self.tr_main, with_keep=False)
        self._fill_trophy_combo(self.tr_sub1, with_keep=True)
        self._fill_trophy_combo(self.tr_sub2, with_keep=True)
        tr_lay.addWidget(self.tr_current_ids_label)
        form.addRow("主称号", self.tr_main)
        form.addRow("副称号 1", self.tr_sub1)
        form.addRow("副称号 2", self.tr_sub2)
        tr_lay.addLayout(form)
        self.tr_preview = QLabel("预览（主称号）")
        self.tr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tr_preview.setMinimumHeight(200)
        self.tr_preview.setStyleSheet("border:1px solid #444;")
        tr_lay.addWidget(self.tr_preview)
        self.tr_main.currentIndexChanged.connect(self._on_tr_main_changed)
        self.tabs.addTab(tr_page, "称号")

        # --- 企鹅（userItemList：itemKind=5，isValid=true，stock=数量）---
        pg_page = QWidget()
        pg_lay = QVBoxLayout(pg_page)
        pg_hint = QLabel(
            "对应导出存档 userItemList：itemKind=5，itemId 8000 金企鹅 / 8010 小企鹅 / 8020 企鹅之魂 / 8030 彩色企鹅，"
            "isValid 固定为 true，stock 为数量（含 0）。"
            " 修改后须点击底部「另存为」写入新 JSON，不会改动原文件。"
        )
        pg_hint.setWordWrap(True)
        pg_hint.setStyleSheet("color:#6B7280;")
        pg_lay.addWidget(pg_hint)
        pg_form = QFormLayout()
        self._penguin_spins: list[QSpinBox] = []
        for pid in PENGUIN_ITEM_IDS:
            sp = QSpinBox()
            sp.setRange(0, 9_999_999)
            sp.setSingleStep(1)
            sp.setKeyboardTracking(False)
            self._penguin_spins.append(sp)
            name = PENGUIN_ITEM_NAMES.get(pid, str(pid))
            pg_form.addRow(f"{name}（itemId {pid}）", sp)
        pg_lay.addLayout(pg_form)
        pg_lay.addStretch(1)
        self.tabs.addTab(pg_page, "企鹅")

        apply_btn = QPushButton("写入并另存为…")
        apply_btn.clicked.connect(self._apply)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)

        hint = QLabel(
            "另存时会同时写入：当前选中的名牌 + 主/副称号（副槽可选「保持存档原值」）"
            " + 「企鹅」页各 ID 数量（写入 userItemList，其它物品不动）。"
            " 原 JSON 路径不会被覆盖，请选择新文件名保存。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#B45309;")

        root = QVBoxLayout(self)
        root.addWidget(pick_btn)
        root.addWidget(self.path_label)
        root.addWidget(hint)
        root.addWidget(self.tabs, stretch=1)
        root.addLayout(btns)

        self._filter_nameplates()
        self._on_np_changed()
        self._on_tr_main_changed()

    def _fill_trophy_combo(self, cb: QComboBox, *, with_keep: bool) -> None:
        if with_keep:
            cb.addItem("（保持存档原值）", None)
        for t in self._trophies:
            cb.addItem(f"{t.name.id} | {t.name.str}", t)

    def _pick_save(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择导出存档", "", "JSON (*.json);;All (*)")
        if not path:
            return
        p = Path(path)
        try:
            self._data = load_save(p)
            if "userData" not in self._data:
                raise ValueError("不是有效的导出存档：缺少 userData")
        except Exception as e:
            QMessageBox.critical(self, "读取失败", str(e))
            self._data = None
            self._save_path = None
            self.path_label.setText("读取失败")
            return
        self._save_path = p
        self.path_label.setText(str(p))
        self._sync_from_save()

    def _sync_from_save(self) -> None:
        if not self._data:
            return
        ud = self._data.get("userData") or {}
        self._update_current_id_labels()

        nid = ud.get("nameplateId")
        if isinstance(nid, int):
            for i in range(self.np_combo.count()):
                np: NamePlateItem = self.np_combo.itemData(i)
                if np and np.name.id == nid:
                    self.np_combo.setCurrentIndex(i)
                    break
            else:
                self.np_combo.setEditText(str(nid))

        def set_trophy_combo(cb: QComboBox, tid: object, *, allow_keep: bool) -> None:
            if not isinstance(tid, int):
                return
            for i in range(cb.count()):
                it = cb.itemData(i)
                if it is None and allow_keep:
                    continue
                if isinstance(it, TrophyItem) and it.name.id == tid:
                    cb.setCurrentIndex(i)
                    return
            cb.setEditText(str(tid))

        set_trophy_combo(self.tr_main, ud.get("trophyId"), allow_keep=False)
        set_trophy_combo(self.tr_sub1, ud.get("trophyIdSub1"), allow_keep=True)
        set_trophy_combo(self.tr_sub2, ud.get("trophyIdSub2"), allow_keep=True)

        self._sync_penguins_from_save()

        self._on_np_changed()
        self._on_tr_main_changed()

    def _update_current_id_labels(self) -> None:
        ud = (self._data or {}).get("userData") or {}
        nid = ud.get("nameplateId")
        t0 = ud.get("trophyId")
        t1 = ud.get("trophyIdSub1")
        t2 = ud.get("trophyIdSub2")
        self.np_current_id_label.setText(f"当前存档名牌 ID：{nid if isinstance(nid, int) else '-'}")
        self.tr_current_ids_label.setText(
            f"当前存档称号 ID：主 {t0 if isinstance(t0, int) else '-'} / "
            f"副1 {t1 if isinstance(t1, int) else '-'} / "
            f"副2 {t2 if isinstance(t2, int) else '-'}"
        )

    @staticmethod
    def _extract_numeric_id(text: str) -> int | None:
        s = text.strip()
        if not s:
            return None
        if re.fullmatch(r"-?\d+", s):
            return int(s)
        m = re.match(r"\s*(-?\d+)\s*\|", s)
        if m:
            return int(m.group(1))
        return None

    def _sync_penguins_from_save(self) -> None:
        if not self._data:
            for sp in self._penguin_spins:
                sp.setValue(0)
            return

        for sp, pid in zip(self._penguin_spins, PENGUIN_ITEM_IDS, strict=True):
            n = sum_item_stock(self._data, item_kind=PENGUIN_ITEM_KIND, item_id=pid)
            sp.blockSignals(True)
            sp.setValue(max(0, min(n, sp.maximum())))
            sp.blockSignals(False)

    def _filter_nameplates(self) -> None:
        q = self.np_filter.text().strip().lower()
        self.np_combo.blockSignals(True)
        self.np_combo.clear()
        for np in self._nameplates:
            blob = f"{np.name.id} {np.name.str}".lower()
            if q and q not in blob:
                continue
            self.np_combo.addItem(f"{np.name.id} | {np.name.str}", np)
        self.np_combo.blockSignals(False)
        if self.np_combo.count() == 0:
            self.np_combo.addItem("(无匹配)", None)
        self._on_np_changed()

    def _tool(self) -> Path | None:
        return self._get_tool_path()

    def _set_preview(self, label: QLabel, dds_path: Path | None) -> None:
        tool = self._tool()
        label.clear()
        if dds_path is None or not dds_path.is_file():
            label.setText("无预览图")
            return
        if tool is None and not quicktex_available():
            label.setText("配置 quicktex 或 compressonator 后可预览 DDS")
            return
        pm = dds_to_pixmap(acus_root=self._acus_root, compressonatorcli_path=tool, dds_path=dds_path)
        if pm is None:
            label.setText("预览失败")
            return
        label.setPixmap(pm.scaled(280, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        label.setText("")

    def _on_np_changed(self) -> None:
        np: NamePlateItem | None = self.np_combo.currentData()
        if np is None or not np.image_path:
            self._set_preview(self.np_preview, None)
            return
        dds = np.xml_path.parent / np.image_path
        self._set_preview(self.np_preview, dds)

    def _on_tr_main_changed(self) -> None:
        t: TrophyItem | None = self.tr_main.currentData()
        if t is None or not t.image_path:
            self._set_preview(self.tr_preview, None)
            return
        dds = t.xml_path.parent / t.image_path
        self._set_preview(self.tr_preview, dds)

    def _apply(self) -> None:
        if not self._data:
            QMessageBox.warning(self, "提示", "请先选择存档 JSON")
            return
        np: NamePlateItem | None = self.np_combo.currentData()
        np_id = np.name.id if isinstance(np, NamePlateItem) else self._extract_numeric_id(self.np_combo.currentText())
        if np_id is None:
            QMessageBox.warning(self, "提示", "请选择名牌，或在下拉框里输入名牌 ID")
            return
        main: TrophyItem | None = self.tr_main.currentData()
        main_id = main.name.id if isinstance(main, TrophyItem) else self._extract_numeric_id(self.tr_main.currentText())
        if main_id is None:
            QMessageBox.warning(self, "提示", "请选择主称号，或在下拉框里输入称号 ID")
            return
        set_equipped_nameplate(self._data, np_id)
        ud = self._data.setdefault("userData", {})
        cur_sub1 = ud.get("trophyIdSub1")
        cur_sub2 = ud.get("trophyIdSub2")
        sub1_it = self.tr_sub1.currentData()
        sub2_it = self.tr_sub2.currentData()
        sub1_typed = self._extract_numeric_id(self.tr_sub1.currentText())
        sub2_typed = self._extract_numeric_id(self.tr_sub2.currentText())
        s1 = (
            sub1_it.name.id
            if isinstance(sub1_it, TrophyItem)
            else (sub1_typed if isinstance(sub1_typed, int) else (int(cur_sub1) if isinstance(cur_sub1, int) else -1))
        )
        s2 = (
            sub2_it.name.id
            if isinstance(sub2_it, TrophyItem)
            else (sub2_typed if isinstance(sub2_typed, int) else (int(cur_sub2) if isinstance(cur_sub2, int) else -1))
        )
        set_equipped_trophies(self._data, main_id, s1, s2)

        stocks = {pid: sp.value() for sp, pid in zip(self._penguin_spins, PENGUIN_ITEM_IDS, strict=True)}
        set_penguin_stocks(self._data, stocks)

        out, _ = QFileDialog.getSaveFileName(
            self,
            "另存为",
            str(self._save_path.with_name(self._save_path.stem + "_patched.json")) if self._save_path else "patched.json",
            "JSON (*.json)",
        )
        if not out:
            return
        try:
            save_save(out, self._data, indent=None)
        except Exception as e:
            QMessageBox.critical(self, "写入失败", str(e))
            return
        QMessageBox.information(self, "完成", f"已写入：\n{out}")
        self.accept()
