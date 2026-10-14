"""Original vector artwork for the companion's configuration workspace."""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QWidget
from ..assets.icons import icon
from .agent_visuals import colors, sparkle


def translucent(value, alpha):
    """复制颜色并设置 alpha 透明度，供静态背景层绘制使用。"""
    color = QColor(value)
    color.setAlpha(alpha)
    return color


def polygon(points):
    """把二维坐标列表转换为 Qt 浮点多边形。"""
    return QPolygonF([QPointF(x, y) for x, y in points])


def paint_workspace(widget, painter):
    """Decorative layers stay behind controls and have no hit regions or timers."""
    c = widget.section_palette
    w, h = widget.width(), widget.height()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    # Broad angled fragments, rather than another full-width rectangular banner.
    painter.setBrush(translucent(c.lavender, 235))
    painter.drawPolygon(polygon([(-20, -10), (258, -10), (300, 36), (235, 108),
                                 (8, 122), (-20, 66)]))
    painter.setBrush(translucent(c.blue, 235))
    painter.drawPolygon(polygon([(w - 288, 7), (w - 130, 7), (w - 80, 61),
                                 (w - 238, 138), (w - 315, 76)]))
    painter.setBrush(QColor(c.coral))
    painter.drawPolygon(polygon([(-18, h - 94), (114, h - 106), (179, h - 47),
                                 (132, h + 8), (-18, h + 8)]))
    painter.setPen(QPen(translucent(c.accent, 80), 1))
    painter.drawLine(QPointF(12, 16), QPointF(12, 111))
    painter.drawLine(QPointF(12, 16), QPointF(43, 16))
    painter.drawLine(QPointF(w - 15, h - 90), QPointF(w - 15, h - 19))
    painter.drawLine(QPointF(w - 52, h - 19), QPointF(w - 15, h - 19))
    if w >= 700:
        painter.save()
        painter.setClipRect(QRectF(w - 255, 122, 235, 127))
        painter.setPen(translucent(c.accent, 42))
        painter.setFont(QFont('Bahnschrift', 145, QFont.Bold))
        painter.drawText(QRectF(w - 250, 94, 245, 190), Qt.AlignRight, 'S')
        painter.restore()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(c.accent))
        painter.drawPolygon(polygon([(w - 30, 115), (w - 16, 102), (w - 16, 130)]))
    # Hatch, constellation marks and cutout discs carry the same section colour.
    for i in range(7):
        x = w - 132 + i * 10
        painter.drawLine(QPointF(x, 15), QPointF(x + 22, 39))
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(translucent(c.accent, 95), 1.5, Qt.DashLine))
    painter.drawEllipse(QRectF(w - 146, 130, 116, 116))
    painter.setPen(QPen(translucent(c.accent, 140), 1.5))
    painter.drawEllipse(QRectF(w - 120, 154, 64, 64))
    sparkle(painter, QPointF(w - 53, 166), 21, c.accent)
    sparkle(painter, QPointF(w - 138, 214), 8, c.accent)
    painter.setPen(QPen(translucent(c.accent, 110), 1))
    for row in range(4):
        for col in range(5):
            x, y = w - 72 + col * 10, h - 87 + row * 10
            painter.drawLine(QPointF(x - 2, y), QPointF(x + 2, y))
            painter.drawLine(QPointF(x, y - 2), QPointF(x, y + 2))
    # Small barcode-like marks add rhythm without carrying configuration data.
    painter.setPen(QPen(translucent(c.accent, 110), 1))
    for i, length in enumerate((16, 8, 20, 12, 16, 6, 18)):
        painter.drawLine(QPointF(18 + i * 4, h - 92), QPointF(18 + i * 4, h - 92 + length))


