#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离屏抓取 v0.8.3 更新介绍片所需的真实界面截图（可重复运行）。

    .venv-build\\Scripts\\python.exe scripts\\capture_ui_shots.py
    .venv-build\\Scripts\\python.exe scripts\\capture_ui_shots.py --only mate
    .venv-build\\Scripts\\python.exe scripts\\capture_ui_shots.py --list

做法：``QT_QPA_PLATFORM=offscreen`` 下构造真实对话框 / 主窗口，``widget.grab()`` 后写 PNG。

只读 ACUS 与 ``pjsk_cache/``（真实数据只用于列表文字）；中间文件写
``docs/Introduction/v0.8.3/_tmp/capture/``，运行结束自动删除。
输出目录：``docs/Introduction/v0.8.3/film/assets/img/``。
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import QPoint, QRect, Qt  # noqa: E402
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from qfluentwidgets import Theme, setTheme  # noqa: E402

OUT_DIR = ROOT / "docs" / "Introduction" / "v0.8.3" / "film" / "assets" / "img"
TMP_DIR = ROOT / "docs" / "Introduction" / "v0.8.3" / "_tmp" / "capture"
ACUS_ROOT = ROOT / "ACUS"

# ---------------------------------------------------------------------------
# 假数据（报告里逐项列出）：只用于把控件填到有内容的状态，不写任何真实数据。
# ---------------------------------------------------------------------------

# 在线模型仓库（真实接口 https://lolicount.top/api/psb/models 本轮 SSL 不通，
# 这里按剧情里提到的作品名造一份列表；控件文字仍由真实 combo.addItem 写入）
FAKE_MODELS: tuple[str, ...] = (
    "nekopara_vanilla.psb",
    "nekopara_chocola.psb",
    "nekopara_azuki.psb",
    "nekopara_coconut.psb",
    "nekopara_cinnamon.psb",
    "nekopara_maple.psb",
    "nekopara_cacao.psb",
    "steinsgate_kurisu.psb",
    "steinsgate_mayuri.psb",
    "steinsgate_suzuha.psb",
    "chunithm_ikazuchi.psb",
    "chunithm_milk.psb",
    "chunithm_tsumugi.psb",
    "chunithm_azuki_mate.psb",
    "chunithm_margrete.psb",
    "chunithm_chiffon.psb",
) + tuple(f"sample_mate_{i:03d}.psb" for i in range(17, 85))  # 凑满 84 个（分镜里的数量）

# PSB 解析结果（动作名是 FreeMote 解包后 timeline 的真实命名习惯）
FAKE_TIMELINES: tuple[tuple[str, int], ...] = (
    ("平常ループ", 0),
    ("ウインク", 0),
    ("怒る00", 0),
    ("怒る01", 0),
    ("哀しい00", 0),
    ("哀しい01", 0),
    ("喜ぶ00", 0),
    ("喜ぶ01", 0),
    ("照れる", 1),
    ("首かしげ", 1),
    ("手を振る", 1),
    ("ジャンプ", 1),
)

# PJSK 曲目库列表（真实接口本轮不可用；标题/作曲家做成常见的 PJSK 收录曲）
FAKE_PJSK_MUSICS: tuple[tuple[int, str, str, str, int], ...] = (
    (8, "Tell Your World", "livetune", "jacket_s_008", 18),
    (21, "みくみくにしてあげる♪【してやんよ】", "ika_mo", "jacket_s_021", 24),
    (32, "千本桜", "黒うさP", "jacket_s_032", 26),
    (74, "夜咄ディセイブ", "じん", "jacket_s_074", 28),
    (124, "ロキ", "みきとP", "jacket_s_124", 27),
    (172, "ECHO", "Crusher-P", "jacket_s_172", 25),
    (224, "シャルル", "バルーン", "jacket_s_224", 26),
    (328, "ワーワーワールド", "Giga × Mitchie M", "jacket_s_328", 30),
    (409, "25時の情熱", "カンザキイオリ", "jacket_s_409", 25),
    (504, "フォニイ", "ツミキ", "jacket_s_504", 27),
    (611, "神っぽいな", "ピノキオピー", "jacket_s_611", 28),
    (722, "KING", "Kanaria", "jacket_s_722", 26),
    (818, "ヴァンパイア", "DECO*27", "jacket_s_818", 27),
    (901, "少女レイ", "みきとP", "jacket_s_901", 29),
    (1002, "悪ノ娘", "mothy", "jacket_s_1002", 25),
    (1104, "劣等上等", "Giga", "jacket_s_1104", 31),
)

