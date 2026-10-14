"""Small painted controls with native Qt button and focus semantics."""
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QLinearGradient
from PySide6.QtWidgets import QToolButton, QWidget
from ..assets.icons import icon
from .agent_visuals import colors, sparkle


class OrbitButton(QToolButton):
    """Qt 主线程绘制的圆形工具按钮，保留原生焦点、点击和无障碍语义。"""
    def __init__(self, caption, tool, tone, parent):
        """设置按钮标题/图标/色调，创建仅用于悬停反馈的短过渡动画。"""
        super().__init__(parent)
        self.caption, self.tool, self.tone = caption, tool, tone
        self.setFixedSize(64, 64)
        self.setFocusPolicy(Qt.StrongFocus)
        self.motion = True
        self._hover = 0.
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(180)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._frame)

    def _frame(self, value):
        """接收悬停动画值并请求重绘，不改变工具功能或业务状态。"""
        self._hover = value
        self.update()

    def _transition(self, value):
        """从当前悬停程度过渡到目标值，减弱动态效果时直接设置终值。"""
        self._animation.stop()
        if not self.motion:
            self._frame(value)
            return
        self._animation.setStartValue(self._hover)
        self._animation.setEndValue(value)
        self._animation.start()

    def enterEvent(self, event):
        """按钮可用时启动进入高亮，并继续交给原生按钮处理鼠标事件。"""
        if self.isEnabled():
            self._transition(1.)
        super().enterEvent(event)

    def leaveEvent(self, event):
        """退出悬停时恢复普通高亮，保留原生事件处理。"""
        self._transition(0.)
        super().leaveEvent(event)

    def paintEvent(self, event):
        """按按钮尺寸绘制半透明圆面、工具图标、标题及焦点/悬停装饰。"""
        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width() / 64, self.height() / 64)
        tone = QColor(getattr(c, self.tone))
        tone.setAlpha(240 if self.isDown() else 195 + round(45 * self._hover))
        grad = QLinearGradient(0, 0, 55, 64)
        sheen = QColor(c.surface)
        sheen.setAlpha(220)
        grad.setColorAt(0, sheen)
        grad.setColorAt(1, tone)
        p.setPen(QPen(QColor(c.accent if self.isEnabled() else c.line), 1.4))
        p.setBrush(grad)
        p.drawEllipse(QRectF(3, 3, 58, 58))
        p.setPen(QPen(QColor(c.surface), 2.2))
        p.drawArc(QRectF(7, 7, 50, 50), 45 * 16, 90 * 16)
        tint = c.accent if self.isEnabled() else c.muted
        icon(self.tool, tint, 26).paint(p, 19, 10, 26, 26)
        p.setPen(QColor(tint))
        p.setFont(QFont('Microsoft YaHei UI', 9))
        p.drawText(QRectF(2, 38, 60, 19), Qt.AlignCenter, self.caption)
        if self.hasFocus():
            p.setPen(QPen(QColor(c.accent), 2, Qt.DotLine))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QRectF(0, 0, 63, 63))
        if self._hover > .1:
            sparkle(p, QPointF(53, 9), 4 + self._hover, tint)


class AgentJourney(QWidget):
    """Actual graph stages; the activity pulse never implies a percent complete."""
    def __init__(self):
        """创建三阶段指示器和低频视觉脉冲，初始不代表任何完成百分比。"""
        super().__init__()
        self.setFixedHeight(32)
        self.stage, self.busy, self.motion = 0, False, True
        self._phase = 0
        self._timer = QTimer(self)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._pulse)
        self.setAccessibleName('搜索进度')

    def _pulse(self):
        """推进当前阶段的视觉脉冲并重绘，仅供等待反馈。"""
        self._phase = (self._phase + 1) % 3
        self.update()

    def set_stage(self, stage, busy):
        """更新真实阶段与忙碌状态、无障碍描述，并重新决定是否启动动画。"""
        self.stage, self.busy = stage, busy
        self.setAccessibleDescription(('寻找线索', '对照来源', '整理给你')[min(stage, 2)] if busy else '情报已整理')
        self._sync_timer()
        self.update()

    def set_motion_enabled(self, enabled):
        """启停阶段动效，关闭时保留静态阶段信息。"""
        self.motion = bool(enabled)
        self._sync_timer()

    def _sync_timer(self):
        """仅在忙碌、允许动效且控件可见时运行脉冲计时器。"""
        self._timer.start() if self.busy and self.motion and self.isVisible() else self._timer.stop()

    def showEvent(self, event):
        """控件显示后按当前状态恢复脉冲，不重置任务阶段。"""
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        """控件隐藏时停止脉冲，避免后台无效重绘。"""
        self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        """绘制找线索/读来源/写手信三阶段标签和当前活动亮点。"""
        c = colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont('Microsoft YaHei UI', 8))
        unit = self.width() / 3
        for i, text in enumerate(('找线索', '读来源', '写手信')):
            x = i * unit + 6
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c.accent if i <= self.stage else c.line))
            radius = 3 + (self._phase * .6 if self.busy and i == self.stage else 0)
            p.drawEllipse(QPointF(x, 16), radius, radius)
            p.setPen(QColor(c.ink if i <= self.stage else c.muted))
            p.drawText(QRectF(x + 11, 4, unit - 12, 24), Qt.AlignVCenter, text)
