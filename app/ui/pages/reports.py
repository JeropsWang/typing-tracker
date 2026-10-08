"""报表页（M2）：趋势分析 / 打卡日历 / 时段分布 / 周月报。

数据全部来自 daily_stats 与 minute_stats（日快照、分钟快照），
正确率与平均速度均为按日/按段指标，不涉及终身总计。

视觉：按交接设计稿（design/stats-1440.png）把图表直接画在奶油纸张上：
- 图表区背景透明，露出纸张本身（实测设计稿绘图区与纸张同为 #EEE5D6，
  绘图区内无网格线）；
- **保留 y 轴读数与真实单位**（口径更新 DECISIONS.md 第 2 条 / catalog.json
  `confirmed.statistics.showYAxisValues`）：有效字数写「字」、速度写「tw/分」、
  比例图写「%」；刻度由真实数据自动取值，不为外观固定假范围；
- 网格淡化但读数保留，避免与图例/序列开关重复同一组数字；
- 序列线细而克制（1.6px、0.92 不透明度），序列色仍取主题 charts.json
  的原值，仅在与纸面对比度不足时按色相向墨色加深；
- 图例由序列开关本身承担（设计稿图例即三个复选框），不在图内重复一块图例框。
- 页头换成交付的转曲艺术标题 `ArtHeading('stats')`，副标题仍是普通可读文字。
- 绘图区高度用「上下限区间 + 尺度系数（`design.scale_factor`）」而不是固定像素。
"""
from __future__ import annotations

from datetime import date, timedelta

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
)

from ...core.classifier import tw_to_hanzi_per_min, tw_to_letters_per_min
from ..dashboard import _num
from ..palette import P
from ..widgets import design as _design
from ..widgets.design import (
    FONT_BODY, FONT_LABEL, ArtHeading, Disclosure, PaperPage, is_compact, rgba,
)


def scale_for(width: int, height: int) -> float:
    """共享层尺度系数 `design.scale_factor`（唯一口径，不自己另造 token）。"""
    shared = getattr(_design, 'scale_factor', None)
    if callable(shared):
        try:
            return float(shared(width, height))
        except Exception:
            pass
    return max(0.85, min(1.15, min(width / 1440.0, height / 1024.0)))


def _interp(low: int, high: int, scale: float) -> int:
    """在上下限区间里按尺度系数取值（0.85 → low，1.00 → high）。"""
    t = max(0.0, min(1.0, (float(scale) - 0.85) / 0.15))
    return int(round(low + (high - low) * t))


# 默认图表配色（主题 charts.json 未注册时的兜底，apply_chart_palette 会覆盖）
C_SPEED = '#3b82f6'
C_ACC = '#10b981'
C_CHARS = '#f59e0b'
C_EMPTY = '#e5e7eb'
C_LEVELS = ['#dbeafe', '#93c5fd', '#60a5fa', '#2563eb', '#1e40af']

# 纸张上图表的几何（上下限区间，由尺度系数插值；字号不缩）
# 设计稿实测：绘图区净高约 250px、整块约 297px（1440 档），紧凑档取区间下限。
PLOT_HEIGHT_MIN, PLOT_HEIGHT_MAX = 230, 300
HM_CELL_MIN, HM_CELL_MAX = 13, 16
HM_MIN_HEIGHT_MIN, HM_MIN_HEIGHT_MAX = 120, 176
FIELD_WIDTH_MIN, FIELD_WIDTH_MAX = 200, 260
HOURS_HEIGHT_MIN, HOURS_HEIGHT_MAX = 150, 176

MIN_CONTRAST = 4.2          # 折线/柱体与纸张的最小对比度（设计稿示例线 ≈4.9:1）
LINE_WIDTH = 1.6            # 序列线宽：设计稿为细线，不要用 2px 以上压过纸面
LINE_ALPHA = 0.92           # 序列线不透明度：压低饱和感，避免"重线"
GRID_ALPHA = 0.10           # 网格：设计稿绘图区内几乎不可见
AXIS_ALPHA = 0.32           # 轴线/刻度：设计稿只有极淡的底部基线
METRIC_VALUE_FONT = 18      # 关键指标数字（设计稿 18px；页级大数字 32 只用于今日页）


def _dstr(d: date) -> str:
    return d.isoformat()


def _relative_luminance(color) -> float:
    c = QColor(color)
    channels = []
    for value in (c.redF(), c.greenF(), c.blueF()):
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(a, b) -> float:
    """WCAG 对比度（1~21）。"""
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _on_paper(color: str, background: str, minimum: float = MIN_CONTRAST) -> str:
    """纸张上的图形色：对比度不足时向墨色加深，仍保留主题色相/明度关系。"""
    if _contrast(color, background) >= minimum:
        return color
    target = P.paper_text
    best = QColor(target)
    for step in range(1, 101):
        t = step / 100
        c = QColor(color)
        c.setRedF(min(1.0, c.redF() * (1 - t) + QColor(target).redF() * t))
        c.setGreenF(min(1.0, c.greenF() * (1 - t) + QColor(target).greenF() * t))
        c.setBlueF(min(1.0, c.blueF() * (1 - t) + QColor(target).blueF() * t))
        if _contrast(c.name(), background) >= minimum:
            return c.name()
        best = c
    return best.name()


