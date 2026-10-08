"""手绘 SVG 发丝层：固定发根，仅弯曲细线控制点。"""
from __future__ import annotations

import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtSvg import QSvgRenderer

ET.register_namespace('', 'http://www.w3.org/2000/svg')


class SketchStrand:
    def __init__(self, node):
        self.node = node
        segments = re.split(r'\s*C\s*', node.attrib['d'].strip())
        if not segments[0].startswith('M') or len(segments) < 2:
            raise ValueError('Hand-drawn strand requires M and cubic C segments')
        start = tuple(float(value) for value in segments[0][1:].replace(',', ' ').split())
        curves = [tuple(float(value) for value in segment.replace(',', ' ').split())
                  for segment in segments[1:]]
        if len(start) != 2 or any(len(curve) != 6 for curve in curves):
            raise ValueError('Invalid cubic strand coordinates')
        self.points = [start] + [(curve[index], curve[index + 1])
                                 for curve in curves for index in (0, 2, 4)]
        self.amplitude = float(node.get('data-sway', '2'))
        self.period = float(node.get('data-period', '8'))
        self.phase = float(node.get('data-phase', '0'))
        if (not all(math.isfinite(value) for point in self.points for value in point)
                or not all(math.isfinite(value) for value in (self.amplitude, self.period, self.phase))
                or self.period < 1 or self.amplitude < 0):
            raise ValueError('Strand motion requires finite values and a period of at least one second')
        self.amplitude = min(3.0, self.amplitude)

    def update(self, elapsed):
        # 两个缓慢周期叠加，避免所有细线像钟摆一样同步。
        sway = self.amplitude * (
            .78 * math.sin(elapsed * math.tau / self.period + self.phase)
            + .22 * math.sin(elapsed * math.tau / (self.period * 1.73) + self.phase * .7))
        points = []
        for index, (x, y) in enumerate(self.points):
            progress = index / (len(self.points) - 1)
            weight = progress * progress
            points.append((x + sway * weight, y + sway * weight * .12))
        commands = [f'M {points[0][0]:.2f} {points[0][1]:.2f}']
        for index in range(1, len(points), 3):
            commands.append('C ' + ' '.join(f'{value:.2f}' for point in points[index:index + 3] for value in point))
        self.node.set('d', ' '.join(commands))


class SvgHairLayer:
    """加载可编辑 SVG；共享一个渲染器，保持原插画纹理和轮廓固定。"""
    def __init__(self, path: Path, size):
        self._root = ET.fromstring(path.read_bytes())
        if self._root.tag != '{http://www.w3.org/2000/svg}svg':
            raise ValueError('Strand asset requires an SVG root element')
        viewbox = [float(value) for value in self._root.attrib['viewBox'].split()]
        if viewbox != [0, 0, size.width(), size.height()]:
            raise ValueError('Strand SVG must match the illustration canvas')
        self.strands = [SketchStrand(node) for node in self._root.iter()
                        if node.tag.rsplit('}', 1)[-1] == 'path']
        if not self.strands:
            raise ValueError('Empty strand SVG')
        self._rect = QRectF(0, 0, size.width(), size.height())
        self._renderer = QSvgRenderer()
        if not self._renderer.load(QByteArray(ET.tostring(self._root, encoding='utf-8'))):
            raise ValueError('Strand asset cannot be rendered as SVG')

    def paint(self, painter, elapsed):
        for strand in self.strands:
            strand.update(elapsed)
        if not self._renderer.load(QByteArray(ET.tostring(self._root, encoding='utf-8'))):
            return
        fade = min(1.0, elapsed / 1.2)
        fade = fade * fade * (3 - 2 * fade)
        painter.save()
        painter.setOpacity(painter.opacity() * fade)
        self._renderer.render(painter, self._rect)
        painter.restore()
