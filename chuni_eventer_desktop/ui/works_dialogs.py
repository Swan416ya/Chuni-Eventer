from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..works_library import add_work_entry, load_works_library, remove_work_entry, WORKS_CUSTOM_ID_START
from .name_glyph_preview import wrap_name_input_with_preview
from ..xml_writer import (
    CHARA_DEFAULT_NET_OPEN_ID,
    CHARA_DEFAULT_NET_OPEN_STR,
    CHARA_DEFAULT_RELEASE_TAG_ID,
    CHARA_DEFAULT_RELEASE_TAG_STR,
    ensure_chara_works_xml,
)


WORKS_WARNING_TEXT = (
    "若不填写有效的作品（works），游戏内选角界面可能无法按作品分类检索到该角色，"
    "往往只能出现在「最近使用」等分类；长时间不用可能从列表中消失。"
)


def works_warning_label() -> QLabel:
    lb = QLabel(WORKS_WARNING_TEXT)
    lb.setWordWrap(True)
    lb.setStyleSheet("color:#B45309; font-size: 12px;")
    return lb


def fill_works_combo(cb: QComboBox, *, include_invalid: bool = True) -> None:
    cb.clear()
    if include_invalid:
        cb.addItem("（不填）Invalid — 检索可能受限", (-1, "Invalid"))
    entries, _ = load_works_library()
    for e in entries:
        cb.addItem(f"{e.id} · {e.str}", (e.id, e.str))


def ensure_combo_select_works(cb: QComboBox, wid: int, wstr: str) -> None:
    """下拉刷新后选中与 XML 一致的项；若库中无记录则插入「当前 XML」占位项。"""
    fill_works_combo(cb)
    for j in range(cb.count()):
        d = cb.itemData(j)
        if d is not None and len(d) == 2 and int(d[0]) == wid:
            cb.setCurrentIndex(j)
            return
    label = f"{wid} · {wstr}（当前 XML，未在作品库）"
    cb.insertItem(1, label, (wid, wstr))
    cb.setCurrentIndex(1)


def combo_works_id_str(cb: QComboBox) -> tuple[int, str]:
    data = cb.currentData()
    if data is not None and isinstance(data, tuple) and len(data) == 2:
        i, s = data
        try:
            return int(i), str(s)
        except Exception:
            pass
    return -1, "Invalid"


