"""有限时长绘制层动效；关闭时落在稳定终态，不改变控件几何。"""
import math
from PySide6.QtCore import QEasingCurve, QObject, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget
from ..palette import P
from .scrapbook import star_path


class MotionValue(QObject):
    def __init__(self, parent, on_change, duration=180):
        super().__init__(parent)
        self.value = 0.0
        self._target = 0.0
        self._enabled = True
        self._on_change = on_change
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(duration)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        self.animation.valueChanged.connect(self._set)

    def _set(self, value):
        self.value = float(value)
        self._on_change(self.value)

    def animate_to(self, value):
        self.animation.stop()
        self._target = float(value)
        if not self._enabled or self.value == self._target:
            self._set(self._target)
            return
        self.animation.setStartValue(self.value)
        self.animation.setEndValue(self._target)
        self.animation.start()

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        if not self._enabled:
            self.stop()

    def stop(self):
        self.animation.stop()
        self._set(self._target)


class FeedbackSpark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.motion = MotionValue(self, lambda _: self.update(), 360)

    def set_motion_enabled(self, enabled):
        self.motion.set_enabled(enabled)

    def flash(self):
        self.motion.stop()
        self.motion._set(0)
        self.motion.animate_to(1)

    def paintEvent(self, event):
        pulse = math.sin(math.pi * self.motion.value)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(P.accent_ochre))
        painter.drawPath(star_path(21, 22, 12 + pulse * 4))
        painter.setBrush(QColor(P.primary))
        painter.drawPath(star_path(35, 9, 3 + pulse))
