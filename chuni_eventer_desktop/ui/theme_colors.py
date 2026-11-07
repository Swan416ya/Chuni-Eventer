"""浅色 / 深色双主题的中性文字颜色。

qfluentwidgets 只切换自己 QSS 里的颜色，各处用 ``setStyleSheet`` 写死的中性灰、
警告橙不会跟着主题走：深色弹窗里灰字发暗、橙字偏暗红。这里给统一的双值。

对 ``FluentLabelBase``（BodyLabel / CaptionLabel 等）走它自带的
``setTextColor(light, dark)``：标签在主题切换时会用这两个颜色重新注册 QSS，
比 ``setCustomStyleSheet`` 更可靠（标签每次换主题都会重写自己的 custom QSS）。
其他控件退回 ``setCustomStyleSheet``。

需要单独取色（例如塞进富文本 HTML）时用 ``muted_text_color()`` /
``warn_text_color()``。
"""

from __future__ import annotations

from typing import Any

from qfluentwidgets import FluentLabelBase, isDarkTheme, setCustomStyleSheet

# 次级说明文字（浅色 #6B7280 与深色 #9CA3AF 在各自底色上的观感最接近）
MUTED_LIGHT = "#6B7280"
MUTED_DARK = "#9CA3AF"
# 提示 / 警告文字（沿用 pjsk_hub_dialog 已有的深色琥珀）
WARN_LIGHT = "#B45309"
WARN_DARK = "#FBBF24"


def muted_text_color() -> str:
    """次级说明文字颜色。"""
    return MUTED_DARK if isDarkTheme() else MUTED_LIGHT


def warn_text_color() -> str:
    """提示 / 警告文字颜色。"""
    return WARN_DARK if isDarkTheme() else WARN_LIGHT


def _apply_theme_text_color(
    widget: Any,
    light: str,
    dark: str,
    *,
    font_size: int | None = None,
) -> None:
    if font_size:
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)

    if isinstance(widget, FluentLabelBase):
        widget.setTextColor(light, dark)
        return

    suffix = f"font-size:{font_size}px;" if font_size else ""
    setCustomStyleSheet(
        widget,
        f"color:{light};{suffix}",
        f"color:{dark};{suffix}",
    )


def apply_muted_style(widget: Any, *, font_size: int | None = None) -> None:
    """把控件文字设为次级说明色（随主题切换）。"""
    _apply_theme_text_color(widget, MUTED_LIGHT, MUTED_DARK, font_size=font_size)


def apply_warn_style(widget: Any, *, font_size: int | None = None) -> None:
    """把控件文字设为提示 / 警告色（随主题切换）。"""
    _apply_theme_text_color(widget, WARN_LIGHT, WARN_DARK, font_size=font_size)
