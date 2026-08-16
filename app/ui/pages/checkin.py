"""打卡页（M3 UI）：月历连签视图 + 补签卡 + 里程碑礼包 + 道具库存。"""
from __future__ import annotations

import json
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ..palette import P

C_CHECKED = '#3b82f6'
C_TODAY_BORDER = '#ef4444'


def _dstr(d: date) -> str:
    return d.isoformat()


class CheckinPage(QWidget):
    def __init__(self, repo, balance, checkin_service, reward_service, engine,
                 parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._checkin = checkin_service
        self._rewards = reward_service
        self._engine = engine

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        self._streak_label = QLabel('连签 0 天')
        self._streak_label.setStyleSheet('font-size:20px; font-weight:600;')
        top.addWidget(self._streak_label)
        self._card_label = QLabel('')
        top.addWidget(self._card_label)
        top.addStretch(1)
        self._repair_btn = QPushButton('使用补签卡')
        self._repair_btn.clicked.connect(self._repair)
        top.addWidget(self._repair_btn)
        root.addLayout(top)

        # 月历
        nav = QHBoxLayout()
        self._prev_btn = QPushButton('‹ 上月')
        self._next_btn = QPushButton('下月 ›')
        self._prev_btn.clicked.connect(lambda: self._shift_month(-1))
        self._next_btn.clicked.connect(lambda: self._shift_month(1))
        self._month_label = QLabel('')
        self._month_label.setStyleSheet('font-weight:600; font-size:15px;')
        nav.addWidget(self._prev_btn)
        nav.addWidget(self._month_label)
        nav.addWidget(self._next_btn)
        nav.addStretch(1)
        root.addLayout(nav)

        self._cal = QGridLayout()
        root.addLayout(self._cal)

        # 里程碑
        self._ms_title = QLabel('连签里程碑礼包')
        self._ms_title.setStyleSheet('font-weight:600; margin-top:8px;')
        root.addWidget(self._ms_title)
        self._ms_label = QLabel('')
        self._ms_label.setWordWrap(True)
        self._ms_label.setStyleSheet('font-size:12px;')
        root.addWidget(self._ms_label)

        # 道具库存
        self._inv_label = QLabel('')
        self._inv_label.setStyleSheet('font-size:12px;')
        root.addWidget(self._inv_label)
        self._boost_btn = QPushButton('使用经验加成卡（30 分钟 ×2）')
        self._boost_btn.clicked.connect(self._use_boost)
        root.addWidget(self._boost_btn)
        root.addStretch(1)

        self._month = date.fromisoformat(self._engine.current_day())
        self.apply_theme()
        self.refresh()

    def apply_theme(self):
        """主题切换：刷新文字颜色（保证深色主题可读）。"""
        self._streak_label.setStyleSheet(
            f'font-size:20px; font-weight:600; color:{P.warn};')
        for lab in (self._card_label, self._ms_label, self._inv_label):
            lab.setStyleSheet(f'font-size:12px; color:{P.muted};')

    # ---------- 刷新 ----------
    def refresh(self, *_):
        today = date.fromisoformat(self._engine.current_day())
        streak = self._repo.get_streak(_dstr(today)) or self._repo.get_streak(
            _dstr(today - timedelta(days=1)))
        cards = self._rewards.count('makeup_card')
        boost = self._rewards.count('exp_boost')
        titles = self._rewards.titles()

        self._streak_label.setText(f'🔥 连签 {streak} 天')
        self._card_label.setText(
            f'补签卡 ×{cards}　·　经验加成卡 ×{boost}'
            + (f'　·　称号：{"、".join(titles)}' if titles else ''))

        missed = not self._repo.has_checkin(_dstr(today - timedelta(days=1)))
        self._repair_btn.setEnabled(missed and cards > 0)
        self._repair_btn.setText(
            '使用补签卡补签昨天' if missed else '昨日已打卡')

        self._build_calendar()
        self._build_milestones()
        self._build_inventory(boost)

    # ---------- 月历 ----------
    def _shift_month(self, delta):
        m = self._month.month + delta
        y = self._month.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        self._month = date(y, m, 1)
        self._build_calendar()

    def _build_calendar(self):
        # 立即脱离父级再销毁，避免重建期间瞬时双重绘制（布局体检发现的真实问题）
        while self._cal.count():
            item = self._cal.takeAt(0)
            if item.widget():
                w = item.widget()
                w.setParent(None)
                w.deleteLater()

        self._month_label.setText(f'{self._month.year} 年 {self._month.month} 月')
        today = date.fromisoformat(self._engine.current_day())
        first = self._month
        last = date(first.year, first.month + 1, 1) - timedelta(days=1)
        rows = self._repo.get_checkins(_dstr(first), _dstr(last))
        streak_map = {k: v['streak'] for k, v in rows.items()}

        for i, wd in enumerate(['一', '二', '三', '四', '五', '六', '日']):
            lab = QLabel(wd)
            lab.setAlignment(Qt.AlignCenter)
            lab.setStyleSheet('font-size:11px;')
            self._cal.addWidget(lab, 0, i)

        start_col = (first.weekday()) % 7  # 周一=0
        day = first
        row = 1
        for _ in range(start_col):
            self._cal.addWidget(QLabel(''), row, _)
        while day <= last:
            cell = QFrame()
            cell.setFixedSize(44, 44)
            bg = C_CHECKED if _dstr(day) in streak_map else (
                P.cal_missed if day < today else P.cal_future)
            style = (f'background:{bg}; border-radius:6px;')
            if day == today:
                style += f'border:2px solid {C_TODAY_BORDER};'
            cell.setStyleSheet(style)
            num = QLabel(str(day.day))
            num.setAlignment(Qt.AlignCenter)
            if _dstr(day) in streak_map:
                num.setStyleSheet('color:white; font-weight:600;')
            if _dstr(day) in streak_map:
                cell.setToolTip(f'{day.isoformat()}　连签 {streak_map[_dstr(day)]} 天')
            lay = QVBoxLayout(cell)
            lay.addWidget(num)
            self._cal.addWidget(cell, row, day.weekday())
            if day.weekday() == 6:
                row += 1
            day += timedelta(days=1)

    # ---------- 里程碑 ----------
    def _build_milestones(self):
        cfg = self._balance['checkin']
        ms = cfg.get('milestones', [])
        rewards = cfg.get('milestone_rewards', {})
        granted = self._repo.get_setting('milestone_granted', '[]')
        try:
            granted = json.loads(granted)
        except (ValueError, TypeError):
            granted = []
        parts = []
        for m in ms:
            rw = rewards.get(str(m), {})
            text = ' + '.join(
                (f'{q} exp' if k == 'exp'
                 else f'补签卡×{q}' if k == 'makeup_card'
                 else f'加成卡×{q}' if k == 'exp_boost'
                 else f'称号「{q}」')
                for k, q in rw.items()) or '—'
            state = '✅' if m in granted else '🔒'
            parts.append(f'{state} 第 {m} 天：{text}')
        self._ms_label.setText('　'.join(parts))

    # ---------- 库存与加成卡 ----------
    def _build_inventory(self, boost):
        self._boost_btn.setEnabled(boost > 0)
        if self._rewards.boost_active():
            self._boost_btn.setText('经验加成卡生效中（×2）…')
            self._boost_btn.setEnabled(False)

    def _use_boost(self):
        if self._rewards.use_exp_boost(30):
            self.refresh()

    def _repair(self):
        today = date.fromisoformat(self._engine.current_day())
        missed = _dstr(today - timedelta(days=1))
        if not self._repo.has_checkin(missed):
            ret = QMessageBox.question(
                self, '补签', f'使用 1 张补签卡补签 {missed}？\n补签后连签天数恢复延续。')
            if ret == QMessageBox.Yes:
                self._repo.use_reward('makeup_card')
                r = self._checkin.apply_makeup_card(missed)
                if r:
                    self.refresh()
