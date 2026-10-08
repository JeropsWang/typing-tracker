"""背景层：插画（cover 裁切与角色局部待机）+ 星空粒子。

静态插画来自交付资源 assets/background.png（只含插画，不含界面文字控件），
星空仍由主题 effects 配置，两者层级由主窗口装配：插画在下、星星在上。
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .character_motion import SarianaMotion

_RNG = random.Random(42)


class BackdropImage(QWidget):
    """背景保持居中 cover；角色动效由独立控制器局部绘制。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._source: Path | None = None
        self._pixmap: QPixmap | None = None
        self._cover_cache: QPixmap | None = None
        self._motion = SarianaMotion(self)
        self._motion.changed.connect(self.update)
        self._radius = 16
        self.setVisible(False)

    def set_source(self, path, motion_path=None) -> None:
        """设置插画文件；文件缺失时静默隐藏（其它主题不依赖该资源）。"""
        path = Path(path) if path else None
        if path is not None and not path.exists():
            path = None
        self._source = path
        self._pixmap = QPixmap(str(path)) if path is not None else None
        if self._pixmap is not None and self._pixmap.isNull():
            self._pixmap = None
        self._cover_cache = None
        self._motion.configure(path, self._pixmap, motion_path)
        self.setVisible(self._pixmap is not None)
        self.update()

    def has_artwork(self) -> bool:
        return self._pixmap is not None

    def set_motion_enabled(self, enabled: bool) -> None:
        self._motion.set_enabled(enabled)

    def set_corner_radius(self, radius: int) -> None:
        self._radius = int(radius)
        self.update()

    def paintEvent(self, event) -> None:
        if self._pixmap is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        painter.setClipPath(clip)
        if self._cover_cache is None:
            self._cover_cache = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        scaled = self._cover_cache
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.save()
        painter.translate(x, y)
        painter.scale(scaled.width() / self._pixmap.width(),
                      scaled.height() / self._pixmap.height())
        self._motion.paint(painter)
        painter.restore()
        painter.end()

    def resizeEvent(self, event) -> None:
        self._cover_cache = None
        self.update()
        super().resizeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._motion.set_visible(True)

    def hideEvent(self, event) -> None:
        self._motion.set_visible(False)
        super().hideEvent(event)


class StarField(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._enabled = False
        self._paused = False
        self._color = QColor('#ffd700')
        self._density = 0.0012
        self._speed = 1.0
        self._sparkle = True
        self._radius = 16          # 与壳层圆角一致（主窗口会同步）
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
        if self._enabled and not self._paused and not self._timer.isActive():
            self._timer.start(33)
        elif not self._enabled or self._paused:
            self._timer.stop()
        self.update()

    def set_corner_radius(self, radius: int) -> None:
        """圆角跟随壳层（最大化时置 0），避免星星画到透明角落。"""
        radius = int(radius)
        if radius != self._radius:
            self._radius = radius
            self.update()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused or not self._enabled:
            self._timer.stop()
        else:
            self._timer.start(33)

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
        if self._radius > 0:
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
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
