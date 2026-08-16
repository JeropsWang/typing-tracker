"""今日概览面板（前沿 Dashboard 布局）。

层级设计（现代仪表盘范式）：
1. 状态行：钩子状态（弱化，一行小字）
2. 等级区：徽章 + 渐变进度条 + 连签（一行）
3. Hero 区：3 张大数字卡片（有效字数 / 平均速度 / 正确率）——视觉焦点
4. 指标 chips：次级指标两行网格（输入/删除/改写率/tw/预测…）
5. 终身汇总条：单行卡片
6. 今日逐分钟曲线
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ..core.classifier import tw_to_hanzi_per_min, tw_to_letters_per_min
from .assets.icons import pixmap as svg_pixmap
from .palette import P
from .widgets.level_bar import LevelBar


def _num(v, digits=0) -> str:
    if v is None:
        return '—'
    if isinstance(v, float):
        return f'{v:,.{digits}f}'
    return f'{v:,}'


# Hero 卡语义色（低饱和，深浅主题均可达标；克制统一，避免彩虹糖）
_HERO_COLORS = {
    'chars': '#6366F1',   # indigo
    'speed': '#0D9488',   # teal
    'acc': '#DB2777',     # pink
}


class _HeroCard(QFrame):
    """大数字 Hero 卡：顶部语义色条 + 图标 + 大数字（克制统一风格）。"""

    def __init__(self, icon_name, label, key, unit='', parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self._key = key
        self._color = _HERO_COLORS.get(key, '#6366F1')
        # 注意：不使用 QGraphicsDropShadowEffect——无边框透明窗口上效果残留
        # 会导致整体渲染偏移（v0.8.6 修复；此处曾漏网，v0.8.9 移除）
        # 层次感由 1px 边框 + 渐变底色实现（apply_theme）

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 10, 16, 14)
        v.setSpacing(4)
        bar = QFrame()
        bar.setFixedHeight(4)
        bar.setStyleSheet(
            f'QFrame {{ background:{self._color}; border:none; border-radius:2px; }}')
        v.addWidget(bar)
        row = QHBoxLayout()
        row.setSpacing(6)
        self._icon = QLabel()
        self._icon.setPixmap(svg_pixmap(icon_name, self._color, 16))
        row.addWidget(self._icon)
        self._lab = QLabel(label)
        row.addWidget(self._lab)
        row.addStretch(1)
        v.addLayout(row)
        self._value = QLabel('—')
        self._value.setStyleSheet(
            f'color:{self._color}; font-size:34px; font-weight:900;')
        v.addWidget(self._value)
        self._unit = QLabel(unit)
        v.addWidget(self._unit)

    def apply_theme(self):
        self._lab.setStyleSheet(f'color:{P.muted}; font-size:12px; font-weight:600;')
        self._unit.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._value.setStyleSheet(
            f'color:{self._color}; font-size:34px; font-weight:900;')
        self.setStyleSheet(
            f'QFrame {{ background:{P.card_bg}; border-radius:16px;'
            f' border:1px solid {P.card_border}; }}')

    def set_value(self, text: str, tooltip: str = ''):
        self._value.setText(text)
        self._value.setToolTip(tooltip)

    def set_unit(self, unit: str):
        self._unit.setText(unit)


class Dashboard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # 1. 状态行（弱化）
        status = QHBoxLayout()
        status.setSpacing(10)
        self._hook_status = QLabel('🟢 统计中')
        status.addWidget(self._hook_status)
        self._hook_info = QLabel('')
        self._hook_info.setStyleSheet('font-size:11px;')
        status.addWidget(self._hook_info)
        status.addStretch(1)
        root.addLayout(status)

        # 2. 等级区
        head = QHBoxLayout()
        head.setSpacing(12)
        self._level_badge = QLabel('Lv.1')
        head.addWidget(self._level_badge)
        col = QVBoxLayout()
        col.setSpacing(2)
        self._band_label = QLabel('')
        self._band_label.setStyleSheet('font-size:12px;')
        col.addWidget(self._band_label)
        self._level_bar = LevelBar()
        col.addWidget(self._level_bar)
        self._exp_text = QLabel('')
        self._exp_text.setStyleSheet('font-size:11px;')
        col.addWidget(self._exp_text)
        head.addLayout(col, 1)
        self._streak_label = QLabel('🔥 连签 0 天')
        self._streak_label.setStyleSheet('font-weight:700; font-size:14px;')
        head.addWidget(self._streak_label, 0, Qt.AlignTop)
        root.addLayout(head)

        # 3. Hero 大数字卡（视觉焦点）
        hero_grid = QGridLayout()
        hero_grid.setSpacing(12)
        self._heroes = {}
        specs = [
            ('doc', '今日有效字数', 'valid', 'chars', ''),
            ('zap', '平均速度', 'avg_tw', 'speed', 'tw/分'),
            ('target', '正确率', 'accuracy', 'acc', ''),
        ]
        for i, (ic, label, key, kind, unit) in enumerate(specs):
            card = _HeroCard(ic, label, kind, unit)
            self._heroes[key] = card
            hero_grid.addWidget(card, 0, i)
        root.addLayout(hero_grid)

        # 4. 次级指标 chips（4 列 2 行）
        self._chips = {}
        chips_grid = QGridLayout()
        chips_grid.setSpacing(6)
        chips = [
            ('今日输入', 'typed'), ('今日删除', 'deleted'),
            ('改写率', 'revision'), ('今日 tw', 'tw'),
            ('预测汉字/分', 'pred_hanzi'), ('预测字母/分', 'pred_letters'),
            ('活跃时长', 'minutes'), ('等级经验', 'exp'),
        ]
        for i, (name, key) in enumerate(chips):
            cell = QWidget()
            cv = QVBoxLayout(cell)
            cv.setContentsMargins(10, 6, 10, 6)
            cv.setSpacing(0)
            n = QLabel(name)
            n.setStyleSheet('font-size:10px;')
            val = QLabel('—')
            val.setStyleSheet('font-size:16px; font-weight:700;')
            cv.addWidget(n)
            cv.addWidget(val)
            self._chips[key] = val
            self._chip_names = getattr(self, '_chip_names', []) + [n]
            self._chip_cards = getattr(self, '_chip_cards', []) + [cell]
            chips_grid.addWidget(cell, i // 4, i % 4)
        chips_grid.setColumnStretch(0, 1)
        chips_grid.setColumnStretch(1, 1)
        chips_grid.setColumnStretch(2, 1)
        chips_grid.setColumnStretch(3, 1)
        root.addLayout(chips_grid)

        # 5. 终身汇总条
        self._life_bar = QFrame()
        self._life_bar.setFrameShape(QFrame.StyledPanel)
        lv = QHBoxLayout(self._life_bar)
        lv.setContentsMargins(14, 8, 14, 8)
        self._life_label = QLabel('')
        self._life_label.setStyleSheet('font-size:12px;')
        lv.addWidget(self._life_label)
        root.addWidget(self._life_bar)

        # 6. 迷你曲线
        self._mini_title = QLabel('✨ 今日逐分钟 tw 曲线')
        self._mini_title.setStyleSheet('margin-top:2px;')
        root.addWidget(self._mini_title)
        self._mini_plot = pg.PlotWidget()
        self._mini_plot.setFixedHeight(120)
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

    # ---------- 主题 ----------
    def apply_theme(self):
        self._hook_status.setStyleSheet(
            f'color:{P.success}; font-weight:700; font-size:12px;')
        self._hook_info.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._level_badge.setStyleSheet(
            f'font-size:26px; font-weight:900; color:{P.badge_text};'
            f'background:{P.badge_bg}; border-radius:12px;'
            f'padding:4px 14px; border:2px solid {P.badge_border};')
        self._band_label.setStyleSheet(f'color:{P.muted}; font-size:12px;')
        self._exp_text.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._streak_label.setStyleSheet(
            f'color:{P.warn}; font-weight:700; font-size:14px;')
        for n in getattr(self, '_chip_names', []):
            n.setStyleSheet(f'color:{P.muted}; font-size:10px;')
        for cell in self._chip_cards:
            # cell 是普通 QWidget，QSS 选择器必须为空（作用于自身），
            # 写 'QFrame {...}' 不会匹配 QWidget（曾导致 chips 无卡片背景）
            cell.setStyleSheet(
                f'background:{P.card_bg}; border-radius:12px;'
                f' border:1px solid {P.card_border};')
        for key, card in self._heroes.items():
            card.apply_theme()
        self._life_bar.setStyleSheet(
            f'QFrame {{ background:{P.card_bg}; border-radius:12px;'
            f' border:1px solid {P.card_border}; }}')
        self._life_label.setStyleSheet(f'color:{P.muted}; font-size:12px;')
        self._mini_title.setStyleSheet(f'color:{P.muted}; margin-top:2px;')
        self._hint.setStyleSheet(f'color:{P.faint}; font-size:11px;')
        self._mini_plot.setBackground(P.mini_bg)
        self._mini_curve.setPen(pg.mkPen(P.accent, width=2))

    # ---------- 钩子状态 ----------
    def resume_animations(self, on: bool) -> None:
        """窗口可见性变化时暂停/恢复扫光动画（托盘驻留时省电）。"""
        self._level_bar.set_visible_anim(on)

    def set_hook_status(self, ok: bool):
        self._hook_status.setText('🟢 统计中（键盘钩子正常）' if ok
                                  else '🔴 键盘钩子未运行，不会统计打字——请重启应用')
        self._hook_status.setStyleSheet(
            f'color:{"#059669" if ok else "#dc2626"}; font-weight:700; font-size:12px;')

    def set_hook_info(self, event_count: int, ime_readable: bool, errs=None,
                      tsf_ok: bool = False):
        text = f'钩子已捕获 {event_count:,} 个按键事件（本次运行）'
        if tsf_ok:
            text += ' ｜ TSF 中文精确计数已启用'
        elif not ime_readable:
            text += ' ｜ 输入法组字状态读取不可用（TSF 输入法），中文按按键近似计数'
        if errs:
            text += f' ｜ ⚠ 回调异常 {len(errs)} 条（悬停查看详情）'
            self._hook_info.setToolTip('\n'.join(errs[:3]))
        else:
            self._hook_info.setToolTip('')
        self._hook_info.setText(text)

    # ---------- 等级 ----------
    def set_level_colors(self, colors):
        self._level_bar.set_colors(colors)

    def refresh(self, snap, level, progress, band, streak, unit, exp=0):
        # 等级区
        self._level_badge.setText(f'Lv.{level}')
        self._band_label.setText(f'称号：{band}　·　{unit} 单位')
        self._streak_label.setText(f'🔥 连签 {streak} 天')
        self._level_bar.set_progress(progress)
        self._exp_text.setText(f'经验进度 {round(progress * 100)}%')
        self._exp_value = exp

        # Hero 卡
        hero_valid = _num(snap['valid'])
        self._heroes['valid'].set_value(hero_valid,
                                        '今日有效字数 = 输入 − 删除')
        avg = snap['avg_tw']
        self._heroes['avg_tw'].set_value(
            f'{avg:.1f}' if avg is not None else '—',
            f'平均速度（{unit}/分），按日统计不并入终身总计')
        self._heroes['avg_tw'].set_unit(f'{unit}/分' if avg is not None else '')
        acc = snap['accuracy']
        self._heroes['accuracy'].set_value(
            f'{acc * 100:.1f}%' if acc is not None else '—',
            '正确率 = 有效 ÷ 输入（删除按键计入失误），悬停见口径')
        self._heroes['accuracy'].set_unit('')

        # chips
        self._chips['typed'].setText(_num(snap['typed']))
        self._chips['deleted'].setText(_num(snap['deleted']))
        rev = snap['deleted'] / snap['typed'] if snap['typed'] else None
        rev_lab = self._chips['revision']
        rev_lab.setText(f'{rev * 100:.1f}%' if rev is not None else '—')
        rev_lab.setToolTip('改写率 = 删除 ÷ 输入；写作场景比正确率更诚实')
        self._chips['tw'].setText(_num(snap['tw']))
        self._chips['pred_hanzi'].setText(
            f'{tw_to_hanzi_per_min(avg):.1f}' if avg is not None else '—')
        self._chips['pred_letters'].setText(
            f'{tw_to_letters_per_min(avg):.1f}' if avg is not None else '—')
        self._chips['minutes'].setText(_num(snap['minutes']))
        self._chips['exp'].setText(_num(self._exp_value if hasattr(self, '_exp_value') else 0))

        # 终身汇总条
        self._life_label.setText(
            f'🏅 终身　累计输入 {_num(snap["lifetime_typed"])} 字　·　'
            f'有效 {_num(snap["lifetime_valid"])} 字　·　'
            f'tw {_num(snap["lifetime_tw"])}　·　'
            f'活跃 {_num(snap["lifetime_minutes"])} 分钟')

        # 迷你曲线
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
