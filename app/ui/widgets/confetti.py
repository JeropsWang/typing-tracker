"""彩带庆祝特效：结算分数达到档位时飘落彩色粒子（金色/多彩两档）。"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

_RNG = random.Random(2026)

TIER_COLORS = {
    # 100 万档：金色庆祝
    1: ['#FFD54F', '#FFC107', '#FFB300', '#FFE082', '#FFF59D'],
    # 200 万档：多彩狂欢
    2: ['#FFD54F', '#FF9ECF', '#4FC3F7', '#B39DDB', '#66BB6A', '#FF8A80'],
}


class ConfettiOverlay(QWidget):
    """覆盖层：粒子从顶部飘落 + 旋转。start(tier) 后自动结束并隐藏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._particles = []
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def start(self, tier: int = 1, duration: float = 2.2) -> None:
        """tier 1 = 金色（≥100万），tier 2 = 多彩（≥200万）。"""
        colors = TIER_COLORS.get(tier, TIER_COLORS[1])
        n = 46 if tier == 1 else 72
        w = max(self.width(), 600)
        self._particles = [[
            _RNG.uniform(0, w), _RNG.uniform(-40, -8),
            _RNG.uniform(2.5, 5.0), _RNG.uniform(0.8, 2.0),
            _RNG.uniform(0, 6.283), _RNG.choice(colors),
            _RNG.uniform(4, 9)] for _ in range(n)]
        self._t = 0.0
        self._duration = duration
        self.show()
        self.raise_()
        self._timer.start(30)

    def _tick(self) -> None:
        self._t += 0.03
        h = max(self.height(), 400)
        for p in self._particles:
            p[1] += p[3]                    # 下落
            p[4] += 0.12                    # 旋转
        if self._t >= self._duration:
            self.stop()
            return
        self.update()

    def stop(self):
        self._timer.stop()
        self._particles.clear()
        self.hide()

    def paintEvent(self, event) -> None:
        if not self._particles:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for x, y, vy, vx, rot, color, size in self._particles:
            p.save()
            p.translate(x, y)
            p.rotate(math.degrees(rot))
            p.setBrush(QColor(color))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(-size / 2, -size / 4, size, size / 2),
                              size / 4, size / 4)
            p.restore()
        p.end()
