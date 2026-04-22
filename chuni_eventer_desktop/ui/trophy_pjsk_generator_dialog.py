from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QIcon, QColor, QFont, QFontDatabase, QImage, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPixmap
from PyQt6.QtWidgets import QColorDialog, QHBoxLayout, QLabel, QSlider, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, ComboBox as FluentComboBox, LineEdit, PrimaryPushButton, PushButton

from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical
from .trophy_texture_compose_dialog import compose_trophy_title_image

W = 608
H = 80
BG_PREVIEW_W = 120
BG_PREVIEW_H = 30


def _assets_root() -> Path:
    return Path(__file__).resolve().parent.parent / "static" / "PJSK Trophy"


def _background_dir() -> Path:
    return _assets_root() / "Background"


def _font_dirs() -> list[Path]:
    root = Path(__file__).resolve().parent.parent / "static"
    return [root / "fonts", root / "font", root / "PJSK Trophy" / "fonts"]


def _preferred_misans_file() -> Path:
    # 约定的打包字体路径：优先使用这个文件。
    return Path(__file__).resolve().parent.parent / "static" / "fonts" / "MiSans-Heavy.ttf"


def _resolve_misans_family() -> str:
    # 优先加载随软件打包的 MiSans-Heavy.ttf；找不到时回退系统字体。
    pref = _preferred_misans_file()
    if pref.is_file():
        fid = QFontDatabase.addApplicationFont(str(pref))
        if fid >= 0:
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                return fams[0]
    for d in _font_dirs():
        if not d.is_dir():
            continue
        for p in sorted([*d.glob("*.ttf"), *d.glob("*.otf")], key=lambda x: x.name.lower()):
            if "misans" not in p.name.lower():
                continue
            fid = QFontDatabase.addApplicationFont(str(p))
            if fid < 0:
                continue
            fams = QFontDatabase.applicationFontFamilies(fid)
            if fams:
                return fams[0]
    # 某些 PyQt6 版本下 QFontDatabase() 构造不稳定，避免实例化导致初始化失败。
    try:
        for fam in QFontDatabase.families():
            if "misans" in str(fam).lower():
                return str(fam)
    except Exception:
        pass
    return "SimHei"


def _line_files() -> list[Path]:
    root = _assets_root()
    return sorted([p for p in root.glob("Line*.png") if p.is_file()], key=lambda p: p.name.lower())


def _bg_files() -> list[Path]:
    root = _background_dir()
    return sorted([p for p in root.glob("*.png") if p.is_file()], key=lambda p: p.name.lower())


