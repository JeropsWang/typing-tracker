"""Sariana 肖像、头像选择器和素材解析。只负责显示与选择，不读写数据库。"""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from ...core.avatars import AVATAR_PRESETS, DEFAULT_AVATAR, normalize_avatar
from ..palette import P

ASSETS = Path(__file__).resolve().parents[1] / 'assets'
AVATAR_NOTES = {
    'default': '才没有在等你练习，键盘只是刚好空着。',
    'chibi': '手短，但敲键盘的气势很足。',
    'front': '正脸营业，请别只顾盯着我。',
    'side': '侧脸模式，给认真留一个角度。',
    'lino': '贝尔塔登场，键盘就是今晚的舞台。',
}


def avatar_path(preset=DEFAULT_AVATAR):
    return ASSETS / 'avatars' / f'{normalize_avatar(preset)}.png'


@lru_cache(maxsize=12)
def _pixmap(path, modified):
    return QPixmap(path)


def load_portrait(path):
    path = Path(path)
    try:
        image = _pixmap(str(path), path.stat().st_mtime_ns)
        if not image.isNull():
            return image
    except OSError:
        pass
    fallback = ASSETS / 'app_icon.png'
    return _pixmap(str(fallback), fallback.stat().st_mtime_ns)


def draw_portrait(painter, image, rect, *, round_crop=False):
    path = QPainterPath()
    if round_crop:
        path.addEllipse(rect)
    else:
        path.addRoundedRect(rect, 10, 10)
    painter.save()
    painter.setClipPath(path)
    scaled = image.scaled(round(rect.width()), round(rect.height()),
                          Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    painter.drawPixmap(rect, scaled, QRectF((scaled.width() - rect.width()) / 2,
                                           (scaled.height() - rect.height()) / 2,
                                           rect.width(), rect.height()))
    painter.restore()


class AvatarPortrait(QWidget):
    """个人中心圆形头像；上传失败或无上传时显示所选 Sariana。"""
    def __init__(self, size=96, parent=None):
        super().__init__(parent)
        self.preset = DEFAULT_AVATAR
        self._size = size
        self._image = load_portrait(avatar_path())
        self.setFixedSize(size, size)
        self.setAccessibleName('Sariana 头像')

    def set_size(self, size):
        self._size = size
        self.setFixedSize(size, size)

    def set_preset(self, preset):
        self.preset = normalize_avatar(preset)
        self.set_image(None)

    def set_image(self, path):
        self._image = load_portrait(path or avatar_path(self.preset))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        draw_portrait(p, self._image, rect, round_crop=True)
        p.setPen(QPen(QColor(P.primary), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(P.accent_rose), 2))
        p.drawArc(rect.adjusted(-3, -3, 3, 3), 15 * 16, 95 * 16)


class PortraitCard(QWidget):
    """偏移拍立得：装饰底纸旋转，人物与文字保持端正。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = load_portrait(avatar_path())
        self.caption = 'Sariana · 默认'
        self.setFixedSize(174, 214)
        self.setAccessibleName('当前头像预览')

    def set_portrait(self, preset, image=None):
        self._image = QPixmap.fromImage(image) if image is not None else load_portrait(avatar_path(preset))
        self.caption = '本地头像' if image is not None else f'Sariana · {dict(AVATAR_PRESETS)[normalize_avatar(preset)]}'
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.save()
        p.translate(87, 106)
        p.rotate(5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P.accent_rose))
        p.drawRoundedRect(QRectF(-70, -92, 144, 187), 12, 12)
        p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(P.paper))
        p.drawRoundedRect(QRectF(10, 8, 152, 190), 8, 8)
        draw_portrait(p, self._image, QRectF(18, 19, 136, 141))
        p.setPen(QColor(P.paper_text))
        font = QFont(); font.setPixelSize(13); font.setBold(True); p.setFont(font)
        p.drawText(QRectF(14, 167, 146, 24), Qt.AlignCenter, self.caption)
        p.setPen(Qt.NoPen)
        tape = QColor(P.primary); tape.setAlpha(160); p.setBrush(tape)
        p.save(); p.translate(85, 12); p.rotate(-12)
        p.drawRect(QRectF(-27, -5, 54, 13)); p.restore()


class _AvatarButton(QPushButton):
    def __init__(self, key, label, parent=None):
        super().__init__(label, parent)
        self.key = key
        self._image = load_portrait(avatar_path(key))
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setFixedHeight(110)
        self.setMinimumWidth(78)
        self.setAccessibleName(f'Sariana {label}头像')
        self.setToolTip(f'{AVATAR_NOTES[key]}\n选用 Sariana {label}，保存后生效。')
        self.setStyleSheet('QPushButton { background: transparent; border: none; padding: 0;'
                          ' min-height: 110px; max-height: 110px; }')

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor(P.focus_on_paper if self.hasFocus() else P.primary),
                      2 if self.isChecked() or self.hasFocus() else 0))
        fill = QColor(P.primary if self.isChecked() else P.accent_rose)
        fill.setAlpha(150 if self.isChecked() else (85 if self.underMouse() else 35))
        p.setBrush(fill)
        p.drawRoundedRect(rect, 14, 14)
        size = min(66, self.width() - 14)
        draw_portrait(p, self._image, QRectF((self.width() - size) / 2, 9, size, size), round_crop=True)
        p.setPen(QColor(P.paper_text))
        font = QFont(); font.setPixelSize(13); font.setBold(self.isChecked()); p.setFont(font)
        p.drawText(QRectF(4, 78, self.width() - 8, 25), Qt.AlignCenter, self.text())
        if self.isChecked():
            p.setPen(QPen(QColor(P.accent_rose), 3))
            p.drawLine(self.width() // 2 - 13, 104, self.width() // 2 + 13, 104)


class AvatarPicker(QWidget):
    selected = Signal(str)

    def __init__(self, preset=DEFAULT_AVATAR, parent=None):
        super().__init__(parent)
        self.buttons = {}
        self._group = QButtonGroup(self)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        for key, label in AVATAR_PRESETS:
            button = _AvatarButton(key, label)
            self._group.addButton(button)
            self.buttons[key] = button
            row.addWidget(button, 1)
            button.clicked.connect(lambda checked=False, k=key: self.selected.emit(k))
        self.set_preset(preset)

    def current_preset(self):
        return self._group.checkedButton().key

    def set_preset(self, key):
        self.buttons[normalize_avatar(key)].setChecked(True)
