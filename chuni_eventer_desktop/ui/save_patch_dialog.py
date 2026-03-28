from __future__ import annotations

from pathlib import Path
import re

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    EditableComboBox,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    SpinBox,
    TabWidget,
    isDarkTheme,
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
from .fluent_dialogs import fly_critical, fly_message, fly_warning


def _preview_frame_style() -> str:
    b = "#3A3A3A" if isDarkTheme() else "#D1D5DB"
    bg = "#2D2D2D" if isDarkTheme() else "#F9FAFB"
    return f"QLabel {{ border: 1px solid {b}; border-radius: 8px; background: {bg}; }}"


class SavePatchDialog(QDialog):
    """
    上传 ALL.Net 导出存档 JSON，将 userData 中的名牌/称号改为 ACUS 中已有条目（仅改装备字段）。
    """

    def __init__(self, *, acus_root: Path, get_tool_path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("存档装备（名牌 / 称号 / 企鹅）")
        self.setModal(True)
        self.resize(760, 680)
        self._acus_root = acus_root
        self._get_tool_path = get_tool_path
        self._save_path: Path | None = None
        self._data: dict | None = None

        self._nameplates = scan_nameplates(acus_root)
        self._trophies = scan_trophies(acus_root)

        self.path_label = CaptionLabel("未选择文件", self)
        self.path_label.setWordWrap(True)

        pick_btn = PrimaryPushButton("选择存档 JSON…", self)
        pick_btn.clicked.connect(self._pick_save)

        self.tabs = TabWidget(self)

        # --- 名牌 ---
        np_page = QWidget()
        np_lay = QVBoxLayout(np_page)
        np_lay.setContentsMargins(8, 8, 8, 8)
        np_lay.setSpacing(10)
        self.np_current_id_label = CaptionLabel("当前存档名牌 ID：-", self)
        self.np_filter = SearchLineEdit(self)
        self.np_filter.setPlaceholderText("筛选名牌：ID 或名称")
        self.np_filter.textChanged.connect(self._filter_nameplates)
        self.np_combo = EditableComboBox(self)
        self.np_combo.setMaxVisibleItems(30)
        for np in self._nameplates:
            self.np_combo.addItem(f"{np.name.id} | {np.name.str}", None, np)
        np_lay.addWidget(self.np_current_id_label)
        np_lay.addWidget(self.np_filter)
        np_lay.addWidget(self.np_combo)
        self.np_preview = QLabel("预览", self)
        self.np_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.np_preview.setMinimumHeight(200)
        self.np_preview.setStyleSheet(_preview_frame_style())
        np_lay.addWidget(self.np_preview)
        self.np_combo.currentIndexChanged.connect(self._on_np_changed)
        self.np_combo.currentTextChanged.connect(lambda _t: self._on_np_changed())
        self.tabs.addTab(np_page, "名牌")

        # --- 称号 ---
        tr_page = QWidget()
        tr_lay = QVBoxLayout(tr_page)
        tr_lay.setContentsMargins(8, 8, 8, 8)
        tr_lay.setSpacing(10)
        self.tr_current_ids_label = CaptionLabel("当前存档称号 ID：主 - / 副1 - / 副2 -", self)
        self.tr_limit_hint = BodyLabel("提示：因 rin 服服务器问题，当前仅支持修改主称号。", self)
        self.tr_limit_hint.setWordWrap(True)
        self.tr_limit_hint.setStyleSheet("color: #CA8A04;")
        form = QFormLayout()
        self.tr_main = EditableComboBox(self)
        self.tr_main.setMaxVisibleItems(30)
        self._fill_trophy_combo(self.tr_main, with_keep=False)
        tr_lay.addWidget(self.tr_current_ids_label)
        tr_lay.addWidget(self.tr_limit_hint)
        form.addRow("主称号", self.tr_main)
        tr_lay.addLayout(form)
        self.tr_preview = QLabel("预览（主称号）", self)
        self.tr_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tr_preview.setMinimumHeight(200)
        self.tr_preview.setStyleSheet(_preview_frame_style())
        tr_lay.addWidget(self.tr_preview)
        self.tr_main.currentIndexChanged.connect(self._on_tr_main_changed)
        self.tr_main.currentTextChanged.connect(lambda _t: self._on_tr_main_changed())
        self.tabs.addTab(tr_page, "称号")

        # --- 企鹅 ---
        pg_page = QWidget()
        pg_lay = QVBoxLayout(pg_page)
        pg_lay.setContentsMargins(8, 8, 8, 8)
        pg_lay.setSpacing(10)
        pg_hint = BodyLabel(
            "对应导出存档 userItemList：itemKind=5，itemId 8000 金企鹅 / 8010 小企鹅 / 8020 企鹅之魂 / 8030 彩色企鹅，"
            "isValid 固定为 true，stock 为数量（含 0）。"
            " 修改后须点击底部「另存为」写入新 JSON，不会改动原文件。",
            self,
        )
        pg_hint.setWordWrap(True)
        pg_lay.addWidget(pg_hint)
        pg_form = QFormLayout()
        self._penguin_spins: list[SpinBox] = []
        for pid in PENGUIN_ITEM_IDS:
            sp = SpinBox(self)
            sp.setRange(0, 9_999_999)
            sp.setSingleStep(1)
            sp.setKeyboardTracking(False)
            self._penguin_spins.append(sp)
            name = PENGUIN_ITEM_NAMES.get(pid, str(pid))
            pg_form.addRow(f"{name}（itemId {pid}）", sp)
        pg_lay.addLayout(pg_form)
        pg_lay.addStretch(1)
        self.tabs.addTab(pg_page, "企鹅")

        apply_btn = PrimaryPushButton("写入并另存为…", self)
        apply_btn.clicked.connect(self._apply)
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        btns.addWidget(cancel_btn)
        btns.addWidget(apply_btn)

        hint = BodyLabel(
            "另存时会同时写入：当前选中的名牌 + 主称号（因 rin 服服务器问题，副称号保持存档原值）"
            " + 「企鹅」页各 ID 数量（写入 userItemList，其它物品不动）。"
            " 原 JSON 路径不会被覆盖，请选择新文件名保存。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #CA8A04;")

        tabs_card = CardWidget(self)
        tc_lay = QVBoxLayout(tabs_card)
        tc_lay.setContentsMargins(12, 12, 12, 12)
        tc_lay.addWidget(self.tabs)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)
        root.addWidget(pick_btn)
        root.addWidget(self.path_label)
        root.addWidget(hint)
        root.addWidget(tabs_card, stretch=1)
        root.addLayout(btns)

        self._filter_nameplates()
        self._on_np_changed()
        self._on_tr_main_changed()

    def _fill_trophy_combo(self, cb: EditableComboBox, *, with_keep: bool) -> None:
        if with_keep:
            cb.addItem("（保持存档原值）", None, None)
        for t in self._trophies:
            cb.addItem(f"{t.name.id} | {t.name.str}", None, t)

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
            fly_critical(self, "读取失败", str(e))
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
                np: NamePlateItem | None = self.np_combo.itemData(i)
                if np and np.name.id == nid:
                    self.np_combo.setCurrentIndex(i)
                    break
            else:
                self.np_combo.setText(str(nid))

        def set_trophy_combo(cb: EditableComboBox, tid: object, *, allow_keep: bool) -> None:
            if not isinstance(tid, int):
                return
            for i in range(cb.count()):
                it = cb.itemData(i)
                if it is None and allow_keep:
                    continue
                if isinstance(it, TrophyItem) and it.name.id == tid:
                    cb.setCurrentIndex(i)
                    return
            cb.setText(str(tid))

        set_trophy_combo(self.tr_main, ud.get("trophyId"), allow_keep=False)

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
            self.np_combo.addItem(f"{np.name.id} | {np.name.str}", None, np)
        self.np_combo.blockSignals(False)
        if self.np_combo.count() == 0:
            self.np_combo.addItem("(无匹配)", None, None)
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
            fly_warning(self, "提示", "请先选择存档 JSON")
            return
        np: NamePlateItem | None = self.np_combo.currentData()
        np_id = np.name.id if isinstance(np, NamePlateItem) else self._extract_numeric_id(self.np_combo.currentText())
        if np_id is None:
            fly_warning(self, "提示", "请选择名牌，或在下拉框里输入名牌 ID")
            return
        main: TrophyItem | None = self.tr_main.currentData()
        main_id = main.name.id if isinstance(main, TrophyItem) else self._extract_numeric_id(self.tr_main.currentText())
        if main_id is None:
            fly_warning(self, "提示", "请选择主称号，或在下拉框里输入称号 ID")
            return
        set_equipped_nameplate(self._data, np_id)
        ud = self._data.setdefault("userData", {})
        cur_sub1 = ud.get("trophyIdSub1")
        cur_sub2 = ud.get("trophyIdSub2")
        s1 = int(cur_sub1) if isinstance(cur_sub1, int) else -1
        s2 = int(cur_sub2) if isinstance(cur_sub2, int) else -1
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
            fly_critical(self, "写入失败", str(e))
            return
        fly_message(self, "完成", f"已写入：\n{out}")
        self.accept()
