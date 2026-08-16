"""成就/升级小弹窗：圆角卡片 + 位置滑入动画 + 星星装饰 + 自动消失。

kind 决定图标前缀：achievement 🏆 / level 🎉 / encourage 🚀 / star ✨
注意：动画只用位置移动（QPropertyAnimation on pos），不使用
QGraphicsOpacityEffect——无边框透明窗口上效果残留会导致整体渲染偏移。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

KIND_ICON = {
    'achievement': '🏆',
    'level': '🎉',
    'encourage': '🚀',
    'milestone': '🎁',
    'star': '✨',
}

KIND_ACCENT = {
    'achievement': '#f59e0b',
    'level': '#a78bfa',
    'encourage': '#10b981',
    'milestone': '#f472b6',
    'star': '#60a5fa',
}

SHOW_MS = 3200


class ToastPopup(QFrame):
    def __init__(self, parent, title: str, msg: str, kind: str = 'star',
                 accent: str = None, dark: bool = True):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        accent = accent or KIND_ACCENT.get(kind, '#60a5fa')
        icon = KIND_ICON.get(kind, '✨')

        if dark:
            bg = 'rgba(20, 24, 40, 235)'
            fg = '#f3f4f6'
            sub = '#cbd5e1'
        else:
            bg = 'rgba(255, 255, 255, 245)'
            fg = '#111827'
            sub = '#6b7280'

        self.setStyleSheet(
            f'QFrame {{ background: {bg}; border: 1px solid {accent};'
            f' border-radius: 14px; }}'
            f'QLabel {{ background: transparent; border: none; }}'
            f'#toast_title {{ color: {fg}; font-size: 15px; font-weight: 700; }}'
            f'#toast_msg {{ color: {sub}; font-size: 12px; }}'
            f'#toast_stars {{ color: {accent}; font-size: 11px; }}')

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 10)
        row = QHBoxLayout()
        icon_lab = QLabel(icon)
        icon_lab.setStyleSheet('font-size: 20px;')
        row.addWidget(icon_lab)
        col = QVBoxLayout()
        title_lab = QLabel(title)
        title_lab.setObjectName('toast_title')
        col.addWidget(title_lab)
        msg_lab = QLabel(msg)
        msg_lab.setObjectName('toast_msg')
        msg_lab.setWordWrap(True)
        col.addWidget(msg_lab)
        row.addLayout(col, 1)
        root.addLayout(row)
        stars = QLabel('✦ ✧ ★ ✦ ✧')
        stars.setObjectName('toast_stars')
        stars.setAlignment(Qt.AlignRight)
        root.addWidget(stars)

        self.adjustSize()
        self.setFixedWidth(min(360, max(240, self.width())))
        self.adjustSize()

        self._anim = QPropertyAnimation(self, b'pos', self)
        self._anim.setDuration(280)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)
        self._hide_timer.start(SHOW_MS)

    def start_animation(self, target: QPoint) -> None:
        """从下方滑入到目标位置（纯位置动画）。"""
        self.move(target.x(), target.y() + 26)
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(target)
        self._anim.start()

    def _fade_out(self) -> None:
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(self.pos() + QPoint(0, 22))
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()