# 转换流水线真实进度文案（见 pjsk2chuni/pipeline.py 的 bump()）
PJSK_PROGRESS_MSG = "已生成 MASTER 谱面…"
PJSK_DONE_MSG = "完成"

CAPTURED: list[tuple[str, str, int, int]] = []  # (文件名, 来源类名, 宽, 高)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def boot_qt() -> QApplication:
    """离屏 QApplication + 显式字体 + 固定浅色主题（保证每次结果一致）。"""
    app = QApplication.instance() or QApplication([])
    font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    # offscreen 平台没有自带字体，必须手动注册，否则整屏豆腐块
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "segoeuib.ttf", "consola.ttf"):
        p = font_dir / name
        if p.is_file():
            QFontDatabase.addApplicationFont(str(p))
    app.setFont(QFont("Microsoft YaHei UI", 9))
    setTheme(Theme.LIGHT)
    return app


def pump(app: QApplication, rounds: int = 6) -> None:
    for _ in range(rounds):
        app.processEvents()


def flatten(pm: QPixmap, *, bg: str = "#ffffff", pad: int = 0) -> QPixmap:
    """把截图铺到纯色底上（透明/半透明弹窗用），pad 为四周留白。"""
    w, h = pm.width() + pad * 2, pm.height() + pad * 2
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(bg))
    p = QPainter(img)
    p.drawPixmap(pad, pad, pm)
    p.end()
    return QPixmap.fromImage(img)


def save_shot(pm: QPixmap, name: str, *, bg: str | None = None, pad: int = 0) -> None:
    if bg is not None:
        pm = flatten(pm, bg=bg, pad=pad)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    if not pm.save(str(out), "PNG"):
        raise RuntimeError(f"写入失败：{out}")
    CAPTURED.append((name, "", pm.width(), pm.height()))
    print(f"  [ok] {name}  {pm.width()}x{pm.height()}")


def grab_widget(app: QApplication, widget, name: str, *, bg: str | None = None,
                pad: int = 0, source: str = "") -> None:
    widget.show()
    pump(app)
    pm = widget.grab()
    before = len(CAPTURED)
    save_shot(pm, name, bg=bg, pad=pad)
    if len(CAPTURED) > before:
        _name, _src, w, h = CAPTURED[-1]
        CAPTURED[-1] = (name, source or type(widget).__name__, w, h)


def grab_child(app: QApplication, widget, name: str, *, source: str = "") -> None:
    widget.show()  # 先让父级完成布局
    pump(app)
    pm = widget.grab()
    before = len(CAPTURED)
    save_shot(pm, name, bg="#ffffff", pad=24)
    if len(CAPTURED) > before:
        _name, _src, w, h = CAPTURED[-1]
        CAPTURED[-1] = (name, source or type(widget).__name__, w, h)


def _fake_psb_data():
    from chuni_eventer_desktop.psb_action_assigner import PsbActionData, TimelineInfo

    timelines = [TimelineInfo(label=label, diff=diff) for label, diff in FAKE_TIMELINES]
    return PsbActionData(
        psb_path=TMP_DIR / "azuki_mate.psb",
        timelines=timelines,
        platform="PSB(common)",
    )


def _prepare_fake_portrait() -> Path:
    """从 ACUS 里已有的 mate 图标（只读 DDS）裁出立绘层，供预览图合成器演示。"""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    dds = ACUS_ROOT / "mate" / "mate031005" / "CHU_UI_Mate_031005.dds"
    png = TMP_DIR / "mate_icon.png"
    if not png.is_file():
        from chuni_eventer_desktop.dds_quicktex import dds_to_png_quicktex

        dds_to_png_quicktex(input_dds=dds, output_png=png)
    img = QImage(str(png))
    if img.isNull():
        raise RuntimeError(f"无法读取 {png}")
    # 去掉图标外框，只留中间立绘（合成器会自己画白框与 Mate 标签）
    crop = img.copy(QRect(95, 72, 233, 168))
    portrait = TMP_DIR / "mate_portrait.png"
    if not crop.save(str(portrait), "PNG"):
        raise RuntimeError(f"无法写入 {portrait}")
    return portrait


# ---------------------------------------------------------------------------
# Mate
# ---------------------------------------------------------------------------