class SettingsEmblem(QWidget):
    """The user's active companion is a visual part of its own configuration."""
    def __init__(self, portrait=None):
        """接收现有头像图标并固定装饰区域，禁用鼠标命中。"""
        super().__init__()
        self.portrait = portrait
        self.setFixedSize(104, 100)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        """跟随章节色绘制多边形衬纸、头像及星形装饰，无头像时使用工具图标。"""
        c = getattr(self.window(), 'section_palette', colors())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(QPen(QColor(c.line), 1))
        p.setBrush(QColor(c.blue))
        p.drawPolygon(polygon([(8, 10), (86, 2), (100, 27), (84, 91), (20, 96), (0, 65)]))
        p.setPen(QPen(QColor(c.accent), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(7, 5, 86, 86))
        if self.portrait is not None:
            self.portrait.paint(p, 8, 0, 88, 94)
        else:
            icon('agent-search', c.accent, 48).paint(p, 28, 22, 48, 48)
        sparkle(p, QPointF(92, 14), 8, c.accent)
        sparkle(p, QPointF(11, 83), 5, c.accent)


class SettingsSheet(QFrame):
    """Cut corners, torn edge, folded tab and a displaced backing sheet."""
    def __init__(self, tone=None):
        """记录纸面色调并标记为自绘面板，避免普通样式表覆盖几何轮廓。"""
        super().__init__()
        self.tone = tone
        self.setFrameShape(QFrame.NoFrame)
        self.setProperty('agentIllustrated', True)

    def paintEvent(self, event):
        """绘制便签边线或切角/折页/撕边纸面，保持正文控件不旋转。"""
        c = getattr(self.window(), 'section_palette', colors())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.objectName() in ('settingsPrivacy', 'settingsThoughtNote'):
            p.setPen(QPen(QColor(c.line), 2))
            p.drawLine(QPointF(2, 7), QPointF(2, self.height() - 7))
            p.drawLine(QPointF(2, 7), QPointF(14, 7))
            return
        r = QRectF(2, 5, self.width() - 8, self.height() - 12)
        path = QPainterPath(QPointF(r.left() + 22, r.top()))
        path.lineTo(r.right() - 24, r.top())
        path.lineTo(r.right(), r.top() + 20)
        path.lineTo(r.right(), r.bottom() - 25)
        path.lineTo(r.right() - 25, r.bottom())
        for i in range(1, 14):
            x = r.right() - 25 - (r.width() - 44) * i / 13
            path.lineTo(x, r.bottom() - (2 if i % 2 else 0))
        path.lineTo(r.left(), r.bottom() - 15)
        path.lineTo(r.left(), r.top() + 22)
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(translucent(c.accent, 35))
        p.drawPath(path.translated(4, 5))
        p.setPen(QPen(QColor(c.line), 1))
        p.setBrush(QColor(getattr(c, self.tone) if self.tone else c.surface))
        p.drawPath(path)
        p.save()
        p.setClipPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(translucent(c.accent, 35))
        p.drawPolygon(polygon([(r.right() - 24, r.top()), (r.right() - 24, r.top() + 25),
                               (r.right() + 3, r.top() + 25)]))
        p.setPen(QPen(translucent(c.accent, 105), 1))
        for i in range(4):
            x = r.right() - 35 + i * 7
            p.drawLine(QPointF(x, r.bottom()), QPointF(x + 19, r.bottom() - 19))
        p.restore()
        p.setPen(QPen(QColor(c.accent), 2))
        p.drawLine(QPointF(r.left() + 23, r.top()), QPointF(r.left() + 69, r.top()))


class SettingsSection(QWidget):
    """分区标题旁的大编号背景，仅作为静态层次装饰。"""
    def __init__(self, number):
        """保存章节编号并预留标题区域高度。"""
        super().__init__()
        self.number = number
        self.setMinimumHeight(58)

    def paintEvent(self, event):
        """用章节强调色绘制裁切编号与定位线，实际标题由子控件显示。"""
        c = getattr(self.window(), 'section_palette', colors())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(translucent(c.accent, 48))
        p.setFont(QFont('Bahnschrift', 60, QFont.Bold))
        p.drawText(QRectF(self.width() - 147, -15, 138, self.height() + 20), Qt.AlignRight, self.number)
        p.setPen(QPen(QColor(c.line), 1))
        p.drawLine(QPointF(self.width() - 174, 12), QPointF(self.width() - 160, 12))
        p.drawLine(QPointF(self.width() - 167, 5), QPointF(self.width() - 167, 19))