def _dim(color: str, alpha: float) -> QColor:
    """主题色按透明度稀释后用于纸面（极淡的轴线/基线）。"""
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class _InsightPanel(QFrame):
    """趋势区的对齐容器：**无底板**。

    设计稿里折线直接画在奶油纸上（绘图区与纸张同为 #EEE5D6），
    所以这里只负责内边距与标题/图表/开关的竖向对齐，不画任何底色、圆角或描边，
    避免出现"图表背了一块灰板"或一圈硬边。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('paperInsight')
        self.setAttribute(Qt.WA_StyledBackground, True)

    def apply_theme(self, compact: bool = False, scale: float = 1.0) -> None:
        pad = _interp(12, 18, scale) if not compact else 12
        self.setStyleSheet('QFrame#paperInsight { background: transparent;'
                           ' border: none; border-radius: 0px; }')
        layout = self.layout()
        if layout is not None:
            layout.setContentsMargins(pad, pad, pad, pad)


class ReportsPage(QWidget):
    def __init__(self, repo, engine, balance, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._engine = engine
        self._balance = balance
        self._hm_last_build = 0.0
        self._hm_ready = False
        self._compact = is_compact(*self._size_hint_default())
        self._scale = scale_for(*self._size_hint_default())

        # 主题可覆盖的配色（apply_chart_palette 更新；保持主题注入的原值）
        self._curve_colors = {'speed': C_SPEED, 'acc': C_ACC, 'chars': C_CHARS}
        self._hm_levels = list(C_LEVELS)
        self._hm_empty_color = C_EMPTY

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 页面骨架：纸张靠左（最大 1100/760 宽），右侧留给交付插画（与其它页一致）
        self._page = PaperPage(self, compact=self._compact)
        self._page.body.setSpacing(16)
        self._paper = self._page.paper
        self._paper_body = self._page.body
        self._scroll = self._page.scroll
        root.addWidget(self._page)

        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self._build_head(header_layout)
        self._page.set_header(header)
        self._build_controls(self._paper_body)
        self._build_trend(self._paper_body)
        self._build_secondary(self._paper_body)
        self._paper_body.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(10_000)

    # ---------- 构造 ----------
    @staticmethod
    def _size_hint_default():
        return (1440, 1024)

    def _build_head(self, parent):
        # 交付的转曲艺术标题（stats.svg）；副标题仍是普通可读文字（DECISIONS.md 第 5 条）
        self._heading = ArtHeading('stats', '按真实记录回顾节奏，让练习有迹可循。')
        parent.addWidget(self._heading)

    def _build_controls(self, parent):
        """时间范围 + 关键指标（同一行，无数据用 —）。"""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(24)

        self._range_combo = QComboBox()
        self._range_combo.setAccessibleName('时间范围')
        self._range_combo.setToolTip('选择统计的时间范围')
        for label, n in [('最近 7 天', 7), ('最近 30 天', 30), ('最近 90 天', 90)]:
            self._range_combo.addItem(label, n)
        self._range_field = _RangeField(self._range_combo)
        row.addWidget(self._range_field, 0, Qt.AlignTop)

        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFrameShadow(QFrame.Plain)
        divider.setFixedWidth(1)
        self._control_divider = divider
        row.addWidget(divider)

        self._metrics = _MetricRow()
        row.addWidget(self._metrics, 1, Qt.AlignTop)
        parent.addLayout(row)

        self._range_combo.currentIndexChanged.connect(lambda *_: self.refresh())

    def _build_trend(self, parent):
        """主图表：趋势三视角 + 三条序列开关 + 真实指标说明。"""
        self._panel = _InsightPanel()
        body = QVBoxLayout(self._panel)
        body.setSpacing(12)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(16)
        self._trend_title = QLabel('每日有效输入')
        self._trend_title.setProperty('textRole', 'paperField')
        # 设计稿图表标题是正文尺寸（实测约 15px 字高），不是 14px 小标签
        self._trend_title.setStyleSheet(f'font-size: {FONT_BODY}px; font-weight: 400;')
        head.addWidget(self._trend_title)
        self._view_combo = QComboBox()
        self._view_combo.setAccessibleName('趋势视角')
        self._view_combo.setToolTip('切换速度换算视角；正确率与有效字数不受影响')
        for label, factor in [('tw/分', 1.0), ('汉字/分', 0.5), ('字母/分', 1.0)]:
            self._view_combo.addItem(label, factor)
        self._view_combo.currentIndexChanged.connect(lambda *_: self.refresh())
        head.addWidget(self._view_combo)
        head.addStretch(1)
        body.addLayout(head)

        self._plot = pg.PlotWidget()
        self._plot.setAccessibleName('每日趋势图表')
        self._plot.setBackground(None)
        self._plot.setMenuEnabled(False)
        self._plot.setMinimumHeight(PLOT_HEIGHT_MIN)
        self._plot.setMaximumHeight(PLOT_HEIGHT_MAX)
        # 设计稿的图例就是下面那排序列开关，图内不再叠一块图例框
        self._plot.setAntialiasing(True)
        body.addWidget(self._plot, 1)

        # 空态：图表区留白（不绘制伪趋势），只在纸面中央放一句说明
        self._plot_empty = QLabel('', self._plot)
        self._plot_empty.setAlignment(Qt.AlignCenter)
        self._plot_empty.setWordWrap(True)
        self._plot_empty.setProperty('textRole', 'paperMuted')
        self._plot_empty.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._plot_empty.setVisible(False)

        toggles = QHBoxLayout()
        toggles.setContentsMargins(0, 0, 0, 0)
        toggles.setSpacing(20)
        self._checkboxes = {}
        self._curves = {}
        for key, name in [('speed', '平均速度'), ('acc', '正确率'), ('chars', '有效字数')]:
            cb = QCheckBox(name)
            cb.setChecked(True)
            cb.setProperty('paperCheck', True)
            cb.setAccessibleName(name)
            cb.toggled.connect(lambda *_: self.refresh())
            toggles.addWidget(cb)
            self._checkboxes[key] = cb
            self._curves[key] = self._plot.plot(
                [], [], pen=pg.mkPen(self._curve_colors[key], width=LINE_WIDTH), name=name)
        toggles.addStretch(1)
        self._pred_label = QLabel('')
        self._pred_label.setProperty('textRole', 'paperMuted')
        toggles.addWidget(self._pred_label)
        body.addLayout(toggles)

        self._trend_note = QLabel('')
        self._trend_note.setWordWrap(True)
        self._trend_note.setProperty('textRole', 'paperMuted')
        body.addWidget(self._trend_note)

        parent.addWidget(self._panel)

    def _build_secondary(self, parent):
        """次级区：时段分布 / 热力图 / 周月报，折叠承载，紧凑尺寸不消失。"""
        self._sec_title = QLabel('更多视图')
        self._sec_title.setProperty('textRole', 'paperField')
        parent.addWidget(self._sec_title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(4)
        self._hours_disc = Disclosure('每小时分布')
        self._build_hours(self._hours_disc.content)
        self._hm_disc = Disclosure('热力图')
        self._build_heatmap(self._hm_disc.content)
        grid.addWidget(self._hours_disc, 0, 0)
        grid.addWidget(self._hm_disc, 0, 1)
        # 设计稿次级条：两个入口之间留白明显，热量图入口偏左（约在 1/3 处）
        grid.setColumnStretch(0, 5)
        grid.setColumnStretch(1, 4)
        # 设计稿的次级条紧贴图表区（约 18px），标题与入口行之间再收一档
        parent.addSpacing(-8)
        parent.addLayout(grid)

        self._report_disc = Disclosure('周月报')
        self._build_reports(self._report_disc.content)
        parent.addWidget(self._report_disc)

    # ---------- 统一刷新入口 ----------
    def refresh(self, *_):
        if not self.isVisible():
            return
        self._refresh_trend()
        self._refresh_hours()
        self._refresh_reports()
        self._refresh_heatmap()
        self._sync_plot_empty_geometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_plot_empty_geometry()

    def _invalidate_heatmap(self) -> None:
        """热力图需要整体重建（主题/紧凑度变化或首次进入页面）。"""
        self._hm_last_build = 0.0
        self._hm_ready = False

    def set_compact(self, compact: bool) -> None:
        """按 900x640 档降级内边距与控件高度，字号不变（尺寸仍由区间决定）。"""
        compact = bool(compact)
        self._compact = compact
        self._page.set_compact(compact)
        self._range_field.set_compact(compact)
        self._panel.apply_theme(compact, self._scale)
        self._paper_body.setSpacing(12 if compact else 16)
        self._heading.subtitle.setVisible(not compact)
        self._sync_scale()
        self._invalidate_heatmap()
        self._apply_chart_style()
        self._apply_paper_control_style()
        self.refresh()

    def _sync_scale(self) -> None:
        """绘图区/热力图/下拉宽度按尺度系数在上下限区间内取值（字号不变）。"""
        scale = self._scale
        floor = PLOT_HEIGHT_MIN if self._compact else _interp(
            PLOT_HEIGHT_MIN, PLOT_HEIGHT_MAX, scale)
        ceiling = floor if self._compact else PLOT_HEIGHT_MAX
        if self._plot.minimumHeight() != floor:
            self._plot.setMinimumHeight(floor)
        if self._plot.maximumHeight() != ceiling:
            self._plot.setMaximumHeight(ceiling)
        height = HOURS_HEIGHT_MIN if self._compact else _interp(
            HOURS_HEIGHT_MIN, HOURS_HEIGHT_MAX, scale)
        # 同时是下限与上限：折叠区展开后不去抢纸张余量（读数密度不变）
        self._hours_plot.setMinimumHeight(height)
        self._hours_plot.setMaximumHeight(max(height, HOURS_HEIGHT_MAX))
        hm = HM_MIN_HEIGHT_MIN if self._compact else _interp(
            HM_MIN_HEIGHT_MIN, HM_MIN_HEIGHT_MAX, scale)
        self._hm_scroll.setMinimumHeight(hm)
        self._hm_cell_size = (HM_CELL_MIN if self._compact
                              else _interp(HM_CELL_MIN, HM_CELL_MAX, scale))
        self._range_field.set_width(_interp(FIELD_WIDTH_MIN, FIELD_WIDTH_MAX, scale))

    def apply_theme(self):
        """主题切换：重算纸张上的文字/图形颜色，并重绘图表与控件。"""
        for widget in (self._trend_title, self._sec_title, self._pred_label):
            widget.setProperty('textRole', 'paperField')
        for widget in (self._trend_note, self._hm_title, self._hours_title,
                       self._cmp_hint, self._cmp_label):
            widget.setProperty('textRole', 'paperMuted')
        self._panel.apply_theme(self._compact, self._scale)
        self._invalidate_heatmap()
        self._apply_chart_style()
        self._apply_paper_control_style()
        self.refresh()

    def apply_chart_palette(self, palette: dict):
        """主题切换时读取 charts.json：序列色保持原值，仅供图表取用。"""
        self._curve_colors = {
            'speed': palette.get('speed', C_SPEED),
            'acc': palette.get('acc', C_ACC),
            'chars': palette.get('chars', C_CHARS),
        }
        self._hm_levels = list(palette.get('levels', C_LEVELS))
        self._hm_empty_color = palette.get('empty', C_EMPTY)
        self._invalidate_heatmap()
        self._apply_chart_style()
        self.refresh()

    # ---------- 纸面配色 ----------
    def _display_color(self, color: str) -> str:
        """序列色在奶油纸张上的可见版本（对比度不足时加深，保留色相）。"""
        return _on_paper(color, P.paper)

    def _apply_chart_style(self):
        """把图表压回纸面：透明背景、极淡轴线、淡化网格、细序列线，**保留 y 轴读数**。

        口径更新（DECISIONS.md 第 2 条 + catalog.json
        `confirmed.statistics.showYAxisValues = true`）：
        - 趋势图与时段图都**保留真实刻度与单位**（有效字数「字」、速度「tw/分」、
          比例「%」），刻度范围仍由真实数据自动取值，不为外观固定假范围；
        - 网格淡化（`GRID_ALPHA`）以保留读数，但不再同时叠加重复的数值标签；
        - 绘图区背景透明（含 viewport 的 autoFill 调色板填充），露出纸张；
        - 折线细且低饱和（1.6px、0.92），序列色取主题 charts.json 原值。
        """
        if not hasattr(self, '_plot'):
            return
        accent = self._display_color(self._curve_colors['speed'])
        grid_pen = pg.mkPen(_dim(P.paper_muted, GRID_ALPHA), width=1)
        axis_pen = pg.mkPen(_dim(P.paper_muted, AXIS_ALPHA), width=1)
        text_pen = pg.mkPen(QColor(P.paper_muted))
        for plot in (self._plot, self._hours_plot):
            plot.setBackground(None)
            self._make_plot_transparent(plot)
            # 网格淡化但保留（y 轴要能读数）；不再把网格完全关掉
            plot.showGrid(x=False, y=True, alpha=GRID_ALPHA)
            for name in ('bottom', 'left'):
                axis = plot.getAxis(name)
                axis.setPen(axis_pen)
                axis.setTextPen(text_pen)
                axis.setTickPen(axis_pen)
                axis.setStyle(tickTextOffset=10 if name == 'bottom' else 6,
                              tickLength=0)
                # 轴标签文字：pyqtgraph 版本间 labelStyle 有属性/方法两种形态
                style = axis.labelStyle() if callable(axis.labelStyle) else dict(axis.labelStyle)
                style['color'] = P.paper_muted
                axis.setLabel(axis.labelText, **style)
                if name == 'left':
                    # y 轴必须可见：轴线、刻度与读数一起保留（口径：恢复 y 轴数值）
                    axis.setWidth(52)
                    label_item = getattr(axis, 'label', None)
                    if label_item is not None:
                        label_item.setVisible(True)
                        # 轴标题水平摆放：pyqtgraph 默认竖排会把「tw/分」拆成
                        # 单个字符叠在左边缘，读数挤成一列不可读
                        label_item.setRotation(0)
            # 关闭 SI 前缀：日期/小时刻度会被写成「(x0.001)」这类与单位无关的缩放提示
            for name in ('bottom', 'left'):
                axis = plot.getAxis(name)
                if hasattr(axis, 'enableAutoSIPrefix'):
                    axis.enableAutoSIPrefix(False)
            plot.getPlotItem().showAxis('left')
            self._show_axis_text(plot)
        # 曲线：细线 + 低饱和（主题原值只在纸面对比度不足时按色相加深）
        for key, curve in self._curves.items():
            color = QColor(self._display_color(self._curve_colors[key]))
            color.setAlphaF(LINE_ALPHA)
            curve.setPen(pg.mkPen(color, width=LINE_WIDTH))
        if hasattr(self, '_hours_bar'):
            bar = QColor(accent)
            bar.setAlphaF(LINE_ALPHA)
            self._hours_bar.setOpts(brush=pg.mkBrush(bar), pen=pg.mkPen(None))
        if hasattr(self, '_hours_zero'):
            self._hours_zero.setPen(grid_pen)
        self._apply_checkbox_style()

    @staticmethod
    def _show_axis_text(plot) -> None:
        """确保 y 轴读数与轴标题可见（口径：统计页保留真实刻度与单位）。

        `AxisItem.setLabel` 会把之前隐藏的标签重新显示出来，但在某些 pyqtgraph
        版本里 `hideAxis` 的状态会残留，所以每次套用样式后再显式 show 一次。
        """
        for name in ('left', 'bottom'):
            axis = plot.getAxis(name)
            label_item = getattr(axis, 'label', None)
            if label_item is not None:
                label_item.setVisible(True)
            for child in (getattr(axis, 'textItems', None) or []):
                if hasattr(child, 'setVisible'):
                    child.setVisible(True)

    # 兼容旧调用点：语义已改为「显示 y 轴」，保留旧方法名以免外部脚本引用报错
    _hide_axis_text = _show_axis_text

    def _sync_plot_empty_geometry(self) -> None:
        """空态说明放在绘图区中央（纸张上的浅色文字，不拦截鼠标）。"""
        if not hasattr(self, '_plot_empty'):
            return
        rect = self._plot.rect()
        width = max(0, rect.width() - 40)
        self._plot_empty.setFixedWidth(width)
        self._plot_empty.adjustSize()
        self._plot_empty.setGeometry(
            rect.x() + 20, rect.y() + max(0, (rect.height() - self._plot_empty.height()) // 2),
            width, self._plot_empty.height())

    @staticmethod
    def _make_plot_transparent(plot) -> None:
        """让 pyqtgraph 视图真正露出纸张。

        `setBackground(None)` 只把背景刷设为 NoBrush，而未设背景刷时
        QGraphicsView 会用 viewport 调色板的 Window 色填充整个视口
        （实测不透明 #EFEFEF，纸上就出现一块浅灰底）。把 viewport 的
        Window 色设为全透明即可让纸张色透上来；NoRole / autoFillBackground
        都不影响 QGraphicsView 自身的这次填充。
        """
        viewport = plot.viewport()
        if viewport is None:
            return
        palette = viewport.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        viewport.setPalette(palette)
        viewport.setAutoFillBackground(False)
        plot.setAutoFillBackground(False)

    def _apply_checkbox_style(self):
        """纸张上的复选框 = 设计稿的图例：浅描边 + 序列色填充，字色跟随纸张正文。"""
        css = (
            f'QCheckBox[paperCheck="true"] {{ color: {P.paper_text}; font-size: {FONT_LABEL}px;'
            f' spacing: 8px; }}'
            f'QCheckBox[paperCheck="true"]::indicator {{ width: 16px; height: 16px;'
            f' border: 1px solid {rgba(P.paper_text, 0.22)}; border-radius: 3px;'
            f' background: {rgba(P.paper_text, 0.05)}; }}'
        )
        for key, cb in self._checkboxes.items():
            color = self._display_color(self._curve_colors[key])
            cb.setStyleSheet(
                css + f'QCheckBox[paperCheck="true"]::indicator:checked {{'
                      f' background: {rgba(color, 0.72)}; border: 1px solid {rgba(color, 0.95)}; }}')

    def _apply_paper_control_style(self):
        """纸张上的下拉/按钮高度：44px，紧凑 40px（字号不变）。

        设计稿里时间范围下拉是"纸面加深一档"的填充（#DED4CB ≈ 10% 墨色），
        不是白色输入框；这里跟随纸面，避免出现一块白色方框。
        """
        height = 40 if self._compact else 44
        combo_css = (
            f'QFrame[paperSurface="true"] QComboBox {{ background: {rgba(P.paper_text, 0.10)};'
            f' color: {P.paper_text}; border: none; border-radius: 8px;'
            f' padding: 8px 12px; font-size: {FONT_BODY}px; }}'
        )
        for control in (self._range_combo, self._view_combo):
            control.setFixedHeight(height)
            control.setStyleSheet(combo_css)
        for disc in (self._hours_disc, self._hm_disc, self._report_disc):
            disc.toggle.setMinimumHeight(height)

    def _unit(self) -> str:
        return self._repo.get_setting('unit_name', self._balance['unit']['name'])

    # ---------- 关键指标 ----------
    def _refresh_metrics(self, summary, unit):
        if not summary:
            values = {'valid': '—', 'tw': '—', 'speed': '—', 'acc': '—'}
        else:
            speed = summary.get('avg_speed')
            acc = summary.get('accuracy')
            values = {
                'valid': _num(summary.get('valid')),
                'tw': _num(summary.get('tw')),
                'speed': f'{speed:.1f} {unit}/分' if speed else '—',
                'acc': f'{acc * 100:.1f}%' if acc is not None else '—',
            }
        self._metrics.set_values(values)

    # ---------- 主图表：趋势分析 ----------
    def _refresh_trend(self):
        today = date.fromisoformat(self._engine.current_day())
        n = self._range_combo.currentData() or 7
        start = today - timedelta(days=n - 1)
        days = self._repo.get_daily_range(_dstr(start), _dstr(today))
        self._refresh_metrics(self._repo.get_summary(_dstr(start), _dstr(today)), self._unit())

        factor = self._view_combo.currentData() or 1.0
        view = self._view_combo.currentText()
        label = '汉字/分' if factor == 0.5 else ('tw/分' if view == 'tw/分' else '字母/分')
        self._plot.setLabel('bottom', '日期')
        # y 轴保留真实单位（口径：tw/分、字/分、%），刻度范围仍由数据自动取值
        self._plot.setLabel('left', label, color=P.paper_muted)
        self._show_axis_text(self._plot)
        self._trend_title.setText('每日有效输入 · 趋势' if view == 'tw/分'
                                 else f'每日趋势 · {view} 视角')

        xs = list(range(len(days)))
        step = max(1, len(days) // 8)
        ticks = [[(i, d['date'][5:]) for i, d in enumerate(days) if i % step == 0]]
        self._plot.getAxis('bottom').setTicks(ticks)

        series = {
            'speed': [float('nan') if d['avg_tw'] is None else d['avg_tw'] * factor for d in days],
            'acc': [float('nan') if d['accuracy'] is None else d['accuracy'] * 100 for d in days],
            'chars': [d['valid_chars'] for d in days],
        }
        for key, curve in self._curves.items():
            if self._checkboxes[key].isChecked():
                curve.setData(xs, series[key])
            else:
                curve.setData([], [])
        # y 轴范围按**真实数据**取：有数据时自动量程；数据全为 0 或空时给 0..1，
        # 避免 pyqtgraph 在平坦序列上算出 0.6/0.8 这类与数据不符的刻度。
        values = [v for key, s in series.items()
                  if self._checkboxes[key].isChecked()
                  for v in s if v == v]
        if values and (max(values) != min(values) or max(values) > 0):
            self._plot.enableAutoRange(axis='y', enable=True)
        else:
            self._plot.setYRange(0, 1, padding=0)

        vals = [d['avg_tw'] for d in days if d['avg_tw'] is not None]
        unit = self._unit()
        self._plot_empty.setVisible(not days)
        self._plot_empty.setText('' if days else
                                 f'{_dstr(start)} ~ {_dstr(today)}\n暂无每日记录，不绘制趋势')
        self._sync_plot_empty_geometry()
        if not days:
            self._pred_label.setText('')
            self._trend_note.setText(f'{_dstr(start)} ~ {_dstr(today)} 暂无每日记录，'
                                     '开始练习后这里会出现真实曲线。')
        else:
            self._trend_note.setText(
                f'{_dstr(start)} ~ {_dstr(today)} 共 {len(days)} 天有日快照；'
                '列表按真实记录绘制，缺记录的日期留空。')
            if vals:
                m = sum(vals) / len(vals)
                self._pred_label.setText(
                    f'平均 {m:.1f}{unit}/分 ｜ 预测汉字 {tw_to_hanzi_per_min(m):.1f} 字/分')
            else:
                self._pred_label.setText('区间内暂无速度记录')

    # ---------- 次级：时段分布 ----------
    def _build_hours(self, content):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self._hours_title = QLabel('')
        self._hours_title.setWordWrap(True)
        self._hours_title.setProperty('textRole', 'paperMuted')
        lay.addWidget(self._hours_title)

        self._hours_plot = pg.PlotWidget()
        self._hours_plot.setAccessibleName('24 小时时段分布图表')
        self._hours_plot.setBackground(None)
        self._hours_plot.setMenuEnabled(False)
        self._hours_plot.setMinimumHeight(HOURS_HEIGHT_MIN)
        self._hours_plot.setLabel('bottom', '小时')
        # y 轴保留真实单位（tw）
        self._hours_plot.setLabel('left', 'tw')
        self._hours_bar = pg.BarGraphItem(x=[], height=[], width=0.7, brush=pg.mkBrush(self._curve_colors['speed']))
        self._hours_plot.addItem(self._hours_bar)
        self._hours_zero = pg.InfiniteLine(angle=0, pos=0, pen=pg.mkPen(_dim(P.paper_muted, 0.55)))
        self._hours_plot.addItem(self._hours_zero)
        lay.addWidget(self._hours_plot)

        self._hours_empty = QLabel('')
        self._hours_empty.setWordWrap(True)
        self._hours_empty.setProperty('textRole', 'paperMuted')
        self._hours_empty.setVisible(False)
        lay.addWidget(self._hours_empty)
        content.addWidget(body)

    def _refresh_hours(self):
        today = date.fromisoformat(self._engine.current_day())
        start = today - timedelta(days=6)
        rows = self._repo.get_hourly_stats(_dstr(start), _dstr(today))
        tw = [0] * 24
        for r in rows:
            h = int(r['hour'])
            if 0 <= h <= 23:
                tw[h] = r['tw'] or 0
        has_data = any(v > 0 for v in tw)
        self._hours_bar.setOpts(x=list(range(24)), height=tw, width=0.7)
        self._hours_plot.getAxis('bottom').setTicks([[(i, str(i)) for i in range(0, 24, 3)]])
        self._hours_empty.setVisible(not has_data)
        self._hours_empty.setText(
            f'{_dstr(start)} ~ {_dstr(today)} 没有分钟级记录，无法绘制时段分布；'
            '开始练习后按小时统计。' if not has_data else '')
        self._hours_title.setText(f'近 7 天时段分布（{_dstr(start)} ~ {_dstr(today)}）')
        self._show_axis_text(self._hours_plot)

    # ---------- 次级：打卡日历（GitHub 风格年度热力图） ----------
    def _build_heatmap(self, content):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self._hm_title = QLabel('')
        self._hm_title.setWordWrap(True)
        self._hm_title.setProperty('textRole', 'paperMuted')
        lay.addWidget(self._hm_title)

        self._hm_scroll = QScrollArea()
        self._hm_scroll.setWidgetResizable(True)
        self._hm_scroll.setFrameShape(QFrame.NoFrame)
        self._hm_scroll.setMinimumHeight(HM_MIN_HEIGHT_MIN)
        self._hm_grid = QWidget()
        self._hm_lay = QGridLayout(self._hm_grid)
        self._hm_lay.setSpacing(3)
        self._hm_lay.setContentsMargins(0, 0, 0, 0)
        self._hm_scroll.setWidget(self._hm_grid)
        lay.addWidget(self._hm_scroll)

        legend = QHBoxLayout()
        legend.setContentsMargins(0, 0, 0, 0)
        legend.setSpacing(4)
        less = QLabel('少')
        less.setProperty('textRole', 'paperMuted')
        legend.addWidget(less)
        self._hm_legend_cells = []
        for _ in range(5):
            cell = QFrame()
            cell.setFixedSize(12, 12)
            cell.setStyleSheet('border-radius:2px;')
            legend.addWidget(cell)
            self._hm_legend_cells.append(cell)
        more = QLabel('多')
        more.setProperty('textRole', 'paperMuted')
        legend.addWidget(more)
        legend.addStretch(1)
        lay.addLayout(legend)

        self._hm_empty_label = QLabel('')
        self._hm_empty_label.setWordWrap(True)
        self._hm_empty_label.setProperty('textRole', 'paperMuted')
        self._hm_empty_label.setVisible(False)
        lay.addWidget(self._hm_empty_label)
        content.addWidget(body)

    def _refresh_heatmap(self):
        import time
        now = time.monotonic()
        # 热力图重建成本高：建好之后 60 秒内不重复（主题/紧凑度变化会作废缓存）
        if self._hm_ready and now - self._hm_last_build < 60:
            return
        self._hm_last_build = now
        self._hm_ready = True

        today = date.fromisoformat(self._engine.current_day())
        y = today.year
        first = date(y, 1, 1)
        last = date(y, 12, 31)
        data = self._repo.get_heatmap(f'{y}-01-01', f'{y}-12-31')
        max_tw = max(data.values()) if data else 0
        has_record = any(v and v > 0 for v in data.values())
        # 纸张上的空态色：主题 empty 多在深色背景上取值，纸面上改用很低不透明度的墨色
        empty_color = self._hm_empty_color if not P.dark else rgba(P.paper_text, 0.05)

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
        col_of = {first + timedelta(days=i): i // 7 for i in range(total_days + 1)}
        max_col = total_days // 7

        # 清空旧网格
        while self._hm_lay.count():
            item = self._hm_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cell_size = getattr(self, '_hm_cell_size', HM_CELL_MIN)
        self._hm_grid.setMinimumWidth((max_col + 2) * (cell_size + 3))
        self._hm_empty_label.setVisible(not has_record)
        self._hm_empty_label.setText(
            '' if has_record else f'{y} 年还没有打卡记录；有记录后每一天会按当日 tw 量着色。')

        # 月份标签（颜色跟随纸张 QSS）
        self._hm_lay.addWidget(QLabel(''), 0, 0)
        for m in range(1, 13):
            lab = QLabel(f'{m}月')
            lab.setStyleSheet(f'font-size:10px; color:{P.paper_muted};')
            self._hm_lay.addWidget(lab, 0, col_of[date(y, m, 1)] + 1)

        # 日期格子（周一在顶行）
        for i in range(total_days + 1):
            day = first + timedelta(days=i)
            tw = data.get(day.isoformat(), 0) or 0
            lv = level(tw)
            cell = QFrame()
            cell.setFixedSize(cell_size, cell_size)
            color = empty_color if lv < 0 else self._hm_levels[lv]
            cell.setStyleSheet(f'background:{color}; border-radius:3px;')
            tip = f'{day.isoformat()}：{tw} tw' if lv >= 0 else f'{day.isoformat()}：无记录'
            cell.setToolTip(tip)
            self._hm_lay.addWidget(cell, day.weekday() + 1, col_of[day] + 1)

        self._hm_lay.setRowStretch(8, 1)
        self._hm_lay.setColumnStretch(max_col + 2, 1)
        for index, cell in enumerate(self._hm_legend_cells):
            color = empty_color if index == 0 else self._hm_levels[index - 1]
            cell.setStyleSheet(f'background:{color}; border-radius:2px;')
        self._hm_title.setText(f'{y} 年打卡日历（颜色深浅 = 当日 tw 量）')

    # ---------- 次级：周月报 ----------
    def _build_reports(self, content):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        self._cards = {}
        for i, (key, title) in enumerate([
            ('week', '本周'), ('week_prev', '上周'),
            ('month', '本月'), ('month_prev', '上月'),
        ]):
            frame = _ReportCard(title)
            self._cards[key] = frame.body
            grid.addWidget(frame, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)

        self._cmp_hint = QLabel('环比（本周 vs 上周 / 本月 vs 上月）')
        self._cmp_hint.setProperty('textRole', 'paperMuted')
        lay.addWidget(self._cmp_hint)
        self._cmp_label = QLabel('')
        self._cmp_label.setWordWrap(True)
        self._cmp_label.setProperty('textRole', 'paperMuted')
        lay.addWidget(self._cmp_label)
        content.addWidget(body)

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
        if s is None or not s.get('tw'):
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
        sums = {key: self._repo.get_summary(start, end) for key, (start, end) in periods.items()}
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


class _RangeField(QWidget):
    """时间范围：可见字段标签 + 下拉框（宽度随尺度系数在区间内取值，字号不变）。"""

    def __init__(self, control, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.label = QLabel('时间范围')
        self.label.setProperty('textRole', 'paperField')
        self.label.setBuddy(control)
        lay.addWidget(self.label)
        lay.addWidget(control)
        self.setFixedWidth(FIELD_WIDTH_MIN)

    def set_width(self, width: int) -> None:
        self.setFixedWidth(max(FIELD_WIDTH_MIN, int(width)))

    def set_compact(self, compact: bool) -> None:
        # 宽度由 `_sync_scale` 的区间值统一决定；紧凑档取区间下限
        self.set_width(FIELD_WIDTH_MIN if compact else FIELD_WIDTH_MAX)


class _MetricRow(QWidget):
    """关键指标：无数据显示 —，零与无数据分开（零显示 0）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)
        self._values = {}
        self._items = [
            ('valid', '有效输入'), ('tw', '有效 tw'),
            ('speed', '平均速度'), ('acc', '正确率'),
        ]
        for key, title in self._items:
            cell = QWidget()
            v = QVBoxLayout(cell)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(2)
            label = QLabel(title)
            label.setProperty('textRole', 'paperMuted')
            value = QLabel('—')
            value.setProperty('textRole', 'paperField')
            font = QFont(value.font())
            font.setPixelSize(METRIC_VALUE_FONT)
            font.setBold(True)
            value.setFont(font)
            v.addWidget(label)
            v.addWidget(value)
            row.addWidget(cell)
            self._values[key] = value
        row.addStretch(1)
        lay.addLayout(row)

    def set_values(self, values: dict) -> None:
        for key, label in self._values.items():
            label.setText(values.get(key, '—'))


class _ReportCard(QFrame):
    """周月报卡片：纸张上的次级块，标题 + 正文（同色系浅填充、大圆角、无描边）。"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        # 配方第 96 行：纸面浅卡是同色系浅填充（`#E1D8D0` 之于纸张）+ 无描边
        self.setStyleSheet(
            f'background: {rgba(P.paper_text, 0.06)}; border: none; border-radius: 16px;')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(4)
        head = QLabel(title)
        head.setProperty('textRole', 'paperField')
        lay.addWidget(head)
        self.body = QLabel('—')
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setProperty('textRole', 'paperMuted')
        lay.addWidget(self.body)