def capture_mate_entry(app: QApplication) -> None:
    """① 新增伴侣（PSB 导入）对话框初始状态。"""
    from chuni_eventer_desktop.ui.psb_action_dialog import PsbActionDialog

    dlg = PsbActionDialog(
        acus_root=ACUS_ROOT,
        freemote_dir=ROOT / "tools" / "FreeMote",
        mate_id=31006,
    )
    grab_widget(app, dlg, "mate-01-entry.png", source="PsbActionDialog")


def _fill_mate_dialog(dlg, *, with_models: bool) -> None:
    """把对话框填到「选好在线模型 + 已解析出动作」的状态（全部为假数据）。"""
    dlg.resize(1480, 1000)
    dlg.name_edit.setText("アズキ")
    dlg.mate_id_edit.setValue(31006)
    if with_models:
        dlg.model_combo.blockSignals(True)
        dlg.model_combo.clear()
        for m in FAKE_MODELS:
            dlg.model_combo.addItem(m, userData=m)
        dlg.model_combo.setCurrentIndex(2)
        dlg.model_combo.blockSignals(False)
        dlg.psb_path_edit.setText(str(TMP_DIR / "nekopara_azuki.psb"))

    dlg._psb_data = _fake_psb_data()
    dlg._psb_path = dlg._psb_data.psb_path
    dlg._finish_load()
    dlg._status.setText(
        f"在线仓库共 {len(FAKE_MODELS)} 个模型，选择后点「下载并解析」"
    )


def capture_mate_repo(app: QApplication) -> None:
    """② 在线模型列表（combo 展开）+ 解析后的 4 个动作下拉。"""
    from PyQt6.QtWidgets import QApplication as QApp

    from chuni_eventer_desktop.ui.psb_action_dialog import PsbActionDialog

    dlg = PsbActionDialog(
        acus_root=ACUS_ROOT,
        freemote_dir=ROOT / "tools" / "FreeMote",
        mate_id=31006,
    )
    _fill_mate_dialog(dlg, with_models=True)
    dlg.show()
    pump(app)
    dlg.model_combo.showPopup()
    pump(app, 4)
    pm = dlg.grab()
    popup = QApp.activePopupWidget()
    if popup is not None:
        ppm = popup.grab()
        if not ppm.isNull():
            top_left = dlg.mapFromGlobal(popup.mapToGlobal(QPoint(0, 0)))
            painter = QPainter(pm)
            painter.drawPixmap(top_left, ppm)
            painter.end()
    save_shot(pm, "mate-02-repo.png")
    CAPTURED[-1] = ("mate-02-repo.png", "PsbActionDialog（QComboBox 弹层）",
                    pm.width(), pm.height())
    dlg.model_combo.hidePopup()
    pump(app)


def capture_mate_position(app: QApplication) -> None:
    """③ 位置预览卡片特写：16:9 画布 + posX / posY / scale 数值区。"""
    from chuni_eventer_desktop.ui.psb_action_dialog import PsbActionDialog

    dlg = PsbActionDialog(
        acus_root=ACUS_ROOT,
        freemote_dir=ROOT / "tools" / "FreeMote",
        mate_id=31006,
    )
    _fill_mate_dialog(dlg, with_models=True)
    dlg.resize(1520, 1040)
    dlg.show()
    pump(app)
    dlg.pos_x_spin.setValue(120)
    dlg.pos_y_spin.setValue(-80)
    dlg.scale_spin.setValue(6400)
    pump(app)
    card = dlg.preview.parentWidget()
    grab_child(app, card, "mate-03-position.png", source="MatePositionPreview（所在卡片）")
    dlg.close()


def capture_mate_composer(app: QApplication) -> None:
    """④ 伴侣预览图合成器：斜纹框底 + 立绘 + MATE 标签。"""
    from chuni_eventer_desktop.ui.mate_preview_dialog import MatePreviewDialog

    dlg = MatePreviewDialog(acus_root=None)
    dlg.resize(640, 560)
    dlg.show()
    pump(app)
    portrait = _prepare_fake_portrait()
    dlg._canvas.load_portrait(portrait)
    dlg._scale_slider.blockSignals(True)
    dlg._scale_slider.setValue(int(dlg._canvas.scale() * 100))
    dlg._scale_slider.blockSignals(False)
    pump(app)
    grab_widget(app, dlg, "mate-04-composer.png", source="MatePreviewDialog")


