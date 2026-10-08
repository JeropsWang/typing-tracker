"""应用图标：优先使用交付 PNG，缺失/损坏时回退程序化绘制。

优先级（窗口图标 / 托盘图标 / 打包 ICO 共用同一口径）：

1. 交付资源 `app/ui/assets/app_icon.png`（与界面人物一致的应用图标，
   透明圆角外沿；**512×512 派生版**，由 1254×1254 交付原稿平滑降采样得到，
   原稿只留在 `.local` 不入仓）。
2. 程序化绘制 `draw_app_icon()`：深紫星空（呼应梨诺主题）→ 顶部舞台聚光 →
   金色五角星（打字之星）+ 白色输入光标 + 星尘点缀，全程 QPainter 矢量绘制。

两份资源都按 `SIZES` 生成多尺寸 QPixmap：QIcon 里没有对应尺寸时由 Qt
自动缩放，小尺寸（16/24）会比现算的缩放略糊，所以逐尺寸预先生成。
`save_ico()` 以 PNG 内嵌方式写多尺寸 ICO（Vista+ 支持），供 PyInstaller 使用。
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)

SIZES = [16, 24, 32, 48, 64, 128, 256]

# 交付应用图标（与 design.py / achievements.py 的 `__file__` 相对定位口径一致：
# onefile 打包时 __file__ 落在解包目录内，--add-data 收集的整棵树同样可命中）
ASSETS = Path(__file__).resolve().parent
APP_ICON_PNG = ASSETS / 'app_icon.png'


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
    """程序化绘制的多尺寸图标（回退资源）。"""
    return [draw_app_icon(s) for s in SIZES]


def png_pixmaps(path=None) -> list:
    """把交付 PNG 缩放到 `SIZES` 各档；文件缺失/读不出时返回空列表。"""
    target = APP_ICON_PNG if path is None else Path(path)
    try:
        image = QImage(str(target))
    except Exception:  # 极端情况下的 Qt 层异常：视为不可用，交由调用方回退
        return []
    if image.isNull():
        return []
    out = []
    for size in SIZES:
        pm = QPixmap.fromImage(image.scaled(
            size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        if not pm.isNull():
            out.append(pm)
    return out


def _to_icon(pixmaps) -> QIcon:
    """PySide6 的 QIcon 不支持列表构造，逐个 addPixmap。"""
    icon = QIcon()
    for pm in pixmaps:
        icon.addPixmap(pm)
    return icon


def tray_icon() -> QIcon:
    """托盘/窗口图标：交付 PNG 优先，缺失时回退程序化绘制（不抛异常）。"""
    pixmaps = png_pixmaps()
    if not pixmaps:
        pixmaps = icon_pixmaps()
    return _to_icon(pixmaps)


def app_icon() -> QIcon:
    """与 `tray_icon()` 同源的 QIcon（供 QApplication.setWindowIcon 用）。"""
    return tray_icon()


def save_ico(path, source=None) -> Path:
    """写多尺寸 PNG 内嵌 ICO（Vista+ 支持 PNG 压缩 ICO）。

    `source` 给定时以该图片为源缩放各档；缺省或读取失败时回退程序化绘制。
    """
    pixmaps = png_pixmaps(source)
    if not pixmaps:
        pixmaps = icon_pixmaps()
    data_blobs = []
    for pm in pixmaps:
        ba = QBuffer()
        ba.open(QIODevice.WriteOnly)
        pm.save(ba, 'PNG')
        data_blobs.append(bytes(ba.data()))
    count = len(pixmaps)
    offset = 6 + 16 * count
    entries = []
    for size, data in zip(SIZES, data_blobs):
        b = 0 if size >= 256 else size
        entries.append(struct.pack('<BBBBHHII', b, b, 0, 0, 1, 32,
                                   len(data), offset))
        offset += len(data)
    out = struct.pack('<HHH', 0, 1, count) + b''.join(entries)
    out += b''.join(data_blobs)
    target = Path(path)
    target.write_bytes(out)
    return target
