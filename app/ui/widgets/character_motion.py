"""Sariana 局部待机：眼部素材与手绘 SVG 发丝，单一定时器。"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import xml.etree.ElementTree as ET

from PySide6.QtCore import QObject, QPointF, QRectF, QElapsedTimer, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap, QRadialGradient

from .hand_drawn_hair import SvgHairLayer


@dataclass(frozen=True)
class IdlePose:
    blink: float = 0.0
    time: float = 0.0


class IdleTimeline:
    """无控件依赖的待机时序，恢复时从睁眼、中性姿态重新开始。"""
    def __init__(self):
        self._random = random.Random()
        self.reset()

    def reset(self):
        self.next_blink = self._random.uniform(4, 7)

    def sample(self, elapsed: float) -> IdlePose:
        phase = elapsed - self.next_blink
        if phase >= .26:
            self.next_blink = elapsed + self._random.uniform(4, 7)
            blink = 0.0
        elif phase < 0:
            blink = 0.0
        elif phase < .075:
            blink = self._ease(phase / .075)
        elif phase < .12:
            blink = 1.0
        else:
            blink = 1 - self._ease((phase - .12) / .14)
        return IdlePose(blink, elapsed)

    @staticmethod
    def _ease(value):
        return value * value * (3 - 2 * value)


class SarianaMotion(QObject):
    """角色动效拥有素材和时钟；窗口策略只负责 enabled，绘制由背景承接。"""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pose = IdlePose()
        self._enabled = False
        self._visible = False
        self._eyes = None
        self._hair = []
        self._timeline = IdleTimeline()
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def configure(self, source: Path | None, original: QPixmap | None, metadata=None):
        self._stop()
        self._eyes = None
        self._hair = []
        if not source or original is None or not metadata:
            return
        try:
            metadata = Path(metadata)
            data = json.loads(metadata.read_text(encoding='utf-8'))
            if (list((original.width(), original.height())) != data['source_size']
                    or hashlib.sha256(source.read_bytes()).hexdigest() != data['source_sha256']):
                return
            closed = QPixmap(str(metadata.parent / data['closed_eyes']))
            if closed.isNull() or closed.size() != original.size():
                return
            hair = [SvgHairLayer(metadata.parent / data['hair_svg'], original.size())]
            eye_regions = []
            for eye in data['eyes']:
                center = tuple(float(value) for value in eye['center'])
                radius = tuple(float(value) for value in eye['radius'])
                rotation = float(eye['rotation'])
                if (len(center) != 2 or len(radius) != 2
                        or not all(math.isfinite(value) for value in (*center, *radius, rotation))
                        or min(radius) <= 0):
                    raise ValueError('Eye region requires finite coordinates and positive radius')
                eye_regions.append((center, radius, rotation))
            if len(eye_regions) != 2:
                raise ValueError('Sariana blink requires two eye regions')
            mask = QPixmap(original.size())
            mask.fill(Qt.transparent)
            painter = QPainter(mask)
            painter.setPen(Qt.NoPen)
            for center, radius, rotation in eye_regions:
                painter.save()
                painter.translate(*center)
                painter.rotate(rotation)
                painter.scale(*radius)
                feather = QRadialGradient(0, 0, 1)
                feather.setColorAt(0, Qt.white)
                feather.setColorAt(.72, Qt.white)
                feather.setColorAt(1, Qt.transparent)
                painter.setBrush(feather)
                painter.drawEllipse(QRectF(-1, -1, 2, 2))
                painter.restore()
            painter.end()
            # 加载的 PNG 没有 alpha；先放进透明画布，掩膜才会留下透明区域。
            eyes = QPixmap(original.size())
            eyes.fill(Qt.transparent)
            painter = QPainter(eyes)
            painter.drawPixmap(0, 0, closed)
            painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            painter.drawPixmap(0, 0, mask)
            painter.end()
            self._eyes = eyes
            self._hair = hair
        except (OSError, ValueError, KeyError, TypeError, OverflowError, ET.ParseError):
            # 静态插画独立于动画素材，缺失/不匹配时继续正常显示。
            return
        self._sync()

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        self._sync()

    def set_visible(self, visible: bool):
        self._visible = bool(visible)
        self._sync()

    def _sync(self):
        if self._enabled and self._visible and self._eyes is not None:
            if not self._timer.isActive():
                self._timeline.reset()
                self._clock.start()
                self._timer.start()
        else:
            self._stop()

    def _stop(self):
        self._timer.stop()
        if self.pose != IdlePose():
            self.pose = IdlePose()
            self.changed.emit()

    def _tick(self):
        self.pose = self._timeline.sample(self._clock.elapsed() / 1000)
        self.changed.emit()

    def paint(self, painter: QPainter):
        if self.pose.time <= 0 or self._eyes is None:
            return
        for layer in self._hair:
            layer.paint(painter, self.pose.time)
        if self.pose.blink > 0:
            painter.save()
            painter.setOpacity(self.pose.blink)
            painter.drawPixmap(0, 0, self._eyes)
            painter.restore()