def capture_mate_list(app: QApplication) -> None:
    """⑤ 主界面「其他 → 伙伴」列表页（真实主窗口 + 真实 ACUS 数据）。"""
    import chuni_eventer_desktop.ui.main_window as mw

    # 只读：绕开 ensure_acus_layout（会往 ACUS 里补种子文件），也不触发游戏目录扫描
    mw.ensure_acus_layout = lambda **_kw: ACUS_ROOT  # type: ignore[assignment]
    mw.MainWindow._ensure_game_index_background = lambda self: None  # type: ignore[assignment]
    mw.MainWindow._bootstrap_external_tools = lambda self: None  # type: ignore[assignment]

    win = mw.MainWindow()
    win.show()
    pump(app)
    win.deferred_build_ui()
    pump(app, 8)
    win.resize(1440, 900)
    win._enter_others_mode("nav_others")
    pump(app)
    win._others_seg.setCurrentItem("mate")
    pump(app, 8)
    grab_widget(app, win, "mate-05-list.png", source="MainWindow（其他 → 伙伴）")
    # 分镜里 s04 期望的文件名是 main-other-mate.png，同步存一份
    src = OUT_DIR / "mate-05-list.png"
    dst = OUT_DIR / "main-other-mate.png"
    shutil.copyfile(src, dst)
    CAPTURED.append(("main-other-mate.png", "同 mate-05-list.png", 0, 0))
    print(f"  [ok] main-other-mate.png（复制自 mate-05-list.png）")
    win.close()


# ---------------------------------------------------------------------------
# PJSK
# ---------------------------------------------------------------------------


def capture_pjsk_entry(app: QApplication) -> None:
    """⑥ 乐曲页「新增」→ 自制谱下载渠道弹窗（SwanSite / pgko / PJSK）。"""
    from chuni_eventer_desktop.ui.music_add_actions_dialog import MusicSheetChannelsDialog

    dlg = MusicSheetChannelsDialog()
    dlg.show()
    pump(app)
    dlg.adjustSize()
    pump(app)
    pm = dlg.grab()
    print(f"  [i] 渠道弹窗 grab 带 alpha：{pm.hasAlphaChannel()}")
    save_shot(pm, "pjsk-01-entry.png", bg="#0b0d16", pad=28)
    CAPTURED[-1] = ("pjsk-01-entry.png", "MusicSheetChannelsDialog（深色底铺平）",
                    pm.width() + 56, pm.height() + 56)


def capture_pjsk_hub(app: QApplication) -> None:
    """⑦ PJSK 谱面 → 中二：本地缓存列表（真实 pjsk_cache）。"""
    from chuni_eventer_desktop.ui.pjsk_hub_dialog import PjskHubDialog

    dlg = PjskHubDialog(acus_root=ACUS_ROOT)
    dlg.resize(1120, 780)
    dlg.show()
    pump(app, 10)
    grab_widget(app, dlg, "pjsk-02-hub.png", source="PjskHubDialog")
    dlg.close()


def capture_pjsk_download(app: QApplication) -> None:
    """⑧ 从 Project SEKAI 缓存资源：曲目库列表（假数据，避免联网下载）。"""
    from chuni_eventer_desktop.pjsk_sheet_client import PjskMusicRow
    from chuni_eventer_desktop.ui.pjsk_sus_download_dialog import PjskSusDownloadDialog

    original_reload = PjskSusDownloadDialog._on_reload
    PjskSusDownloadDialog._on_reload = lambda self: None  # type: ignore[assignment]
    try:
        dlg = PjskSusDownloadDialog(acus_root=ACUS_ROOT)
        dlg.resize(1080, 760)
        dlg._musics = [
            PjskMusicRow(music_id=mid, title=title, composer=composer,
                         assetbundle_name=ab, filler_sec=None)
            for mid, title, composer, ab, _lv in FAKE_PJSK_MUSICS
        ]
        dlg._apply_filter()
        dlg._status.setText(
            f"已加载 {len(dlg._musics)} 首曲目。选中一行后点「下载选中曲目到缓存」或双击表格行。"
        )
        dlg._table.selectRow(8)
        dlg.show()
        pump(app, 8)
        grab_widget(app, dlg, "pjsk-03-download.png", source="PjskSusDownloadDialog")
        dlg.close()
    finally:
        PjskSusDownloadDialog._on_reload = original_reload  # type: ignore[assignment]


