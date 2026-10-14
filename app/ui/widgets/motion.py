"""有限时长绘制层动效；关闭时落在稳定终态，不改变控件几何。"""
import math
from PySide6.QtCore import QEasingCurve, QObject, QVariantAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget
from ..palette import P
from .scrapbook import star_path


class MotionValue(QObject):
    """Qt 主线程的可中断数值过渡，关闭动效时直接采用目标值。"""
    def __init__(self, parent, on_change, duration=180):
        """建立轻量控件过渡动画组件的依赖与初始状态。"""
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
        """记录当前动画值并调用展示回调，不改变业务数据。"""
        self.value = float(value)
        self._on_change(self.value)

    def animate_to(self, value):
        """从当前可见数值过渡到目标，关闭动效或已达目标时直接完成。"""
        self.animation.stop()
        self._target = float(value)
        if not self._enabled or self.value == self._target:
            self._set(self._target)
            return
        self.animation.setStartValue(self.value)
        self.animation.setEndValue(self._target)
        self.animation.start()

    def set_enabled(self, enabled):
        """切换动画资格，禁用时停止过渡并落到目标值。"""
        self._enabled = bool(enabled)
        if not self._enabled:
            self.stop()

    def stop(self):
        """停止现有动画并确定为最后目标，不遗留半途中间状态。"""
        self.animation.stop()
        self._set(self._target)


class FeedbackSpark(QWidget):
    """不响应输入的短暂反馈星形装饰，遵守减弱动态效果开关。"""
    def __init__(self, parent=None):
        """建立轻量控件过渡动画组件的依赖与初始状态。"""
        super().__init__(parent)
        self.setFixedSize(44, 44)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.NoFocus)
        self.motion = MotionValue(self, lambda _: self.update(), 360)

    def set_motion_enabled(self, enabled):
        """把动效开关同步给反馈星的数值过渡。"""
        self.motion.set_enabled(enabled)

    def flash(self):
        """从零重新触发一次短反馈脉冲，不生成业务奖励。"""
        self.motion.stop()
        self.motion._set(0)
        self.motion.animate_to(1)

    def paintEvent(self, event):
        """在 Qt 主线程按当前状态绘制轻量控件过渡动画的可见内容，不在绘制回调执行业务提交。"""
        pulse = math.sin(math.pi * self.motion.value)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(P.accent_ochre))
        painter.drawPath(star_path(21, 22, 12 + pulse * 4))
        painter.setBrush(QColor(P.primary))
        painter.drawPath(star_path(35, 9, 3 + pulse))