class WorkCreateDialog(QDialog):
    """新建一条作品并写入缓存（可指定 id）。"""

    def __init__(self, *, suggest_id: int, acus_root: Path | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("新建作品（works）")
        self.setModal(True)
        self._acus_root = acus_root
        self._work_id: int | None = None
        self._work_str: str | None = None

        self._id_spin = QSpinBox()
        self._id_spin.setRange(-1, 99_999_999)
        self._id_spin.setValue(max(suggest_id, WORKS_CUSTOM_ID_START))
        self._str_edit = QLineEdit()
        self._str_edit.setPlaceholderText("作品显示名（写入 Chara.xml works/str）")

        form = QFormLayout()
        form.addRow("作品 ID", self._id_spin)
        form.addRow("显示名", wrap_name_input_with_preview(self._str_edit, parent=self))

        ok = QPushButton("保存到作品库")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(works_warning_label())
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        s = self._str_edit.text().strip()
        if not s:
            QMessageBox.critical(self, "错误", "请填写作品显示名。")
            return
        wid = int(self._id_spin.value())
        try:
            add_work_entry(work_id=wid, work_str=s)
        except ValueError as e:
            QMessageBox.critical(self, "错误", str(e))
            return
        # CharaWorks 的 releaseTagName / netOpenName 必须与具体 Chara 一致，无角色上下文时不写磁盘，
        # 避免把 PJSK 等角色误写成 -1/Invalid；请用「编辑作品」或脚本 scripts/sync_acus_chara_works.py 同步。
        self._work_id = wid
        self._work_str = s
        self.accept()

    @property
    def created(self) -> tuple[int, str] | None:
        if self._work_id is None or self._work_str is None:
            return None
        return self._work_id, self._work_str


class WorksLibraryManagerDialog(QDialog):
    """列表维护缓存中的作品库。"""

    def __init__(self, *, acus_root: Path | None = None, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("作品库（缓存）")
        self.setModal(True)
        self._acus_root = acus_root
        self.resize(420, 320)

        self._list = QListWidget()
        self._reload_list()

        add_btn = QPushButton("新建…")
        add_btn.clicked.connect(self._on_add)
        del_btn = QPushButton("删除所选")
        del_btn.clicked.connect(self._on_delete)
        row = QHBoxLayout()
        row.addWidget(add_btn)
        row.addWidget(del_btn)
        row.addStretch(1)

        close = QPushButton("关闭")
        close.clicked.connect(self.accept)

        lay = QVBoxLayout(self)
        _hint = (
            "保存在应用 .cache/works_library.json。"
            "CharaWorks 须与角色 Chara.xml 的 releaseTag/netOpen 一致，请用「编辑作品」或运行 "
            "scripts/sync_acus_chara_works.py 从 chara 目录同步到 charaWorks/。"
        )
        lay.addWidget(QLabel(_hint))
        lay.addWidget(self._list, stretch=1)
        lay.addLayout(row)
        lay.addWidget(works_warning_label())
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)

    def _reload_list(self) -> None:
        self._list.clear()
        entries, _ = load_works_library()
        for e in entries:
            it = QListWidgetItem(f"{e.id} · {e.str}")
            it.setData(Qt.ItemDataRole.UserRole, e.id)
            self._list.addItem(it)

    def _on_add(self) -> None:
        _, next_id = load_works_library()
        dlg = WorkCreateDialog(suggest_id=next_id, acus_root=self._acus_root, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._reload_list()

    def _on_delete(self) -> None:
        it = self._list.currentItem()
        if it is None:
            return
        wid = it.data(Qt.ItemDataRole.UserRole)
        if wid is None:
            return
        r = QMessageBox.question(
            self,
            "删除作品",
            f"确定从作品库删除 id={wid}？\n（已写入 Chara.xml 的引用不会自动改掉。）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        remove_work_entry(int(wid))
        self._reload_list()


def make_works_picker_row(*, parent=None, acus_root: Path | None = None) -> tuple[QWidget, QComboBox]:
    """
    横向：下拉 + 「新建」+ 「管理库」。
    返回 (container, combo)。
    """
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    cb = QComboBox()
    fill_works_combo(cb)
    new_btn = QPushButton("新建…")
    mgr_btn = QPushButton("管理库…")

    def _new() -> None:
        _, nid = load_works_library()
        dlg = WorkCreateDialog(suggest_id=nid, acus_root=acus_root, parent=parent or w)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.created:
            i, s = dlg.created
            fill_works_combo(cb)
            for j in range(cb.count()):
                d = cb.itemData(j)
                if d is not None and d[0] == i:
                    cb.setCurrentIndex(j)
                    break

    def _mgr() -> None:
        WorksLibraryManagerDialog(acus_root=acus_root, parent=parent or w).exec()
        cur = combo_works_id_str(cb)
        fill_works_combo(cb)
        for j in range(cb.count()):
            d = cb.itemData(j)
            if d is not None and d[0] == cur[0] and d[1] == cur[1]:
                cb.setCurrentIndex(j)
                return
        cb.setCurrentIndex(0)

    new_btn.clicked.connect(_new)
    mgr_btn.clicked.connect(_mgr)
    h.addWidget(cb, stretch=1)
    h.addWidget(new_btn)
    h.addWidget(mgr_btn)
    return w, cb


def parse_chara_xml_net_open(xml_path: Path) -> tuple[int, str]:
    try:
        root = ET.parse(xml_path).getroot()
        ni = (root.findtext("netOpenName/id") or "").strip()
        ns = (root.findtext("netOpenName/str") or "").strip()
        try:
            iid = int(ni)
        except ValueError:
            iid = CHARA_DEFAULT_NET_OPEN_ID
        return iid, (ns or "").strip() or CHARA_DEFAULT_NET_OPEN_STR
    except Exception:
        return CHARA_DEFAULT_NET_OPEN_ID, CHARA_DEFAULT_NET_OPEN_STR


def parse_chara_xml_release_tag(xml_path: Path) -> tuple[int, str]:
    try:
        root = ET.parse(xml_path).getroot()
        ri = (root.findtext("releaseTagName/id") or "").strip()
        rs = (root.findtext("releaseTagName/str") or "").strip()
        try:
            iid = int(ri)
        except ValueError:
            iid = CHARA_DEFAULT_RELEASE_TAG_ID
        return iid, rs or CHARA_DEFAULT_RELEASE_TAG_STR
    except Exception:
        return CHARA_DEFAULT_RELEASE_TAG_ID, CHARA_DEFAULT_RELEASE_TAG_STR


def parse_chara_xml_works(xml_path: Path) -> tuple[int, str]:
    try:
        root = ET.parse(xml_path).getroot()
        wi = (root.findtext("works/id") or "").strip()
        ws = (root.findtext("works/str") or "").strip()
        try:
            iid = int(wi)
        except ValueError:
            iid = -1
        return iid, ws or "Invalid"
    except Exception:
        return -1, "Invalid"


def _esc_xml_text(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def patch_chara_xml_works(xml_path: Path, *, works_id: int, works_str: str) -> None:
    root = ET.parse(xml_path).getroot()
    works_el = root.find("works")
    if works_el is None:
        works_el = ET.SubElement(root, "works")
    safe_str = _esc_xml_text(works_str.strip() or "Invalid")
    for tag, val in (("id", str(int(works_id))), ("str", safe_str)):
        el = works_el.find(tag)
        if el is None:
            el = ET.SubElement(works_el, tag)
        el.text = val
    data_el = works_el.find("data")
    if data_el is None:
        ET.SubElement(works_el, "data")
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)


class CharaEditWorksDialog(QDialog):
    """编辑已有 Chara.xml 的 works 字段。"""

    def __init__(self, *, xml_path: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self._xml_path = xml_path
        self._acus_root = xml_path.parent.parent.parent
        self.setWindowTitle("编辑作品（works）")
        self.setModal(True)
        self.resize(520, 220)

        cur_id, cur_str = parse_chara_xml_works(xml_path)
        row, self._cb = make_works_picker_row(parent=self, acus_root=self._acus_root)
        ensure_combo_select_works(self._cb, cur_id, cur_str)

        ok = QPushButton("写入 Chara.xml")
        ok.clicked.connect(self._on_ok)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(str(xml_path.name)))
        lay.addWidget(row)
        lay.addWidget(works_warning_label())
        lay.addLayout(btns)

    def _on_ok(self) -> None:
        wid, wstr = combo_works_id_str(self._cb)
        try:
            patch_chara_xml_works(self._xml_path, works_id=wid, works_str=wstr)
        except Exception as e:
            QMessageBox.critical(self, "写入失败", str(e))
            return
        rt_id, rt_str = parse_chara_xml_release_tag(self._xml_path)
        no_id, no_str = parse_chara_xml_net_open(self._xml_path)
        try:
            ensure_chara_works_xml(
                out_dir=self._acus_root,
                works_id=wid,
                works_str=wstr,
                release_tag_id=rt_id,
                release_tag_str=rt_str,
                net_open_id=no_id,
                net_open_str=no_str,
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "CharaWorks 写入失败",
                f"Chara.xml 已更新，但未能写入 charaWorks：\n{e}",
            )
        self.accept()
