from __future__ import annotations

import logging
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QInputDialog, QVBoxLayout

from qfluentwidgets import BodyLabel, CardWidget, CheckBox, LineEdit, PrimaryPushButton, PushButton

from ..acus_workspace import AcusConfig, app_cache_dir
from ..dds_convert import DdsToolError, is_bc3_dds, run_cmd, validate_compressonator_tool
from ..dds_quicktex import encode_image_to_bc3_dds_quicktex, quicktex_available
from .fluent_caption_dialog import FluentCaptionDialog, fluent_caption_content_margins
from .fluent_dialogs import fly_critical, fly_message, fly_warning
from .pjsk_hub_dialog import PjskHubDialog

_settings_log_logger: logging.Logger | None = None


def _settings_logger() -> logging.Logger:
    global _settings_log_logger
    if _settings_log_logger is not None:
        return _settings_log_logger
    logger = logging.getLogger("chuni.settings_dialog")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        log_dir = app_cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "settings_save.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
    except Exception:
        pass
    _settings_log_logger = logger
    return logger


class SettingsDialog(FluentCaptionDialog):
    def __init__(
        self,
        *,
        cfg: AcusConfig,
        acus_root: Path,
        get_tool_path: Callable[[], Path | None],
        on_request_game_rescan: Callable[[Path, Path | None], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent=parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.resize(520, 520)
        self._cfg = cfg
        self._acus_root = acus_root.resolve()
        self._get_tool_path = get_tool_path
        self._on_request_game_rescan = on_request_game_rescan

        game_hint = BodyLabel(
            "指定已安装游戏中的 **A001** 数据位置（或包含 `A001` / `Option/A001` 的安装根目录）。"
            "用于扫描全量乐曲、场景、DDS 贴图与地图 ddsMap，供地图/奖励编辑下拉里选择。"
        )
        game_hint.setWordWrap(True)
        self.game_root = LineEdit(self)
        self.game_root.setPlaceholderText("例如 D:\\Games\\CHUNITHM 或 …\\A001 的上一级")
        if cfg.game_root:
            self.game_root.setText(cfg.game_root)
        game_browse = PushButton("浏览文件夹…", self)
        game_browse.clicked.connect(self._pick_game_root)
        rescan = PushButton("重新扫描游戏索引", self)
        rescan.clicked.connect(self._rescan_game_index)

        game_row = QHBoxLayout()
        game_row.setSpacing(8)
        game_row.addWidget(self.game_root, stretch=1)
        game_row.addWidget(game_browse)

        game_card = CardWidget(self)
        game_layout = QVBoxLayout(game_card)
        game_layout.setContentsMargins(16, 16, 16, 16)
        game_layout.setSpacing(12)
        game_layout.addWidget(BodyLabel("游戏数据目录", self))
        game_layout.addWidget(game_hint)
        game_layout.addLayout(game_row)
        game_layout.addWidget(rescan)

        if getattr(sys, "frozen", False):
            dds_hint = (
                "打包版已在 exe 同级的 .tools\\CompressonatorCLI 附带 AMD Compressonator CLI。"
                "此处留空则自动使用该副本；填写路径则优先使用您指定的 compressonatorcli.exe。"
            )
            ph = "留空用附带 CLI；或浏览选择自定义 compressonatorcli.exe"
        else:
            dds_hint = (
                "DDS 预览与 BC3 生成默认使用 quicktex；此处可填写 compressonatorcli 作为备选路径。"
            )
            ph = "compressonatorcli 可执行文件路径（可选）"
        hint = BodyLabel(dds_hint)
        hint.setWordWrap(True)

        self.compressonator = LineEdit(self)
        self.compressonator.setPlaceholderText(ph)
        if cfg.compressonatorcli_path:
            self.compressonator.setText(cfg.compressonatorcli_path)

        browse = PushButton("浏览…", self)
        browse.clicked.connect(self._pick_tool)
        test_btn = PushButton("测试转换能力", self)
        test_btn.clicked.connect(self._test_dds_convert)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.compressonator, stretch=1)
        row.addWidget(browse)
        row.addWidget(test_btn)

        card = CardWidget(self)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)
        card_layout.addWidget(BodyLabel("compressonator CLI", self))
        card_layout.addWidget(hint)
        card_layout.addLayout(row)

        pjsk_card = CardWidget(self)
        pjsk_layout = QVBoxLayout(pjsk_card)
        pjsk_layout.setContentsMargins(16, 16, 16, 16)
        pjsk_layout.setSpacing(12)
        pjsk_layout.addWidget(BodyLabel("烤谱（Project SEKAI · 实验）", self))
        pjsk_hint = BodyLabel(
            "本功能仅供图一乐：从游戏导出的 SUS 与自动转换结果不经精修几乎无法正常游玩。\n"
            "需要可玩的自制谱，请在歌曲页点击「新增」→ 选择 SwanSite，下载已精修谱面并导入。"
        )
        pjsk_hint.setWordWrap(True)
        pjsk_hint.setStyleSheet("color:#b45309;font-size:13px;")
        pjsk_layout.addWidget(pjsk_hint)
        pjsk_open = PushButton("打开烤谱下载与本地缓存…", self)
        pjsk_open.clicked.connect(self._open_pjsk_hub)
        pjsk_layout.addWidget(pjsk_open)

        pgko_card = CardWidget(self)
        pgko_layout = QVBoxLayout(pgko_card)
        pgko_layout.setContentsMargins(16, 16, 16, 16)
        pgko_layout.setSpacing(12)
        pgko_layout.addWidget(BodyLabel("PGKO UGC 直转 c2s（实验）", self))
        pgko_hint = BodyLabel(
            "默认关闭。关闭时，主流程只允许 mgxc -> c2s；"
            "UGC 直转仅作为实验功能在 UGC 引导页中可见。"
        )
        pgko_hint.setWordWrap(True)
        pgko_hint.setStyleSheet("color:#b45309;font-size:13px;")
        pgko_layout.addWidget(pgko_hint)
        self.pgko_exp_checkbox = CheckBox("启用实验性 UGC 直转入口", self)
        self.pgko_exp_checkbox.setChecked(bool(getattr(cfg, "enable_pgko_ugc_experimental", False)))
        pgko_layout.addWidget(self.pgko_exp_checkbox)

        ok = PrimaryPushButton("保存", self)
        ok.clicked.connect(self._on_save_clicked)
        cancel = PushButton("取消", self)
        cancel.clicked.connect(self.reject)

        btns = QHBoxLayout()
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(*fluent_caption_content_margins())
        layout.setSpacing(16)
        layout.addWidget(game_card)
        layout.addWidget(card)
        layout.addWidget(pjsk_card)
        layout.addWidget(pgko_card)
        layout.addStretch(1)
        layout.addLayout(btns)

    def _pick_game_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择游戏数据目录（含 A001）")
        if d:
            self.game_root.setText(d)

    def _rescan_game_index(self) -> None:
        raw = self.game_root.text().strip()
        if not raw:
            fly_warning(self, "未设置", "请先填写或浏览选择游戏数据目录。")
            return
        root = Path(raw).expanduser()
        tool_raw = (self.compressonator.text() or "").strip()
        tool_path: Path | None = None
        if tool_raw:
            try:
                tp = Path(tool_raw).expanduser().resolve(strict=False)
                if tp.is_file():
                    tool_path = tp
            except OSError:
                tool_path = None
        if self._on_request_game_rescan is None:
            fly_warning(self, "不可用", "当前窗口未提供后台扫描入口。")
            return
        self._on_request_game_rescan(root, tool_path)

    def _pick_tool(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 compressonatorcli")
        if path:
            self.compressonator.setText(path)

    def _open_pjsk_hub(self) -> None:
        hub = PjskHubDialog(
            acus_root=self._acus_root,
            get_tool_path=self._get_tool_path,
            parent=self,
        )
        hub.exec()

    def _test_dds_convert(self) -> None:
        selected, ok = QInputDialog.getItem(
            self,
            "选择测试方式",
            "请选择要测试的转换逻辑：",
            ["内置 quicktex", "内置 Pillow(DXT5)", "compressonator CLI"],
            0,
            False,
        )
        if not ok:
            return

        test_png_size = (4, 4)
        with tempfile.TemporaryDirectory(prefix="chuni_dds_test_") as tmp:
            tmp_dir = Path(tmp)
            png = tmp_dir / "sample.png"
            dds_quick = tmp_dir / "quicktex.dds"
            dds_cli = tmp_dir / "compressonator.dds"

            try:
                from PIL import Image

                Image.new("RGBA", test_png_size, (255, 0, 255, 255)).save(png, "PNG")
            except Exception as e:
                fly_critical(self, "测试失败", f"无法生成测试图片：{e}")
                return

            if selected == "内置 quicktex":
                quick_ok = False
                quick_msg = ""
                if not quicktex_available():
                    quick_msg = "未检测到 quicktex（打包遗漏或依赖不可用）"
                else:
                    try:
                        encode_image_to_bc3_dds_quicktex(input_image=png, output_dds=dds_quick)
                        quick_ok = is_bc3_dds(dds_quick)
                        quick_msg = "可用（已成功生成 BC3 DDS）" if quick_ok else "输出存在但不是 BC3 DDS"
                    except Exception as e:
                        quick_msg = str(e)
                title = "quicktex 测试完成" if quick_ok else "quicktex 测试失败"
                text = f"DDS 转换自检结果：\n- 内置 quicktex：{'OK' if quick_ok else 'FAIL'}\n  {quick_msg}"
                if quick_ok:
                    fly_message(self, title, text)
                else:
                    fly_warning(self, title, text)
                return
            if selected == "内置 Pillow(DXT5)":
                pillow_ok = False
                pillow_msg = ""
                try:
                    from PIL import Image

                    Image.open(png).convert("RGBA").save(dds_quick, format="DDS", pixel_format="DXT5")
                    pillow_ok = is_bc3_dds(dds_quick)
                    pillow_msg = "可用（已成功生成 BC3 DDS）" if pillow_ok else "输出存在但不是 BC3 DDS"
                except Exception as e:
                    pillow_msg = str(e)
                title = "Pillow(DXT5) 测试完成" if pillow_ok else "Pillow(DXT5) 测试失败"
                text = f"DDS 转换自检结果：\n- 内置 Pillow(DXT5)：{'OK' if pillow_ok else 'FAIL'}\n  {pillow_msg}"
                if pillow_ok:
                    fly_message(self, title, text)
                else:
                    fly_warning(self, title, text)
                return

            cli_ok = False
            cli_msg = ""
            tool = self._resolve_tool_path_for_test()
            if tool is None:
                cli_msg = "未配置 compressonatorcli（且未检测到附带 CLI）"
            else:
                try:
                    validate_compressonator_tool(tool)
                    run_cmd([str(tool), "-fd", "BC3", str(png), str(dds_cli)])
                    cli_ok = is_bc3_dds(dds_cli)
                    cli_msg = f"可用（{tool}）" if cli_ok else f"执行成功但输出不是 BC3（{tool}）"
                except (DdsToolError, OSError) as e:
                    cli_msg = f"{tool}\n{e}"
            title = "compressonator CLI 测试完成" if cli_ok else "compressonator CLI 测试失败"
            text = f"DDS 转换自检结果：\n- compressonator CLI：{'OK' if cli_ok else 'FAIL'}\n  {cli_msg}"
            if cli_ok:
                fly_message(self, title, text)
            else:
                fly_warning(self, title, text)

    def _resolve_tool_path_for_test(self) -> Path | None:
        raw = (self.compressonator.text() or "").strip()
        if raw:
            try:
                p = Path(raw).expanduser().resolve(strict=False)
            except OSError:
                return None
            return p if p.is_file() else None
        return self._get_tool_path()

    def _on_save_clicked(self) -> None:
        lg = _settings_logger()
        lg.info("save_button_clicked")
        try:
            if self.apply():
                lg.info("save_button_accept")
                self.accept()
        except Exception:
            lg.exception("save_button_crash")
            fly_critical(self, "保存失败", "设置保存时发生未处理异常，请提供 settings_save.log。")

    def apply(self) -> bool:
        lg = _settings_logger()
        lg.info("apply_start")
        raw = self.compressonator.text().strip()
        if raw:
            p = Path(raw).expanduser()
            try:
                p = p.resolve(strict=False)
            except OSError:
                lg.warning("apply_reject_invalid_tool_path_unresolvable raw=%s", raw)
                fly_warning(self, "路径无效", "无法解析该路径，请检查拼写。")
                return False
            if not p.is_file():
                lg.warning("apply_reject_invalid_tool_path_not_file path=%s", p)
                fly_warning(
                    self,
                    "路径无效",
                    "DDS 工具必须指向 compressonatorcli 的「可执行文件」本体。\n"
                    "不要填「.」、不要选文件夹；请用「浏览…」选择实际程序文件。",
                )
                return False
        self._cfg.compressonatorcli_path = raw
        gr = self.game_root.text().strip()
        self._cfg.game_root = gr
        self._cfg.enable_pgko_ugc_experimental = bool(self.pgko_exp_checkbox.isChecked())
        self._cfg.save()
        lg.info("apply_done game_root=%s compressonator_set=%s", gr, bool(raw))
        return True
