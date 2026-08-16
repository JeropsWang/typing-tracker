"""星空粒子背景：QPainter 程序化绘制 + 闪烁动画。

不依赖外部图片素材（无版权风险），颜色/密度/速度由主题 effects 配置，
可随主题切换动态变化。
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

_RNG = random.Random(42)


class StarField(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._enabled = False
        self._color = QColor('#ffd700')
        self._density = 0.0012
        self._speed = 1.0
        self._sparkle = True
        self._stars = []        # [x, y, r, phase, speed]
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ---------- 配置（主题 effects） ----------
    def configure(self, effects=None) -> None:
        stars = (effects or {}).get('stars') or {}
        self._enabled = bool(stars.get('enabled', False))
        self._color = QColor(stars.get('color', '#ffd700'))
        self._density = float(stars.get('density', 0.0012))
        self._speed = float(stars.get('speed', 1.0))
        self._sparkle = bool(stars.get('sparkle', True))
        self._reseed()
        self.setVisible(self._enabled)
        # 星星禁用时停掉 30fps 定时器（避免托盘隐藏时空转唤醒）
        if self._enabled and not self._timer.isActive():
            self._timer.start(33)
        elif not self._enabled:
            self._timer.stop()
        self.update()

    # ---------- 粒子 ----------
    def _reseed(self) -> None:
        if not self._enabled:
            self._stars = []
            return
        w, h = self.width(), self.height()
        n = min(400, int(w * h * self._density))
        self._stars = [[_RNG.uniform(0, w), _RNG.uniform(0, h),
                        _RNG.uniform(0.7, 2.3), _RNG.uniform(0, 6.283),
                        _RNG.uniform(0.8, 2.0)] for _ in range(n)]

    def _tick(self) -> None:
        self._t += 0.033 * self._speed
        self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:
        if not self._enabled or not self._stars:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 圆角裁剪：与壳层圆角一致，避免星星画到透明角落
        clip = QPainterPath()
        clip.addRoundedRect(self.rect(), 16, 16)
        p.setClipPath(clip)
        for x, y, r, phase, sp in self._stars:
            if self._sparkle:
                a = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(self._t * sp + phase))
            else:
                a = 0.75
            col = QColor(self._color)
            col.setAlphaF(a)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(x, y), r, r)
            if r >= 1.9:        # 大星星加十字光芒
                pen = QPen(col, 0.8)
                p.setPen(pen)
                p.drawLine(QPointF(x - r * 2.4, y), QPointF(x + r * 2.4, y))
                p.drawLine(QPointF(x, y - r * 2.4), QPointF(x, y + r * 2.4))
        p.end()

    def resizeEvent(self, event) -> None:
        self._reseed()
        super().resizeEvent(event)
