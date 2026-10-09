"""Screen-safe positioning in Qt logical coordinates, including negative origins."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication


def available_screens():
    primary = QGuiApplication.primaryScreen()
    screens = QGuiApplication.screens()
    if primary in screens:
        screens.remove(primary)
        screens.insert(0, primary)
    return [screen.availableGeometry() for screen in screens] or [QRect(0, 0, 1280, 720)]


def clamp_position(point, width, height, screens=None):
    screens = screens or available_screens()
    area = next((r for r in screens if r.contains(point)), screens[0])
    x = max(area.left(), min(point.x(), area.right() - width + 1))
    y = max(area.top(), min(point.y(), area.bottom() - height + 1))
    return QPoint(x, y)
