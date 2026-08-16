"""今日概览面板：实时统计 + 酷炫等级区 + 连签 + 三预测 + 钩子状态 + 分钟曲线。

所有文字/卡片颜色取自全局调色板 P（主题切换自动适配，保证可读性）。
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QHBoxLayout, QLabel,
    QVBoxLayout, QWidget,
)

from ..core.classifier import tw_to_hanzi_per_min, tw_to_letters_per_min
from .palette import P
from .widgets.level_bar import LevelBar


def _num(v, digits=0) -> str:
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:,.{digits}f}'
    return f'{v:,}'


class Dashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)

        # 钩子状态
        self._hook_status = QLabel('🟢 统计中')
        root.addWidget(self._hook_status)
        self._hook_info = QLabel('')
        self._hook_info.setStyleSheet('font-size:11px;')
        root.addWidget(self._hook_info)

        # 头部：等级徽章 / 称号 / 连签 / 酷炫进度条
        head = QHBoxLayout()
        self._level_badge = QLabel('Lv.1')
        head.addWidget(self._level_badge)
        head.addSpacing(10)
        col = QVBoxLayout()
        self._band_label = QLabel('')
        self._band_label.setStyleSheet('font-size:13px;')
        col.addWidget(self._band_label)
        self._level_bar = LevelBar()
        col.addWidget(self._level_bar)
        self._exp_text = QLabel('')
        self._exp_text.setStyleSheet('font-size:11px;')
        col.addWidget(self._exp_text)
        head.addLayout(col, 1)
        head.addSpacing(10)
        self._streak_label = QLabel('🔥 连签 0 天')
        self._streak_label.setStyleSheet('font-weight:600; font-size:14px;')
        head.addWidget(self._streak_label, 0, Qt.AlignTop)
        root.addLayout(head)

        # 统计卡片（今日 / 终身两组）
        grid = QGridLayout()
        self._values = {}
        self._name_labels = []
        self._card_frames = []
        cards = [
            ('📊 今日', [
                ('输入字数', 'typed'), ('删除字数', 'deleted'),
                ('有效字数', 'valid'), ('今日 tw', 'tw'),
                ('平均速度', 'avg_tw'), ('正确率', 'accuracy'),
                ('预测汉字/分', 'pred_hanzi'), ('预测字母/分', 'pred_letters'),
                ('活跃时长', 'minutes'),
            ]),
            ('🏅 终身总计', [
                ('累计输入', 'lifetime_typed'), ('累计有效', 'lifetime_valid'),
                ('累计 tw', 'lifetime_tw'), ('累计活跃', 'lifetime_minutes'),
            ]),
        ]
        for c, (title, fields) in enumerate(cards):
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            # 柔和投影（高级感）
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(22)
            shadow.setOffset(0, 5)
            shadow.setColor(QColor(P.shadow_color))
            card.setGraphicsEffect(shadow)
            v = QVBoxLayout(card)
            t = QLabel(f'<b>{title}</b>')
            t.setStyleSheet('font-size:15px;')
            v.addWidget(t)
            self._name_labels.append(t)
            inner = QGridLayout()
            for i, (name, key) in enumerate(fields):
                val = QLabel('—')
                val.setStyleSheet('font-size:19px; font-weight:700;')
                n = QLabel(name)
                n.setStyleSheet('font-size:11px;')
                inner.addWidget(n, i, 0)
                inner.addWidget(val, i, 1)
                self._values[key] = val
                self._name_labels.append(n)
            v.addLayout(inner)
            self._card_frames.append(card)
            grid.addWidget(card, 0, c)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        root.addLayout(grid)

        # 今日逐分钟实时曲线
        self._mini_title = QLabel('✨ 今日逐分钟 tw 曲线')
        self._mini_title.setStyleSheet('margin-top:6px;')
        root.addWidget(self._mini_title)
        self._mini_plot = pg.PlotWidget()
        self._mini_plot.setFixedHeight(130)
        self._mini_plot.showGrid(x=False, y=True, alpha=0.3)
        self._mini_plot.setLabel('bottom', '时间')
        self._mini_curve = self._mini_plot.plot(
            [], [], pen=pg.mkPen(P.accent, width=2))
        root.addWidget(self._mini_plot)

        root.addStretch(1)

        self._hint = QLabel('提示：关闭窗口后驻留系统托盘，后台继续统计打字。')
        self._hint.setStyleSheet('font-size:11px;')
        root.addWidget(self._hint)

        self.apply_theme()

    # ---------- 主题适配（文字可读性核心） ----------
    def apply_theme(self):
        """主题切换时调用：刷新所有文字/卡片颜色。"""
        self._hook_status.setStyleSheet(
            f'color:{P.success}; font-weight:600;')
        self._hook_info.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._level_badge.setStyleSheet(
            f'font-size:30px; font-weight:800; color:{P.badge_text};'
            f'background:{P.badge_bg}; border-radius:14px;'
            f'padding:6px 18px; border:2px solid {P.badge_border};')
        self._band_label.setStyleSheet(f'color:{P.muted}; font-size:13px;')
        self._exp_text.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._streak_label.setStyleSheet(
            f'color:{P.warn}; font-weight:600; font-size:14px;')
        for lab in self._name_labels:
            lab.setStyleSheet(f'color:{P.muted}; font-size:11px;')
        for card in self._card_frames:
            card.setStyleSheet(
                f'QFrame {{ background:{P.card_bg}; border-radius:16px;'
                f' border:1px solid {P.card_border}; }}')
            eff = card.graphicsEffect()
            if isinstance(eff, QGraphicsDropShadowEffect):
                eff.setColor(QColor(P.shadow_color))
        self._mini_title.setStyleSheet(f'color:{P.muted}; margin-top:6px;')
        self._hint.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._mini_plot.setBackground(P.mini_bg)
        self._mini_curve.setPen(pg.mkPen(P.accent, width=2))

    # ---------- 钩子状态 ----------
    def set_hook_status(self, ok: bool):
        self._hook_status.setText('🟢 统计中（键盘钩子正常）' if ok
                                  else '🔴 键盘钩子未运行，不会统计打字——请重启应用')
        self._hook_status.setStyleSheet(
            f'color:{"#10b981" if ok else "#ef4444"}; font-weight:600;')

    def set_hook_info(self, event_count: int, ime_readable: bool, errs=None,
                      tsf_ok: bool = False):
        text = f'钩子已捕获 {event_count:,} 个按键事件（本次运行）'
        if tsf_ok:
            text += ' ｜ TSF 中文精确计数已启用'
        elif not ime_readable:
            text += ' ｜ 输入法组字状态读取不可用（TSF 输入法），中文按按键近似计数'
        if errs:
            text += f' ｜ ⚠ 回调异常 {len(errs)} 条（统计可能中断，悬停查看详情）'
            self._hook_info.setToolTip('\n'.join(errs[:3]))
        else:
            self._hook_info.setToolTip('')
        self._hook_info.setText(text)

    # ---------- 等级 ----------
    def set_level_colors(self, colors):
        self._level_bar.set_colors(colors)

    def refresh(self, snap, level, progress, band, streak, unit):
        self._level_badge.setText(f'Lv.{level}')
        self._band_label.setText(f'称号：{band}　·　{unit} 单位')
        self._streak_label.setText(f'🔥 连签 {streak} 天')
        self._level_bar.set_progress(progress)
        self._exp_text.setText(f'经验进度 {round(progress * 100)}%')

        self._values['typed'].setText(_num(snap['typed']))
        self._values['deleted'].setText(_num(snap['deleted']))
        self._values['valid'].setText(_num(snap['valid']))
        self._values['tw'].setText(_num(snap['tw']))
        avg = snap['avg_tw']
        self._values['avg_tw'].setText(
            f'{avg:.1f} {unit}/分' if avg is not None else '—')
        self._values['pred_hanzi'].setText(
            f'{tw_to_hanzi_per_min(avg):.1f} 字/分' if avg is not None else '—')
        self._values['pred_letters'].setText(
            f'{tw_to_letters_per_min(avg):.1f} 字母/分' if avg is not None else '—')
        acc = snap['accuracy']
        self._values['accuracy'].setText(
            f'{acc * 100:.1f}%' if acc is not None else '—')
        self._values['minutes'].setText(_num(snap['minutes']))
        self._values['lifetime_typed'].setText(_num(snap['lifetime_typed']))
        self._values['lifetime_valid'].setText(_num(snap['lifetime_valid']))
        self._values['lifetime_tw'].setText(_num(snap['lifetime_tw']))
        self._values['lifetime_minutes'].setText(_num(snap['lifetime_minutes']))

        series = snap.get('minutes_series') or []
        if series:
            xs = list(range(len(series)))
            ys = [v[1] for v in series]
            self._mini_curve.setData(xs, ys)
            ticks = [[
                (i, v[0]) for i, v in enumerate(series)
                if i % max(1, len(series) // 6) == 0
            ]]
            self._mini_plot.getAxis('bottom').setTicks(ticks)
        else:
            self._mini_curve.setData([], [])
