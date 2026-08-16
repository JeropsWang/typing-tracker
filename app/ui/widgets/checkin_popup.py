"""每日签到弹窗：无边框卡片 + 弹入动画 + 连签数字滚动 + 星星粒子。

每天首次打卡成功后弹出；里程碑达成有特别庆祝横幅。
"""
from __future__ import annotations

import math
import random
from datetime import date

from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout,
)

from ..palette import P

_RNG = random.Random(11)


class CheckinPopup(QFrame):
    def __init__(self, parent, result: dict, balance: dict, accent: str = '#f59e0b',
                 dark: bool = True):
        super().__init__(parent)
        self._result = result
        self._balance = balance
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._particles = []        # [x, y, r, phase, speed]
        self._t = 0.0
        self._count = 0             # 动画中的连签数字

        if dark:
            bg = 'rgba(28, 22, 60, 242)'
        else:
            bg = 'rgba(255, 255, 255, 246)'
        self.setStyleSheet(
            f'QFrame {{ background: {bg}; border: 2px solid {accent};'
            f' border-radius: 22px; }}'
            f'QLabel {{ background: transparent; border: none; }}'
            f'#ck_title {{ font-size: 22px; font-weight: 800; }}'
            f'#ck_date {{ font-size: 12px; color: {P.muted}; }}'
            f'#ck_days {{ font-size: 52px; font-weight: 900; color: {accent}; }}'
            f'#ck_days_lab {{ font-size: 14px; }}'
            f'#ck_reward {{ font-size: 13px; color: {P.muted}; }}'
            f'#ck_mile {{ font-size: 14px; font-weight: 700; }}'
            f'#ck_next {{ font-size: 12px; color: {P.muted}; }}'
            f'QPushButton {{ background: {accent}; color: white; border: none;'
            f' border-radius: 12px; padding: 9px 26px; font-size: 14px;'
            f' font-weight: 700; }}'
            f'QPushButton:hover {{ background: {P.accent}; }}')

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 22, 28, 22)
        root.setSpacing(8)

        head = QHBoxLayout()
        title = QLabel('每日签到 ✨')
        title.setObjectName('ck_title')
        head.addWidget(title)
        head.addStretch(1)
        day = date.fromisoformat(result['date'])
        dlab = QLabel(f'{day.year}年{day.month}月{day.day}日')
        dlab.setObjectName('ck_date')
        head.addWidget(dlab)
        root.addLayout(head)

        self._days_label = QLabel('0')
        self._days_label.setObjectName('ck_days')
        self._days_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._days_label)
        lab = QLabel(f'🔥 连续签到')
        lab.setObjectName('ck_days_lab')
        lab.setAlignment(Qt.AlignCenter)
        root.addWidget(lab)

        reward = (f'基础 +{result["base_exp"]} exp'
                  + (f'　连签奖励 +{result["bonus_exp"]} exp' if result['bonus_exp'] else ''))
        rlab = QLabel(reward)
        rlab.setObjectName('ck_reward')
        rlab.setAlignment(Qt.AlignCenter)
        root.addWidget(rlab)

        if result.get('milestone'):
            mlab = QLabel(f'🎁 连签 {result["milestone"]} 天里程碑达成！礼包已发放！')
            mlab.setObjectName('ck_mile')
            mlab.setAlignment(Qt.AlignCenter)
            mlab.setStyleSheet(
                f'#ck_mile {{ font-size:14px; font-weight:700; color:{P.warn};'
                f' background:rgba(255,200,60,40); border-radius:8px; padding:6px; }}')
            root.addWidget(mlab)

        streak = result['streak']
        nxt = self._next_milestone(streak)
        if nxt:
            nlab = QLabel(f'距离下一里程碑（连签 {nxt} 天）还有 {nxt - streak} 天，加油！')
            nlab.setObjectName('ck_next')
            nlab.setAlignment(Qt.AlignCenter)
            root.addWidget(nlab)

        btn = QPushButton('开启今日之旅 ✨')
        btn.clicked.connect(self._close)
        root.addWidget(btn, 0, Qt.AlignCenter)

        self.setFixedWidth(340)
        self.adjustSize()

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._anim = QPropertyAnimation(self._opacity, b'opacity', self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        # 连签数字滚动动画
        self._count_timer = QTimer(self)
        self._count_timer.timeout.connect(self._tick_count)
        self._count_timer.start(45)
        self._tick = QTimer(self)
        self._tick.timeout.connect(self._tick_particles)
        self._tick.start(33)

    def _next_milestone(self, streak):
        for m in self._balance['checkin'].get('milestones', []):
            if m > streak:
                return m
        return None

    # ---------- 动画 ----------
    def start_animation(self) -> None:
        self._opacity.setOpacity(0.0)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _tick_count(self) -> None:
        target = self._result['streak']
        if self._count < target:
            self._count += 1
            self._days_label.setText(str(self._count))
        else:
            self._count_timer.stop()

    def _tick_particles(self) -> None:
        self._t += 0.033
        if len(self._particles) < 14 and _RNG.random() < 0.35:
            self._particles.append([
                _RNG.uniform(10, self.width() - 10),
                _RNG.uniform(10, self.height() - 10),
                _RNG.uniform(1.0, 2.4), _RNG.uniform(0, 6.283),
                _RNG.uniform(1.2, 2.6)])
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for x, y, r, phase, sp in self._particles:
            a = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(self._t * sp + phase))
            col = QColor(P.warn)
            col.setAlphaF(a)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QPointF(x, y), r, r)
            if r >= 2.0:
                pen = QPen(col, 0.7)
                p.setPen(pen)
                p.drawLine(QPointF(x - r * 2, y), QPointF(x + r * 2, y))
                p.drawLine(QPointF(x, y - r * 2), QPointF(x, y + r * 2))
        p.end()

    # ---------- 关闭 ----------
    def _close(self) -> None:
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self.deleteLater)
        self._anim.start()
