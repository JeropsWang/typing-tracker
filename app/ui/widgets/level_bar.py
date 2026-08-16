"""酷炫等级进度条：渐变填充 + 扫光动画 + 分段刻度 + 星星点缀。"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

_RNG = random.Random(7)

DEFAULT_COLORS = ['#60a5fa', '#a78bfa', '#f472b6']


class LevelBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(20)
        self._progress = 0.0
        self._colors = list(DEFAULT_COLORS)
        self._glow = True
        self._t = 0.0
        self._stars = []        # [fx, fy, r, phase] 填充区固定小星
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ---------- 配置 ----------
    def set_progress(self, value: float) -> None:
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    def set_colors(self, colors) -> None:
        if isinstance(colors, list) and len(colors) >= 2:
            self._colors = [str(c) for c in colors]
        self.update()

    def set_glow(self, on: bool) -> None:
        self._glow = bool(on)

    def _tick(self) -> None:
        self._t += 0.033
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = h / 2.0

        # 背景槽
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(0, 0, w, h, r, r)

        fill_w = max(0.0, w * self._progress)
        if fill_w > 1:
            # 渐变填充
            grad = QLinearGradient(0, 0, w, 0)
            n = len(self._colors)
            for i, c in enumerate(self._colors):
                grad.setColorAt(i / max(1, n - 1), QColor(c))
            p.setBrush(grad)
            p.drawRoundedRect(0, 0, fill_w, h, r, r)

            # 扫光高光（在填充区内移动）
            if self._glow:
                shine_x = fill_w * (0.5 + 0.5 * math.sin(self._t * 1.6))
                sw = 26.0
                shine = QLinearGradient(shine_x - sw, 0, shine_x + sw, 0)
                shine.setColorAt(0, QColor(255, 255, 255, 0))
                shine.setColorAt(0.5, QColor(255, 255, 255, 130))
                shine.setColorAt(1, QColor(255, 255, 255, 0))
                p.setBrush(shine)
                p.drawRoundedRect(0, 0, fill_w, h, r, r)

            # 小星星点缀
            if not self._stars:
                self._stars = [[_RNG.uniform(0.06, 0.92), _RNG.uniform(0.18, 0.82),
                                _RNG.uniform(0.8, 1.6), _RNG.uniform(0, 6.283)]
                               for _ in range(4)]
            for fx, fy, sr, phase in self._stars:
                if fx * w > fill_w:
                    continue
                a = 0.35 + 0.55 * (0.5 + 0.5 * math.sin(self._t * 2.0 + phase))
                col = QColor(255, 255, 255)
                col.setAlphaF(a)
                p.setBrush(col)
                p.drawEllipse(QPointF(fx * w, fy * h), sr, sr)

        # 分段刻度
        p.setPen(QPen(QColor(255, 255, 255, 46), 1))
        for i in range(1, 10):
            x = w * i / 10.0
            p.drawLine(QPointF(x, h * 0.25), QPointF(x, h * 0.75))
        p.end()
