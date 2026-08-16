"""成就页（M3 UI）：37 项成就按类展示，未领取显示红点与领取按钮。

类别：速度（平均速度）/ 字数（累计有效字数）/ 分钟正确率 / 总正确率。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
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
        self._summary.setStyleSheet('font-weight:600; font-size:15px;')
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
            f'已解锁 {len(unlocked)} / {len(items)}　·　待领取 {len(pending)} 项'
            + ('（红点 = 可领取奖励）' if pending else ''))

        self._tabs.clear()
        for cat in ['speed', 'chars', 'min_acc', 'total_acc']:
            page = QWidget()
            lay = QVBoxLayout(page)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            inner = QWidget()
            v = QVBoxLayout(inner)
            v.setContentsMargins(4, 4, 4, 4)
            cat_items = [i for i in items if i['category'] == cat]
            for item in cat_items:
                v.addWidget(self._row(item))
            v.addStretch(1)
            scroll.setWidget(inner)
            lay.addWidget(scroll)
            self._tabs.addTab(page, f'{CAT_TITLES[cat]}（{sum(1 for i in cat_items if i["unlocked_at"])}/{len(cat_items)}）')

    def _row(self, item) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        h = QHBoxLayout(frame)

        dot = QLabel('●')
        dot.setStyleSheet(
            f'color:{CAT_COLORS[item["category"]]}; font-size:14px;')
        h.addWidget(dot)

        info = QVBoxLayout()
        name = QLabel(f'<b>{item["name"]}</b>')
        if item['unlocked_at'] and not item['claimed']:
            name.setText(f'<b>{item["name"]}</b> <span style="color:#ef4444;">● 待领取</span>')
        info.addWidget(name)
        desc = QLabel(item['desc'])
        desc.setStyleSheet(f'color:{P.muted}; font-size:12px;')
        info.addWidget(desc)
        rw = QLabel(f'奖励：{reward_text(item)}')
        rw.setStyleSheet(f'color:{P.faint}; font-size:12px;')
        info.addWidget(rw)
        h.addLayout(info, 1)

        if item['unlocked_at'] and not item['claimed']:
            btn = QPushButton('领取')
            btn.setStyleSheet(
                f'background:{P.accent}; color:white; border-radius:4px;'
                'padding:4px 14px;')
            btn.clicked.connect(lambda _=False, c=item['code']: self._do_claim(c))
            h.addWidget(btn)
        else:
            st = '已领取' if item['claimed'] else '未解锁'
            lab = QLabel(st)
            lab.setStyleSheet(
                f'color:{P.success};' if item['claimed'] else f'color:{P.faint};')
            h.addWidget(lab)
        return frame

    def _do_claim(self, code):
        granted = self._ach.claim(code)
        if granted:
            self.claimed.emit()
            self.refresh()
