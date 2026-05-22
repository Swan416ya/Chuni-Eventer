"""Fluent ScrollArea 与主窗口内容区背景对齐。"""

from __future__ import annotations

from PyQt6.QtWidgets import QFrame, QWidget

from qfluentwidgets import ScrollArea


def apply_fluent_transparent_scroll(scroll: ScrollArea) -> None:
    """去掉 QScrollArea 默认的灰底（如 #f3f3f3），与 MSFluentWindow 主体同色。"""
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
    scroll.viewport().setStyleSheet("background: transparent;")
    inner = scroll.widget()
    if inner is not None:
        inner.setStyleSheet("background: transparent;")


def apply_fluent_transparent_panel(widget: QWidget) -> None:
    """页面根容器不自行填色，继承 Fluent 窗口背景。"""
    widget.setAutoFillBackground(False)
