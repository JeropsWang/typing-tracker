"""固定窗口标题栏：拖动、最小化与关闭，不开放最大化。

主题联动：apply_theme() 由主窗口在主题切换时调用。

去硬边（配方 `render_design.py` 第 108 行）：设计稿的标题栏是**与画布同色的平铺色块**
（`box(p, [0,0,width,42], '#232430', 0)`，圆角 0、无描边）。旧实现画了一条
`border-bottom: 1px solid`，深色主题下就是那条“碍眼的黑色边框”，已去掉。
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
        # 配方第 108 行：标题栏高 42，与 spec.json 的 titlebarHeight 一致
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
        self._btn_close = self._ctrl_btn('close', '关闭')
        self._btn_close.clicked.connect(self._window.close)
        lay.addWidget(self._btn_min)
        lay.addWidget(self._btn_close)

        self.apply_theme()

    # ---------- 控制按钮 ----------
    def _ctrl_btn(self, icon_name: str, tip: str) -> QPushButton:
        btn = QPushButton(self)
        btn.setIcon(svg_icon(icon_name, P.surface_muted, 14))
        btn.setFixedSize(34, 30)
        btn.setToolTip(tip)
        btn.setAccessibleName(tip)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            'QPushButton { background: transparent; border: none; border-radius: 7px; }'
            'QPushButton:hover { background: rgba(255,255,255,40); }')
        return btn

    def set_corner_radius(self, radius: int) -> None:
        """标题栏圆角与固定窗口的壳层一致。"""
        if radius != getattr(self, '_corner_radius', None):
            self._corner_radius = radius
            self.apply_theme()

    # ---------- 主题 ----------
    def apply_theme(self):
        radius = getattr(self, '_corner_radius', 16)
        if P.dark:
            # 夜色手稿：标题栏与画布**完全同色**，无描边（配方第 108 行）
            bg = P.canvas
            title_color = P.surface_muted
            icon_color = P.surface_muted
            hover = 'rgba(255,255,255,40)'
        else:
            # 浅色主题同样去掉分隔线：用与画布同色的平铺底，保留圆角
            bg = P.canvas
            title_color = P.text
            icon_color = P.muted
            hover = 'rgba(0,0,0,18)'
        # 关键：不再有 border-bottom（旧实现 `border-bottom: 1px solid {border}`
        # 就是深色主题下那条碍眼的黑边）
        self.setStyleSheet(
            f'QFrame#titleBar {{ background: {bg}; border: none;'
            f' border-top-left-radius: {radius}px;'
            f' border-top-right-radius: {radius}px; }}')
        self._title_label.setStyleSheet(
            f'font-size:13px; font-weight:600; color:{title_color};')
        self._btn_min.setIcon(svg_icon('min', icon_color, 14))
        self._btn_close.setIcon(svg_icon('close', icon_color, 14))
        close_hover = ('rgba(239,68,68,200)' if P.dark else 'rgba(239,68,68,230)')
        for btn in (self._btn_min,):
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
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
