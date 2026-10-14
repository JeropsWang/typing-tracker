"""Small static thumbnails from the same validated sprites used by the companion."""
from functools import lru_cache
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap


def sprite_icon(path, rect=None):
    """规范化素材路径/裁切区域为缓存键，返回工坊与配置共用图标。"""
    return _sprite_icon(str(path), tuple(rect) if rect else None)


@lru_cache(maxsize=40)
def _sprite_icon(path, rect):
    """读取并可选裁切素材，等比生成 144 像素缩略图，供外层缓存复用。"""
    image = QImage(str(path))
    if rect and not image.isNull():
        image = image.copy(QRect(*rect))
    return QIcon(QPixmap.fromImage(image).scaled(144, 144, Qt.KeepAspectRatio, Qt.SmoothTransformation))
