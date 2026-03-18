from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..chuni_formats import ChuniCharaId
from ..acus_workspace import AcusConfig, ensure_acus_layout
from ..dds_convert import DdsToolError, convert_to_bc3_dds
from ..xml_writer import write_chara_xml, write_ddsimage_xml
from .manager_widget import ManagerWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("chuni eventer desktop (ACUS)")
        self.resize(900, 560)

        self._acus_root = ensure_acus_layout()
        self._cfg = AcusConfig.load()

        self.tool_path = QLineEdit()
        self.tool_path.setPlaceholderText("compressonatorcli 可执行文件路径（用于 BC3 生成 & DDS 预览）")
        if self._cfg.compressonatorcli_path:
            self.tool_path.setText(self._cfg.compressonatorcli_path)

        self.chara_base = QLineEdit()
        self.chara_base.setPlaceholderText("角色基ID（= 角色ID//10，例如：2469）")

        self.chara_variant = QLineEdit()
        self.chara_variant.setPlaceholderText("变体 0-9（= 角色ID%10，例如：0）")

        self.chara_id_preview = QLineEdit()
        self.chara_id_preview.setReadOnly(True)
        self.chara_id_preview.setPlaceholderText("最终角色ID（自动计算）")

        self.chara_name = QLineEdit()
        self.chara_name.setPlaceholderText("角色显示名（写入 Chara.xml 的 name.str）")

        self.head_img = QLineEdit()
        self.half_img = QLineEdit()
        self.full_img = QLineEdit()
        for e in (self.head_img, self.half_img, self.full_img):
            e.setPlaceholderText("选择图片文件（png/jpg/webp…）")

        self.log = QTextEdit()
        self.log.setReadOnly(True)

        tabs = QTabWidget()
        tabs.addTab(self._build_generator_tab(), "生成器")
        tabs.addTab(
            ManagerWidget(acus_root=self._acus_root, get_tool_path=self._get_tool_path_or_none),
            "ACUS 管理",
        )

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(tabs)

        self.setCentralWidget(root)

    def _build_generator_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        form.addRow("ACUS 根目录", QLabel(str(self._acus_root)))
        form.addRow("DDS 工具", self._row_with_browse_file(self.tool_path, "选择 compressonatorcli"))
        form.addRow("角色基ID", self.chara_base)
        form.addRow("角色变体", self.chara_variant)
        form.addRow("最终角色ID", self.chara_id_preview)
        form.addRow("角色名", self.chara_name)
        form.addRow("大头", self._row_with_browse_image(self.head_img, "选择大头图"))
        form.addRow("半身", self._row_with_browse_image(self.half_img, "选择半身图"))
        form.addRow("全身", self._row_with_browse_image(self.full_img, "选择全身图"))

        layout.addLayout(form)

        btns = QHBoxLayout()
        run_btn = QPushButton("生成 DDS + XML（写入 ACUS）")
        run_btn.clicked.connect(self.on_run)
        btns.addStretch(1)
        btns.addWidget(run_btn)
        layout.addLayout(btns)

        layout.addWidget(QLabel("日志"))
        layout.addWidget(self.log, stretch=1)

        # live update id preview
        self.chara_base.textChanged.connect(self._update_chara_id_preview)
        self.chara_variant.textChanged.connect(self._update_chara_id_preview)
        self._update_chara_id_preview()
        return w

    def _update_chara_id_preview(self) -> None:
        base_txt = self.chara_base.text().strip()
        var_txt = self.chara_variant.text().strip()
        try:
            base = int(base_txt)
            var = int(var_txt)
            if var < 0 or var > 9:
                raise ValueError()
            cid = base * 10 + var
            self.chara_id_preview.setText(str(cid))
        except Exception:
            self.chara_id_preview.setText("")

    def _get_tool_path_or_none(self) -> Path | None:
        p = Path(self.tool_path.text().strip()).expanduser()
        return p if p.exists() else None

    def _row_with_browse_file(self, edit: QLineEdit, button_text: str) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, stretch=1)
        b = QPushButton("浏览…")
        b.clicked.connect(lambda: self._pick_file_into(edit, button_text))
        h.addWidget(b)
        return w

    def _row_with_browse_image(self, edit: QLineEdit, button_text: str) -> QWidget:
        return self._row_with_browse_file(edit, button_text)

    def _pick_file_into(self, edit: QLineEdit, title: str) -> None:
        path, _ = QFileDialog.getOpenFileName(self, title)
        if path:
            edit.setText(path)

    def _append_log(self, msg: str) -> None:
        self.log.append(msg)

    def _save_cfg(self) -> None:
        self._cfg.compressonatorcli_path = self.tool_path.text().strip()
        self._cfg.save()

    def _get_inputs(self) -> tuple[Path, int, str, Path, Path, Path]:
        try:
            base = int(self.chara_base.text().strip())
            var = int(self.chara_variant.text().strip())
        except Exception as e:
            raise ValueError("角色基ID与变体必须是整数") from e
        if var < 0 or var > 9:
            raise ValueError("变体必须在 0-9 之间")
        cid = base * 10 + var

        tool = Path(self.tool_path.text().strip()).expanduser()

        head = Path(self.head_img.text().strip()).expanduser()
        half = Path(self.half_img.text().strip()).expanduser()
        full = Path(self.full_img.text().strip()).expanduser()

        if not tool.exists():
            raise ValueError("DDS 工具路径不存在（请安装并选择 compressonatorcli）")
        for p, label in ((head, "大头"), (half, "半身"), (full, "全身")):
            if not p.exists():
                raise ValueError(f"{label} 图片路径不存在")

        return tool, cid, self.chara_name.text().strip(), head, half, full

    def on_run(self) -> None:
        try:
            tool, chara_id, chara_name, head, half, full = self._get_inputs()
            self._save_cfg()

            cid = ChuniCharaId(chara_id)
            out_dir = self._acus_root
            dds_dir = out_dir / "ddsImage" / f"ddsImage{cid.raw6}"

            self._append_log(f"角色ID: {cid.raw} => {cid.chara_key}")
            self._append_log(f"输出(ACUS): {out_dir}")
            self._append_log(f"DDS 目录: {dds_dir}")

            # 1) convert images
            targets = [
                (head, dds_dir / cid.dds_filename(0)),
                (half, dds_dir / cid.dds_filename(1)),
                (full, dds_dir / cid.dds_filename(2)),
            ]
            for src, dst in targets:
                self._append_log(f"转换: {src.name} -> {dst.name} (BC3)")
                convert_to_bc3_dds(tool_path=tool, input_image=src, output_dds=dst)

            # 2) write xml
            dds_xml = write_ddsimage_xml(out_dir=out_dir, chara_id=cid.raw)
            chara_xml = write_chara_xml(out_dir=out_dir, chara_id=cid.raw, chara_name=chara_name)

            self._append_log(f"写入: {dds_xml}")
            self._append_log(f"写入: {chara_xml}")
            QMessageBox.information(self, "完成", "已生成 DDS + XML。")
        except DdsToolError as e:
            QMessageBox.critical(self, "DDS 转换失败", str(e))
        except Exception as e:
            QMessageBox.critical(self, "错误", str(e))

