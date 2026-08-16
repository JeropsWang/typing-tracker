"""成就墙：37 项成就以徽章卡片展示（图案 + 名称 + 状态）。

- 已解锁：彩色描边 + 发光底 + 大图标
- 待领取：红点 + 领取按钮
- 未解锁：灰色 + 🔒
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..palette import P

CAT_TITLES = {
    'speed': '平均速度',
    'chars': '累计字数',
    'min_acc': '每分钟正确率',
    'total_acc': '总正确率',
}

CAT_COLORS = {
    'speed': '#3b82f6',
    'chars': '#f59e0b',
    'min_acc': '#10b981',
    'total_acc': '#8b5cf6',
}


def reward_text(item) -> str:
    parts = []
    for rw in item.get('rewards', []):
        kind, qty = rw['kind'], rw.get('qty', 1)
        if kind == 'exp':
            parts.append(f'{qty} exp')
        elif kind == 'makeup_card':
            parts.append(f'补签卡×{qty}')
        elif kind == 'exp_boost':
            parts.append(f'经验加成卡×{qty}')
        elif kind == 'title':
            parts.append(f'称号「{rw.get("value", "")}」')
    return ' + '.join(parts) if parts else '—'


class AchievementsPage(QWidget):
    claimed = Signal()

    def __init__(self, repo, balance, ach_service, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._ach = ach_service

        root = QVBoxLayout(self)
        self._summary = QLabel('')
        root.addWidget(self._summary)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)
        self.apply_theme()

    def apply_theme(self):
        self._summary.setStyleSheet(
            f'font-weight:600; font-size:15px; color:{P.text};')

    def refresh(self):
        items = self._ach.all_achievements()
        unlocked = [i for i in items if i['unlocked_at']]
        pending = [i for i in unlocked if not i['claimed']]
        self._summary.setText(
            f'🏆 成就墙　已解锁 {len(unlocked)} / {len(items)}'
            + (f'　·　待领取 {len(pending)} 项（红点提示）' if pending else ''))

        self._tabs.clear()
        for cat in ['speed', 'chars', 'min_acc', 'total_acc']:
            page = QWidget()
            lay = QVBoxLayout(page)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            grid = QGridLayout(inner)
            grid.setSpacing(10)
            cat_items = [i for i in items if i['category'] == cat]
            for idx, item in enumerate(cat_items):
                grid.addWidget(self._card(item), idx // 4, idx % 4)
            grid.setRowStretch(len(cat_items) // 4 + 1, 1)
            scroll.setWidget(inner)
            lay.addWidget(scroll)
            self._tabs.addTab(
                page, f'{CAT_TITLES[cat]}（{sum(1 for i in cat_items if i["unlocked_at"])}/{len(cat_items)}）')

    # ---------- 徽章卡片 ----------
    def _card(self, item) -> QWidget:
        frame = QFrame()
        frame.setFixedSize(176, 168)
        frame.setFrameShape(QFrame.StyledPanel)
        unlocked = bool(item['unlocked_at'])
        claimed = bool(item['claimed'])

        if unlocked:
            frame.setStyleSheet(
                f'QFrame {{ background: {P.card_bg};'
                f' border: 2px solid {P.accent}; border-radius: 14px; }}')
        else:
            frame.setStyleSheet(
                f'QFrame {{ background: rgba(120,120,140,40);'
                f' border: 1px dashed rgba(150,150,170,90); border-radius: 14px; }}')

        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(2)

        top = QHBoxLayout()
        icon = QLabel(item.get('icon', '🎯'))
        icon.setStyleSheet('font-size:34px;')
        if not unlocked:
            icon.setGraphicsEffect(_gray_effect())
        top.addWidget(icon)
        top.addStretch(1)
        if unlocked and not claimed:
            dot = QLabel('●')
            dot.setStyleSheet('color:#ef4444; font-size:14px;')
            top.addWidget(dot)
        elif claimed:
            ok = QLabel('✓')
            ok.setStyleSheet(f'color:{P.success}; font-size:14px; font-weight:800;')
            top.addWidget(ok)
        else:
            lock = QLabel('🔒')
            lock.setStyleSheet('font-size:13px;')
            top.addWidget(lock)
        v.addLayout(top)

        name = QLabel(f'<b>{item["name"]}</b>')
        name.setStyleSheet(f'color:{P.text}; font-size:13px;')
        name.setAlignment(Qt.AlignCenter)
        v.addWidget(name)

        desc = QLabel(item['desc'])
        desc.setStyleSheet(f'color:{P.muted}; font-size:10px;')
        desc.setAlignment(Qt.AlignCenter)
        desc.setWordWrap(True)
        v.addWidget(desc)

        if unlocked and not claimed:
            btn = QPushButton('领取')
            btn.setStyleSheet(
                f'background:{P.accent}; color:white; border-radius:8px;'
                'padding:3px 10px; font-weight:700;')
            btn.clicked.connect(lambda _=False, c=item['code']: self._do_claim(c))
            v.addWidget(btn, 0, Qt.AlignCenter)
        else:
            rw = QLabel(f'{reward_text(item)}' if unlocked else '达成后解锁奖励')
            rw.setStyleSheet(f'color:{P.faint}; font-size:9px;')
            rw.setAlignment(Qt.AlignCenter)
            rw.setWordWrap(True)
            v.addWidget(rw)
        return frame

    def _do_claim(self, code):
        granted = self._ach.claim(code)
        if granted:
            self.claimed.emit()
            self.refresh()


def _gray_effect():
    from PySide6.QtWidgets import QGraphicsColorizeEffect
    eff = QGraphicsColorizeEffect()
    eff.setColor(Qt.gray)
    eff.setStrength(0.85)
    return eff