def _open_convert_dialog():
    from chuni_eventer_desktop.pjsk_acus_install import (
        iter_local_pjsk_bundles,
        next_chuni_music_id,
    )
    from chuni_eventer_desktop.pjsk_sheet_client import pjsk_cache_root
    from chuni_eventer_desktop.ui.pjsk_hub_dialog import PjskConvertToAcusDialog

    bundles = iter_local_pjsk_bundles(pjsk_cache_root(ACUS_ROOT))
    if not bundles:
        raise RuntimeError("pjsk_cache 里没有可用缓存，无法拍转换设置对话框")
    bundle = bundles[0]
    default_id = next_chuni_music_id(ACUS_ROOT, start=7000)
    dlg = PjskConvertToAcusDialog(
        acus_root=ACUS_ROOT, bundle=bundle, default_chuni_id=default_id
    )
    dlg.resize(680, 820)
    return dlg, bundle


def capture_pjsk_convert(app: QApplication) -> None:
    """⑨ 转换设置对话框（真实缓存曲目 + 按 PJSK 等级算好的定数）。"""
    dlg, bundle = _open_convert_dialog()
    dlg.show()
    pump(app, 8)
    pm = dlg.grab()
    save_shot(pm, "pjsk-04-convert.png")
    CAPTURED[-1] = ("pjsk-04-convert.png", "PjskConvertToAcusDialog", pm.width(), pm.height())
    print(f"  [i] 曲目：{bundle.title} / {bundle.composer}（PJSK ID {bundle.pjsk_music_id}）")
    dlg.close()


def capture_pjsk_progress(app: QApplication) -> None:
    """⑩ 转换进行中（后台流水线 + 进度条）。"""
    dlg, bundle = _open_convert_dialog()
    dlg.show()
    pump(app, 6)
    dlg._prog_label.show()
    dlg._prog_bar.show()
    dlg._prog_label.setText(PJSK_PROGRESS_MSG)
    dlg._prog_bar.setRange(0, 1000)
    dlg._prog_bar.setValue(720)
    dlg.setEnabled(False)  # 真实 _run() 里转换期间也是这样禁用
    pump(app, 6)
    grab_widget(app, dlg, "pjsk-05-progress.png", source="PjskConvertToAcusDialog（转换中）")
    dlg.close()


def capture_pjsk_done(app: QApplication) -> None:
    """⑪ 转换完成状态：进度条走满 + 「完成」。"""
    dlg, _bundle = _open_convert_dialog()
    dlg.show()
    pump(app, 6)
    dlg._prog_label.show()
    dlg._prog_bar.show()
    dlg._prog_label.setText(PJSK_DONE_MSG)
    dlg._prog_bar.setRange(0, 1000)
    dlg._prog_bar.setValue(1000)
    pump(app, 6)
    grab_widget(app, dlg, "pjsk-06-done.png", source="PjskConvertToAcusDialog（完成）")
    dlg.close()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

SHOTS = {
    "mate-01-entry": capture_mate_entry,
    "mate-02-repo": capture_mate_repo,
    "mate-03-position": capture_mate_position,
    "mate-04-composer": capture_mate_composer,
    "mate-05-list": capture_mate_list,
    "pjsk-01-entry": capture_pjsk_entry,
    "pjsk-02-hub": capture_pjsk_hub,
    "pjsk-03-download": capture_pjsk_download,
    "pjsk-04-convert": capture_pjsk_convert,
    "pjsk-05-progress": capture_pjsk_progress,
    "pjsk-06-done": capture_pjsk_done,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="离屏抓取 ChuniEventer 界面截图")
    parser.add_argument("--only", default="", help="只拍匹配前缀的镜头，逗号分隔，如 mate-01,pjsk-02")
    parser.add_argument("--list", action="store_true", help="只列出镜头名")
    args = parser.parse_args(argv)

    if args.list:
        for key in SHOTS:
            print(key)
        return 0

    wanted = [k for k in args.only.split(",") if k.strip()] if args.only else []
    keys = [k for k in SHOTS if not wanted or any(k.startswith(w.strip()) for w in wanted)]
    if not keys:
        print(f"没有匹配的镜头：{args.only}")
        return 1

    app = boot_qt()
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        for key in keys:
            print(f"== {key}")
            try:
                SHOTS[key](app)
            except Exception as e:  # noqa: BLE001 — 单张失败不影响其余
                print(f"  [FAIL] {key}: {type(e).__name__}: {e}")
    finally:
        # 临时立绘 / 图标只服务本次抓拍，用完即删
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    print("\n== 已生成")
    for name, source, w, h in CAPTURED:
        size = f"{w}x{h}" if w else "（复制）"
        print(f"  {name:<24} {size:<12} {source}")
    print(f"\n输出目录：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
