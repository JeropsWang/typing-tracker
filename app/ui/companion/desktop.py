"""Screen-safe positioning in Qt logical coordinates, including negative origins."""
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication


def available_screens():
    """主屏优先取得显示器可用区域，无可用显示器时提供安全默认区域。"""
    primary = QGuiApplication.primaryScreen()
    screens = QGuiApplication.screens()
    if primary in screens:
        screens.remove(primary)
        screens.insert(0, primary)
    return [screen.availableGeometry() for screen in screens] or [QRect(0, 0, 1280, 720)]


def clamp_position(point, width, height, screens=None):
    """按目标坐标所属或主屏区域限制视图位置，兼容负坐标和移除的显示器。"""
    screens = screens or available_screens()
    area = next((r for r in screens if r.contains(point)), screens[0])
    x = max(area.left(), min(point.x(), area.right() - width + 1))
    y = max(area.top(), min(point.y(), area.bottom() - height + 1))
    return QPoint(x, y)
