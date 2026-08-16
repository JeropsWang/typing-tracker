"""应用图标（程序化绘制，多尺寸 ICO 生成）。

设计：深紫星空（呼应梨诺主题）→ 顶部舞台聚光 → 金色五角星（打字之星）+
白色输入光标 + 星尘点缀。全程 QPainter 矢量绘制，任何尺寸清晰。
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)

SIZES = [16, 24, 32, 48, 64, 128, 256]


def _star_path(cx: float, cy: float, R: float, r: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        ang = math.pi / 5 * i - math.pi / 2
        rad = R if i % 2 == 0 else r
        x = cx + rad * math.cos(ang)
        y = cy + rad * math.sin(ang)
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    return path


def draw_app_icon(size: int) -> QPixmap:
    """按 256 基准坐标绘制，缩放到任意尺寸。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(size / 256.0, size / 256.0)

    # 圆角底（深紫星空）
    base = QPainterPath()
    base.addRoundedRect(4, 4, 248, 248, 54, 54)
    p.setClipPath(base)
    grad = QLinearGradient(0, 0, 256, 256)
    grad.setColorAt(0.0, QColor('#312B74'))
    grad.setColorAt(0.55, QColor('#241B52'))
    grad.setColorAt(1.0, QColor('#171233'))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawRect(0, 0, 256, 256)

    # 舞台聚光（顶部光带）
    glow = QRadialGradient(QPointF(128, 58), 230)
    glow.setColorAt(0.0, QColor(179, 157, 219, 95))
    glow.setColorAt(0.55, QColor(179, 157, 219, 26))
    glow.setColorAt(1.0, QColor(179, 157, 219, 0))
    p.setBrush(glow)
    p.drawRect(0, 0, 256, 256)

    # 星尘（小星）
    for sx, sy, sr, alpha in [(66, 64, 5, 200), (190, 54, 4, 150),
                              (182, 148, 4, 120), (88, 166, 3, 100)]:
        sc = QColor('#FFE9A8')
        sc.setAlpha(alpha)
        p.setBrush(sc)
        p.drawEllipse(QPointF(sx, sy), sr, sr)

    # 金色星星光晕
    halo = QRadialGradient(QPointF(128, 112), 108)
    halo.setColorAt(0.0, QColor(255, 213, 79, 130))
    halo.setColorAt(0.6, QColor(255, 213, 79, 34))
    halo.setColorAt(1.0, QColor(255, 213, 79, 0))
    p.setBrush(halo)
    p.drawRect(0, 0, 256, 256)

    # 主图形：金色五角星（打字之星）
    star = _star_path(128, 112, 58, 23)
    star_grad = QLinearGradient(80, 54, 176, 172)
    star_grad.setColorAt(0.0, QColor('#FFF3C4'))
    star_grad.setColorAt(0.5, QColor('#FFD54F'))
    star_grad.setColorAt(1.0, QColor('#FFB300'))
    p.setBrush(star_grad)
    p.setPen(QPen(QColor(255, 243, 196, 160), 2.5))
    p.drawPath(star)

    # 输入光标（打字语义）
    caret = QPainterPath()
    caret.addRoundedRect(121, 168, 14, 58, 7, 7)
    caret_grad = QLinearGradient(121, 168, 135, 226)
    caret_grad.setColorAt(0.0, QColor('#FFFFFF'))
    caret_grad.setColorAt(1.0, QColor('#CBD5E1'))
    p.setBrush(caret_grad)
    p.setPen(Qt.NoPen)
    p.drawPath(caret)

    # 底部微弱阴影线（层次）
    p.setBrush(QColor(0, 0, 0, 46))
    line = QPainterPath()
    line.addRoundedRect(52, 236, 152, 8, 4, 4)
    p.drawPath(line)

    p.setClipping(False)
    p.end()
    return pm


def icon_pixmaps() -> list:
    return [draw_app_icon(s) for s in SIZES]


def tray_icon() -> QIcon:
    """托盘/窗口图标（多尺寸；PySide6 的 QIcon 不支持列表构造，逐个 addPixmap）。"""
    icon = QIcon()
    for pm in icon_pixmaps():
        icon.addPixmap(pm)
    return icon


def save_ico(path) -> Path:
    """多尺寸 PNG 内嵌 ICO（Vista+ 支持 PNG 压缩 ICO）。"""
    entries = []
    data_blobs = []
    for size in SIZES:
        pm = draw_app_icon(size)
        ba = QBuffer()
        ba.open(QIODevice.WriteOnly)
        pm.save(ba, 'PNG')
        data_blobs.append(bytes(ba.data()))
    offset = 6 + 16 * len(SIZES)
    for size, data in zip(SIZES, data_blobs):
        b = 0 if size >= 256 else size
        entries.append(struct.pack('<BBBBHHII', b, b, 0, 0, 1, 32,
                                   len(data), offset))
        offset += len(data)
    out = struct.pack('<HHH', 0, 1, len(SIZES)) + b''.join(entries)
    out += b''.join(data_blobs)
    target = Path(path)
    target.write_bytes(out)
    return target
