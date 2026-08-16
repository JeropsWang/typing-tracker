"""报表页（M2）：趋势分析 / 打卡日历 / 时段分布 / 周月报。

数据全部来自 daily_stats 与 minute_stats（日快照、分钟快照），
正确率与平均速度均为按日/按段指标，不涉及终身总计。
"""
from __future__ import annotations

from datetime import date, timedelta

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from ...core.classifier import tw_to_hanzi_per_min, tw_to_letters_per_min
from ..dashboard import _num
from ..palette import P

C_SPEED = '#3b82f6'
C_ACC = '#10b981'
C_CHARS = '#f59e0b'
C_EMPTY = '#e5e7eb'
C_LEVELS = ['#dbeafe', '#93c5fd', '#60a5fa', '#2563eb', '#1e40af']


def _dstr(d: date) -> str:
    return d.isoformat()


class ReportsPage(QWidget):
    def __init__(self, repo, engine, balance, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._engine = engine
        self._balance = balance
        self._hm_last_build = 0.0

        # 主题可覆盖的配色（apply_chart_palette 更新）
        self._curve_colors = {'speed': C_SPEED, 'acc': C_ACC, 'chars': C_CHARS}
        self._hm_levels = list(C_LEVELS)
        self._hm_empty = C_EMPTY

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._build_trend(), '趋势分析')
        self._tabs.addTab(self._build_heatmap(), '打卡日历')
        self._tabs.addTab(self._build_hours(), '时段分布')
        self._tabs.addTab(self._build_reports(), '周月报')

        lay = QVBoxLayout(self)
        lay.addWidget(self._tabs)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(10_000)

    # ---------- 统一刷新入口 ----------
    def refresh(self, *_):
        if not self.isVisible():
            return
        self._refresh_trend()
        self._refresh_hours()
        self._refresh_reports()
        self._refresh_heatmap()

    def apply_chart_palette(self, palette: dict):
        """主题切换时更新图表配色并重绘。"""
        self._curve_colors = {
            'speed': palette.get('speed', C_SPEED),
            'acc': palette.get('acc', C_ACC),
            'chars': palette.get('chars', C_CHARS),
        }
        self._hm_levels = list(palette.get('levels', C_LEVELS))
        self._hm_empty = palette.get('empty', C_EMPTY)

        bg = palette.get('background')
        if bg:
            self._plot.setBackground(bg)
            self._hours_plot.setBackground(bg)
        grid = palette.get('grid')
        if grid:
            pen = pg.mkPen(grid)
            for ax in ('bottom', 'left'):
                self._plot.getAxis(ax).setPen(pen)
                self._plot.getAxis(ax).setTextPen(pen)
                self._hours_plot.getAxis(ax).setPen(pen)
                self._hours_plot.getAxis(ax).setTextPen(pen)
        for key, curve in self._curves.items():
            curve.setPen(pg.mkPen(self._curve_colors[key], width=2))
        self._hm_last_build = 0.0
        self.refresh()

    def _unit(self) -> str:
        return self._repo.get_setting('unit_name', self._balance['unit']['name'])

    # ---------- Tab1 趋势分析 ----------
    def _build_trend(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        top = QHBoxLayout()
        top.addWidget(QLabel('范围:'))
        self._range_combo = QComboBox()
        for label, n in [('近 7 天', 7), ('近 30 天', 30), ('近 90 天', 90)]:
            self._range_combo.addItem(label, n)
        self._range_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self._range_combo)
        top.addWidget(QLabel('视角:'))
        self._view_combo = QComboBox()
        for label, factor in [('tw/分', 1.0), ('汉字/分', 0.5), ('字母/分', 1.0)]:
            self._view_combo.addItem(label, factor)
        self._view_combo.currentIndexChanged.connect(self.refresh)
        top.addWidget(self._view_combo)
        top.addStretch(1)
        self._pred_label = QLabel('')
        top.addWidget(self._pred_label)
        lay.addLayout(top)

        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel('bottom', '日期')
        self._plot.addLegend(offset=(10, 10))

        toggles = QHBoxLayout()
        self._checkboxes = {}
        self._curves = {}
        for key, name in [('speed', '平均速度'), ('acc', '正确率'), ('chars', '有效字数')]:
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.toggled.connect(self.refresh)
            toggles.addWidget(cb)
            self._checkboxes[key] = cb
            self._curves[key] = self._plot.plot(
                [], [], pen=pg.mkPen(self._curve_colors[key], width=2), name=name)
        toggles.addStretch(1)
        lay.addLayout(toggles)
        lay.addWidget(self._plot)
        return w

    def _refresh_trend(self):
        today = date.fromisoformat(self._engine.current_day())
        n = self._range_combo.currentData()
        start = today - timedelta(days=n - 1)
        days = self._repo.get_daily_range(_dstr(start), _dstr(today))

        xs = list(range(len(days)))
        ticks = [
            [(i, d['date'][5:]) for i, d in enumerate(days)
             if i % max(1, len(days) // 8) == 0]
        ]
        self._plot.getAxis('bottom').setTicks(ticks)

        factor = self._view_combo.currentData()
        self._plot.setLabel('left', '汉字/分' if factor == 0.5 else 'tw/分')
        series = {
            'speed': [float('nan') if d['avg_tw'] is None
                      else d['avg_tw'] * factor for d in days],
            'acc': [float('nan') if d['accuracy'] is None
                    else d['accuracy'] * 100 for d in days],
            'chars': [d['valid_chars'] for d in days],
        }
        for key, curve in self._curves.items():
            if self._checkboxes[key].isChecked():
                curve.setData(xs, series[key])
            else:
                curve.setData([], [])

        vals = [d['avg_tw'] for d in days if d['avg_tw'] is not None]
        unit = self._unit()
        if vals:
            m = sum(vals) / len(vals)
            self._pred_label.setText(
                f'平均 {m:.1f}{unit}/分 ｜ 预测汉字 {tw_to_hanzi_per_min(m):.1f} 字/分'
                f' ｜ 预测字母 {tw_to_letters_per_min(m):.1f} 字母/分')
        else:
            self._pred_label.setText('近段暂无数据')

    # ---------- Tab2 打卡日历（GitHub 风格年度热力图） ----------
    def _build_heatmap(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._hm_title = QLabel('')
        lay.addWidget(self._hm_title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._hm_grid = QWidget()
        self._hm_lay = QGridLayout(self._hm_grid)
        self._hm_lay.setSpacing(3)
        scroll.setWidget(self._hm_grid)
        lay.addWidget(scroll)

        legend = QHBoxLayout()
        legend.addWidget(QLabel('少'))
        for c in C_LEVELS:
            cell = QFrame()
            cell.setFixedSize(12, 12)
            cell.setStyleSheet(f'background:{c}; border-radius:2px;')
            legend.addWidget(cell)
        legend.addWidget(QLabel('多'))
        legend.addStretch(1)
        lay.addLayout(legend)
        return w

    def _refresh_heatmap(self):
        import time
        now = time.monotonic()
        if now - self._hm_last_build < 60:   # 热力图重建成本高，60 秒内不重复
            return
        self._hm_last_build = now

        today = date.fromisoformat(self._engine.current_day())
        y = today.year
        first = date(y, 1, 1)
        last = date(y, 12, 31)
        data = self._repo.get_heatmap(f'{y}-01-01', f'{y}-12-31')
        max_tw = max(data.values()) if data else 0

        def level(tw):
            if tw <= 0 or max_tw <= 0:
                return -1
            r = tw / max_tw
            if r <= 0.25:
                return 0
            if r <= 0.5:
                return 1
            if r <= 0.75:
                return 2
            return 3

        total_days = (last - first).days
        col_of = {}
        for i in range(total_days + 1):
            col_of[first + timedelta(days=i)] = i // 7
        max_col = total_days // 7

        # 清空旧网格
        while self._hm_lay.count():
            item = self._hm_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # 月份标签（颜色跟随主题 QSS）
        self._hm_lay.addWidget(QLabel(''), 0, 0)
        for m in range(1, 13):
            lab = QLabel(f'{m}月')
            lab.setStyleSheet('font-size:10px;')
            self._hm_lay.addWidget(lab, 0, col_of[date(y, m, 1)] + 1)

        # 日期格子（周一在顶行）
        for i in range(total_days + 1):
            day = first + timedelta(days=i)
            tw = data.get(day.isoformat(), 0)
            lv = level(tw)
            cell = QFrame()
            cell.setFixedSize(16, 16)
            color = self._hm_empty if lv < 0 else self._hm_levels[lv]
            cell.setStyleSheet(f'background:{color}; border-radius:3px;')
            tip = f'{day.isoformat()}：{tw} tw' if lv >= 0 else f'{day.isoformat()}：无记录'
            cell.setToolTip(tip)
            self._hm_lay.addWidget(cell, day.weekday() + 1, col_of[day] + 1)

        self._hm_lay.setRowStretch(8, 1)
        self._hm_lay.setColumnStretch(max_col + 2, 1)
        self._hm_title.setText(f'{y} 年打卡日历（颜色深浅 = 当日 tw 量）')

    # ---------- Tab3 时段分布 ----------
    def _build_hours(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self._hours_title = QLabel('')
        lay.addWidget(self._hours_title)
        self._hours_plot = pg.PlotWidget()
        self._hours_plot.showGrid(x=True, y=True, alpha=0.3)
        self._hours_plot.setLabel('bottom', '小时')
        self._hours_plot.setLabel('left', 'tw')
        self._hours_bar = pg.BarGraphItem(x=[], height=[], width=0.7)
        self._hours_plot.addItem(self._hours_bar)
        lay.addWidget(self._hours_plot)
        return w

    def _refresh_hours(self):
        today = date.fromisoformat(self._engine.current_day())
        start = today - timedelta(days=6)
        rows = self._repo.get_hourly_stats(_dstr(start), _dstr(today))
        tw = [0] * 24
        for r in rows:
            h = int(r['hour'])
            if 0 <= h <= 23:
                tw[h] = r['tw']
        self._hours_bar.setOpts(x=list(range(24)), height=tw, width=0.7)
        ticks = [[(i, str(i)) for i in range(0, 24, 3)]]
        self._hours_plot.getAxis('bottom').setTicks(ticks)
        self._hours_title.setText(f'近 7 天时段分布（{_dstr(start)} ~ {_dstr(today)}）')

    # ---------- Tab4 周月报 ----------
    def _build_reports(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        grid = QGridLayout()
        self._cards = {}
        for i, (key, title) in enumerate([
            ('week', '本周'), ('week_prev', '上周'),
            ('month', '本月'), ('month_prev', '上月'),
        ]):
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            v = QVBoxLayout(frame)
            t = QLabel(f'<b>{title}</b>')
            t.setStyleSheet('font-size:15px;')
            body = QLabel('—')
            body.setWordWrap(True)
            body.setTextFormat(Qt.RichText)
            v.addWidget(t)
            v.addWidget(body)
            self._cards[key] = body
            grid.addWidget(frame, i // 2, i % 2)
        lay.addLayout(grid)
        self._cmp_label = QLabel('')
        lay.addWidget(self._cmp_label)
        lay.addStretch(1)
        return w

    def apply_theme(self):
        """主题切换：刷新说明文字颜色（保证深色主题可读）。"""
        for lab in (self._pred_label, self._hm_title,
                    self._hours_title, self._cmp_label):
            lab.setStyleSheet(f'color:{P.muted};')

    def _periods(self):
        today = date.fromisoformat(self._engine.current_day())
        monday = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        pm_end = month_start - timedelta(days=1)
        pm_start = pm_end.replace(day=1)
        return {
            'week': (_dstr(monday), _dstr(today)),
            'week_prev': (_dstr(monday - timedelta(days=7)),
                          _dstr(monday - timedelta(days=1))),
            'month': (_dstr(month_start), _dstr(today)),
            'month_prev': (_dstr(pm_start), _dstr(pm_end)),
        }

    def _card_text(self, s, unit) -> str:
        if s is None:
            return '暂无数据'
        speed = s.get('avg_speed')
        acc = s.get('accuracy')
        parts = [
            f'有效字数 <b>{_num(s["valid"])}</b>',
            f'tw <b>{_num(s["tw"])}</b>',
            f'速度 <b>{speed:.1f}{unit}/分</b>' if speed else '速度 —',
            f'正确率 <b>{acc * 100:.1f}%</b>' if acc is not None else '正确率 —',
            f'活跃 <b>{_num(s["minutes"])}</b> 分钟',
        ]
        return '<br>'.join(parts)

    def _refresh_reports(self):
        unit = self._unit()
        periods = self._periods()
        sums = {}
        for key, (start, end) in periods.items():
            sums[key] = self._repo.get_summary(start, end)
        for key, body in self._cards.items():
            body.setText(self._card_text(sums[key], unit))

        def delta(cur, prev, field):
            if not cur or not prev or not prev.get(field):
                return '—'
            return f'{(cur[field] - prev[field]) / prev[field] * 100:+.0f}%'

        self._cmp_label.setText(
            '本周 vs 上周：'
            f'tw {delta(sums["week"], sums["week_prev"], "tw")} · '
            f'速度 {delta(sums["week"], sums["week_prev"], "avg_speed")} · '
            f'正确率 {delta(sums["week"], sums["week_prev"], "accuracy")} ｜ '
            '本月 vs 上月：'
            f'tw {delta(sums["month"], sums["month_prev"], "tw")} · '
            f'速度 {delta(sums["month"], sums["month_prev"], "avg_speed")} · '
            f'正确率 {delta(sums["month"], sums["month_prev"], "accuracy")}')