def _bg_preview_icon(path: Path) -> QIcon:
    src = QPixmap(str(path))
    if src.isNull():
        return QIcon()
    canvas = QPixmap(BG_PREVIEW_W, BG_PREVIEW_H)
    canvas.fill(Qt.GlobalColor.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    scaled = src.scaled(
        BG_PREVIEW_W,
        BG_PREVIEW_H,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = max(0, (scaled.width() - BG_PREVIEW_W) // 2)
    y = max(0, (scaled.height() - BG_PREVIEW_H) // 2)
    p.drawPixmap(0, 0, scaled.copy(x, y, BG_PREVIEW_W, BG_PREVIEW_H))
    p.end()
    return QIcon(canvas)


def _darkest_color(img: QImage) -> QColor:
    if img.isNull():
        return QColor("#808080")
    step_x = max(1, img.width() // 64)
    step_y = max(1, img.height() // 32)
    best = QColor("#808080")
    best_luma = 10**9
    for y in range(0, img.height(), step_y):
        for x in range(0, img.width(), step_x):
            c = img.pixelColor(x, y)
            # 感知亮度，值越小越“深”
            luma = 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()
            if luma < best_luma:
                best_luma = luma
                best = c
    return best


def _lift_dark_50(c: QColor) -> QColor:
    # 暗部提升 50%：按亮度放大并限制上限
    return QColor(min(255, int(c.red() * 1.5)), min(255, int(c.green() * 1.5)), min(255, int(c.blue() * 1.5)))


def render_pjsk_trophy_title(
    *,
    bg_path: Path,
    line_path: Path | None,
    text: str,
    stroke_color_override: QColor | None = None,
    font_size_px: int = 62,
    offset_x: int = 0,
    offset_y: int = -2,
) -> QImage:
    bg_pm = QPixmap(str(bg_path))
    if bg_pm.isNull():
        raise ValueError(f"无法读取底板：{bg_path.name}")
    bg_pm = bg_pm.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    out = QImage(W, H, QImage.Format.Format_ARGB32)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    p.drawPixmap(0, 0, bg_pm)

    # 文本：黑体加粗 + 渐变填充 + 5px 外描边
    text_draw = (text or "").strip()
    if text_draw:
        bg_dark = _darkest_color(out)
        stroke_color = stroke_color_override if stroke_color_override is not None else _lift_dark_50(bg_dark)
        font = QFont(_resolve_misans_family())
        font.setBold(True)
        font.setPixelSize(max(10, int(font_size_px)))
        p.setFont(font)

        # 以路径居中，便于描边与渐变控制
        path = QPainterPath()
        # x/y 使用基线坐标：先用字体度量做居中定位
        fm = p.fontMetrics()
        bw = fm.horizontalAdvance(text_draw)
        # 文本垂直大致中心，略上移 2px
        baseline_x = (W - bw) / 2.0 + float(offset_x)
        baseline_y = (H + fm.ascent() - fm.descent()) / 2.0 + float(offset_y)
        path.addText(baseline_x, baseline_y, font, text_draw)

        stroker = QPainterPathStroker()
        stroker.setWidth(10.0)  # 近似 5px 外描边
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroke = stroker.createStroke(path)
        p.fillPath(stroke, stroke_color)

        grad = QLinearGradient(0.0, 0.0, 0.0, float(H))
        grad.setColorAt(0.0, QColor("#ffffff"))
        grad.setColorAt(0.5, QColor("#ffffff"))
        grad.setColorAt(1.0, QColor("#fff665"))
        p.fillPath(path, grad)

    if line_path is not None:
        ln = QPixmap(str(line_path))
        if not ln.isNull():
            ln = ln.scaled(W, H, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(0, 0, ln)
    p.end()
    return out


class TrophyPjskGeneratorDialog(FluentCaptionDialog):
    def __init__(self, *, out_dir: Path, parent=None) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("PJSK 称号贴图自助生成")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.resize(760, 520)
        self._out_dir = out_dir
        self.result_png_path: Path | None = None
        self._stroke_override: QColor | None = None
        self._font_size = 48
        self._offset_x = -50
        self._offset_y = 0

        self._bgs = _bg_files()
        self._lines = _line_files()
        if not self._bgs:
            raise ValueError(f"未找到底板资源：{_background_dir()}")

        self.bg_combo = FluentComboBox(self)
        self.bg_combo.setIconSize(QSize(BG_PREVIEW_W, BG_PREVIEW_H))
        for p in self._bgs:
            self.bg_combo.addItem(p.stem, _bg_preview_icon(p), str(p))
        self.line_combo = FluentComboBox(self)
        self.line_combo.addItem("无外框 line", None, "")
        for p in self._lines:
            self.line_combo.addItem(p.stem, None, str(p))
        self.text_edit = LineEdit(self)
        self.text_edit.setPlaceholderText("输入称号文字")
        self.stroke_color_label = BodyLabel("描边颜色：自动取色", self)
        self.stroke_color_label.setTextColor("#6B7280", "#9CA3AF")
        self.font_label = BodyLabel(self)
        self.font_label.setTextColor("#6B7280", "#9CA3AF")
        self.font_label.setText(
            f"字体：{_resolve_misans_family()}（优先 {str(_preferred_misans_file())}）"
        )

        self.preview = QLabel(self)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(200)
        self.preview.setStyleSheet("border:1px solid #d1d5db;border-radius:8px;")

        hint = BodyLabel(
            "文字样式：黑体加粗，填充渐变（#ffffff -> #ffffff -> #fff665），"
            "并按当前底板平均色生成 5px 外描边（暗部提升 50%）。",
            self,
        )
        hint.setWordWrap(True)
        hint.setTextColor("#6B7280", "#9CA3AF")

        self.bg_combo.currentIndexChanged.connect(self._refresh_preview)
        self.line_combo.currentIndexChanged.connect(self._refresh_preview)
        self.text_edit.textChanged.connect(self._refresh_preview)
        pick_stroke_btn = PushButton("描边取色器…", self)
        pick_stroke_btn.clicked.connect(self._pick_stroke_color)
        auto_stroke_btn = PushButton("描边改回自动", self)
        auto_stroke_btn.clicked.connect(self._reset_stroke_color)
        self.size_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.size_slider.setRange(20, 96)
        self.size_slider.setValue(self._font_size)
        self.size_slider.valueChanged.connect(self._on_slider_changed)
        self.x_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.x_slider.setRange(-180, 180)
        self.x_slider.setValue(self._offset_x)
        self.x_slider.valueChanged.connect(self._on_slider_changed)
        self.y_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.y_slider.setRange(-80, 80)
        self.y_slider.setValue(self._offset_y)
        self.y_slider.valueChanged.connect(self._on_slider_changed)
        self.size_label = BodyLabel("", self)
        self.size_label.setTextColor("#6B7280", "#9CA3AF")
        self.x_label = BodyLabel("", self)
        self.x_label.setTextColor("#6B7280", "#9CA3AF")
        self.y_label = BodyLabel("", self)
        self.y_label.setTextColor("#6B7280", "#9CA3AF")

        make_btn = PrimaryPushButton("生成并填入", self)
        make_btn.clicked.connect(self._on_make)
        cancel_btn = PushButton("取消", self)
        cancel_btn.clicked.connect(self.reject)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(cancel_btn)
        foot.addWidget(make_btn)

        card = CardWidget(self)
        cly = QVBoxLayout(card)
        cly.setContentsMargins(16, 14, 16, 14)
        cly.setSpacing(10)
        cly.addWidget(BodyLabel("底板", self))
        cly.addWidget(self.bg_combo)
        cly.addWidget(BodyLabel("外框 line", self))
        cly.addWidget(self.line_combo)
        cly.addWidget(BodyLabel("文字", self))
        cly.addWidget(self.text_edit)
        cly.addWidget(self.font_label)
        stroke_row = QHBoxLayout()
        stroke_row.addWidget(pick_stroke_btn)
        stroke_row.addWidget(auto_stroke_btn)
        stroke_row.addStretch(1)
        cly.addLayout(stroke_row)
        cly.addWidget(self.stroke_color_label)
        cly.addWidget(self.size_label)
        cly.addWidget(self.size_slider)
        cly.addWidget(self.x_label)
        cly.addWidget(self.x_slider)
        cly.addWidget(self.y_label)
        cly.addWidget(self.y_slider)
        cly.addWidget(hint)
        cly.addWidget(self.preview, stretch=1)
        cly.addLayout(foot)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(*fluent_caption_content_margins())
        lay.setSpacing(10)
        lay.addWidget(card, stretch=1)

        self._refresh_preview()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        print(
            f"[trophy-debug] pjsk show ts={time.time():.3f} "
            f"visible={self.isVisible()} active={self.isActiveWindow()} "
            f"geom={self.geometry().x()},{self.geometry().y()},{self.geometry().width()},{self.geometry().height()}"
        )

    def _picked_bg(self) -> Path:
        d = self.bg_combo.currentData()
        s = str(d or "").strip()
        if s:
            return Path(s)
        return self._bgs[0]

    def _picked_line(self) -> Path | None:
        d = self.line_combo.currentData()
        s = str(d or "").strip()
        return Path(s) if s else None

    def _refresh_preview(self) -> None:
        self._font_size = int(self.size_slider.value())
        self._offset_x = int(self.x_slider.value())
        self._offset_y = int(self.y_slider.value())
        self.size_label.setText(f"文字大小：{self._font_size}px")
        self.x_label.setText(f"文字横向位置：{self._offset_x:+d}px")
        self.y_label.setText(f"文字纵向位置：{self._offset_y:+d}px")
        try:
            img80 = render_pjsk_trophy_title(
                bg_path=self._picked_bg(),
                line_path=self._picked_line(),
                text=self.text_edit.text().strip(),
                stroke_color_override=self._stroke_override,
                font_size_px=self._font_size,
                offset_x=self._offset_x,
                offset_y=self._offset_y,
            )
            img = compose_trophy_title_image(user_image=img80)
        except Exception as e:
            self.preview.setText(f"预览失败：{e}")
            self.preview.setPixmap(QPixmap())
            return
        pm = QPixmap.fromImage(img)
        self.preview.setText("")
        self.preview.setPixmap(pm.scaledToWidth(620, Qt.TransformationMode.SmoothTransformation))

    def _on_make(self) -> None:
        txt = self.text_edit.text().strip()
        if not txt:
            fly_critical(self, "错误", "请先输入称号文字。")
            return
        try:
            img80 = render_pjsk_trophy_title(
                bg_path=self._picked_bg(),
                line_path=self._picked_line(),
                text=txt,
                stroke_color_override=self._stroke_override,
                font_size_px=self._font_size,
                offset_x=self._offset_x,
                offset_y=self._offset_y,
            )
            img = compose_trophy_title_image(user_image=img80)
        except Exception as e:
            fly_critical(self, "生成失败", str(e))
            return
        self._out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out = self._out_dir / f"pjsk_trophy_{ts}.png"
        if not img.save(str(out), "PNG"):
            fly_critical(self, "生成失败", f"无法写入：{out}")
            return
        self.result_png_path = out
        self.accept()

    def _pick_stroke_color(self) -> None:
        initial = self._stroke_override if self._stroke_override is not None else QColor("#808080")
        c = QColorDialog.getColor(initial, self, "选择描边颜色")
        if not c.isValid():
            return
        self._stroke_override = c
        self.stroke_color_label.setText(f"描边颜色：手动 {c.name().upper()}")
        self._refresh_preview()

    def _reset_stroke_color(self) -> None:
        self._stroke_override = None
        self.stroke_color_label.setText("描边颜色：自动取色")
        self._refresh_preview()

    def _on_slider_changed(self, _value: int) -> None:
        self._refresh_preview()

