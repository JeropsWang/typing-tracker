"""手稿装饰容器：纸张错位、胶带与星轨，交互内容由正常布局管理。"""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame
from ..palette import P
from .visual_tokens import mix


def star_path(x, y, size):
    path = QPainterPath()
    for i in range(8):
        angle = i * math.pi / 4 - math.pi / 2
        radius = size if i % 2 == 0 else size * .27
        point = QPointF(x + math.cos(angle) * radius, y + math.sin(angle) * radius)
        path.moveTo(point) if i == 0 else path.lineTo(point)
    path.closeSubpath()
    return path


class ScrapbookCard(QFrame):
    def __init__(self, tone='rose', parent=None):
        super().__init__(parent)
        self.tone = tone
        self.setStyleSheet('QFrame { background: transparent; border: none; }')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        tint = P.accent_rose if self.tone == 'rose' else P.primary
        p.setPen(Qt.NoPen)
        backing = QColor(tint); backing.setAlpha(110); p.setBrush(backing)
        path = QPainterPath(); path.moveTo(9, 12); path.lineTo(w - 4, 2)
        path.lineTo(w - 10, h - 6); path.lineTo(2, h - 14); path.closeSubpath()
        p.drawPath(path)
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0, QColor(P.paper))
        grad.setColorAt(1, QColor(mix(tint, P.paper, .32)))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(7, 7, w - 19, h - 19), 20, 20)
        p.setPen(QPen(QColor(tint), 1.5, Qt.DashLine))
        p.drawArc(QRectF(w - 112, -35, 130, 118), 160 * 16, 150 * 16)
        p.setPen(Qt.NoPen); p.setBrush(QColor(P.accent_ochre))
        p.drawPath(star_path(w - 27, 23, 9))
        p.setBrush(QColor(P.primary))
        p.drawPath(star_path(w - 47, 35, 4))
        p.setBrush(backing)
        p.save(); p.translate(38, 9); p.rotate(-8)
        p.drawRect(QRectF(-20, -3, 48, 10)); p.restore()
