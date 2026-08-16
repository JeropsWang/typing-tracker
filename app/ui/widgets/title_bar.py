"""自定义标题栏：无边框窗口的渐变标题层 + 拖动 + 最小化/最大化/关闭。

主题联动：apply_theme() 由主窗口在主题切换时调用。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from ..assets.icons import icon as svg_icon
from ..palette import P


class TitleBar(QFrame):
    def __init__(self, window, title: str, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_offset = None
        self.setObjectName('titleBar')
        self.setFixedHeight(42)
        self.setMouseTracking(True)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(8)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet('font-size:13px; font-weight:700;')
        lay.addWidget(self._title_label)
        lay.addStretch(1)

        self._btn_min = self._ctrl_btn('min', '最小化')
        self._btn_min.clicked.connect(self._window.showMinimized)
        self._btn_max = self._ctrl_btn('max', '最大化')
        self._btn_max.clicked.connect(self._toggle_max)
        self._btn_close = self._ctrl_btn('close', '关闭')
        self._btn_close.clicked.connect(self._window.close)
        lay.addWidget(self._btn_min)
        lay.addWidget(self._btn_max)
        lay.addWidget(self._btn_close)

        self.apply_theme()

    # ---------- 控制按钮 ----------
    def _ctrl_btn(self, icon_name: str, tip: str) -> QPushButton:
        btn = QPushButton(self)
        btn.setIcon(svg_icon(icon_name, '#94A3B8', 14))
        btn.setFixedSize(34, 30)
        btn.setToolTip(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            'QPushButton { background: transparent; border: none; border-radius: 7px; }'
            'QPushButton:hover { background: rgba(255,255,255,40); }')
        return btn

    def _toggle_max(self):
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()
        self._update_max_icon()

    def _update_max_icon(self):
        name = 'restore' if self._window.isMaximized() else 'max'
        color = '#CBD5E1' if P.dark else '#475569'
        self._btn_max.setIcon(svg_icon(name, color, 14))

    # ---------- 主题 ----------
    def apply_theme(self):
        if P.dark:
            bg = ('qlineargradient(x1:0, y1:0, x2:1, y2:0,'
                  ' stop:0 rgba(30,41,59,235), stop:1 rgba(46,36,99,235))')
            title_color = '#E2E8F0'
            icon_color = '#CBD5E1'
            hover = 'rgba(255,255,255,40)'
        else:
            bg = ('qlineargradient(x1:0, y1:0, x2:1, y2:0,'
                  ' stop:0 rgba(255,255,255,242), stop:1 rgba(238,242,255,242))')
            title_color = '#111827'
            icon_color = '#475569'
            hover = 'rgba(99,102,241,30)'
        self.setStyleSheet(
            f'QFrame#titleBar {{ background: {bg};'
            f' border-bottom: 1px solid {"#334155" if P.dark else "#E5E7EB"}; }}')
        self._title_label.setStyleSheet(
            f'font-size:13px; font-weight:700; color:{title_color};')
        self._btn_min.setIcon(svg_icon('min', icon_color, 14))
        self._btn_max.setIcon(svg_icon('max', icon_color, 14))
        self._btn_close.setIcon(svg_icon('close', icon_color, 14))
        close_hover = ('rgba(239,68,68,200)' if P.dark else 'rgba(239,68,68,230)')
        for btn in (self._btn_min, self._btn_max):
            btn.setStyleSheet(
                f'QPushButton {{ background: transparent; border: none;'
                f' border-radius: 7px; }}'
                f'QPushButton:hover {{ background: {hover}; }}')
        self._btn_close.setStyleSheet(
            f'QPushButton {{ background: transparent; border: none;'
            f' border-radius: 7px; }}'
            f'QPushButton:hover {{ background: {close_hover}; }}'
            f'QPushButton:hover {{ color: white; }}')

    # ---------- 拖动 ----------
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self._window.frameGeometry().topLeft())
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            if not self._window.isMaximized():
                self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._toggle_max()
