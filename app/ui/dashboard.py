"""今日概览页：欢迎语 + 进入训练主按钮 + 奶油纸张上的今日主统计。

层级（交接 UI_SPEC.md / spec.json v1「星光伴学 · 夜色手稿」，补充口径见素材包 v2
`DECISIONS.md`）：
1. 画布页头：转曲艺术标题（`ArtHeading(role='today')`）+ 正常文字副标题
2. 等级 / 连签摘要 + 同屏一个显著主动作「进入训练」
3. 奶油纸张主统计：今日有效字数（大数字 + 单位）+ 活跃时长 / 平均速度 / 输入准确率
4. 纸内右侧深色练习卡（同色系深靛填充、无描边、大圆角）
5. 折叠明细：详细统计、累计记录、今日逐分钟曲线（紧凑尺寸不消失，内部滚动）

版式由 `PaperPage` 页面骨架 + Qt 布局管理：纸张靠左（1440 上限 1100、900x640 上限 760），
右侧留给交付插画；纸张内边距与控件高度按 1440x1024 / 900x640 降级，字号不缩。
写死的像素改成「上下限区间 + 尺度系数（`design.scale_factor`）+ 布局 stretch」，
纸张高度由内容决定、由页内滚动兜底，不再是一个固定值。
数据只读自 `snap`（StatsEngine.snapshot），本文件不写 SQL、不改经验/日切口径。
"""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QSpacerItem, QVBoxLayout, QWidget,
)

from ..core.classifier import tw_to_hanzi_per_min, tw_to_letters_per_min
from .palette import P
from .widgets import design as _design
from .widgets.design import (
    BUTTON_HEIGHT, BUTTON_HEIGHT_COMPACT, FONT_BODY, FONT_HELPER, FONT_LABEL, FONT_METRIC,
    FONT_PAGE_TITLE, PAGE_MARGIN_TOP, PAGE_MARGIN_TOP_COMPACT, ArtHeading, Disclosure,
    Panel, PaperPage, card_fill, is_compact, rgba,
)
from .widgets.level_bar import LevelBar


def scale_for(width: int, height: int) -> float:
    """共享层尺度系数 `design.scale_factor`（唯一口径，不自己另造 token）。"""
    shared = getattr(_design, 'scale_factor', None)
    if callable(shared):
        try:
            return float(shared(width, height))
        except Exception:
            pass
    return max(0.85, min(1.15, min(width / 1440.0, height / 1024.0)))


def _scale_px(value: float, scale: float, *, minimum: int = 0) -> int:
    """共享层 `design.scale_px`（缺失时就地取整，口径一致）。"""
    shared = getattr(_design, 'scale_px', None)
    if callable(shared):
        return int(shared(value, scale, minimum=minimum))
    return max(minimum, int(round(value * scale)))


def _interp(low: int, high: int, scale: float) -> int:
    """在上下限区间里按尺度系数取值（0.85 → low，1.00 → high）。"""
    t = max(0.0, min(1.0, (float(scale) - 0.85) / 0.15))
    return int(round(low + (high - low) * t))


# 版式常量（纸张由 PaperPage 限宽；这里只管页头、纸张内部与训练卡的间距/尺寸）
HEADING_TITLE = '今天的每一次敲击'
HEADING_SUBTITLE = '陪你记录进步，今晚也闪闪发光。'
LEVEL_BAR_WIDTH_MIN, LEVEL_BAR_WIDTH_MAX = 130, 170
STATUS_MIN_WIDTH = 168           # 状态文案一行宽度（"键盘钩子未运行…" 需整段可读）
PLOT_HEIGHT_MIN, PLOT_HEIGHT_MAX = 104, 140
DETAILS_MIN, DETAILS_MAX = 200, 240     # 折叠明细展开后在这段高度内滚动
DETAILS_MIN_COMPACT = 150
# 训练卡（设计稿纸张内右侧深色卡）：宽约 290，主按钮 192x52 / 紧凑 164x44
# 紧凑档卡片**不换行堆到统计下方**（那样纸张高度会涨到 744，超出 900x640 的
# 411px 视口，卡片被纸张底边裁掉一半）：改为同排但收窄到 240，与设计稿
# today 页「左大数字 + 右深色练习卡」的水平排布一致。
TRAIN_CARD_WIDTH_MIN, TRAIN_CARD_WIDTH_MAX = 232, 300
TRAIN_CARD_PAD_MIN, TRAIN_CARD_PAD_MAX = 16, 26
TRAIN_CARD_SPACING_MIN, TRAIN_CARD_SPACING_MAX = 10, 14
TRAIN_BUTTON_WIDTH_MIN, TRAIN_BUTTON_WIDTH_MAX = 164, 200
TRAIN_BADGE_MIN, TRAIN_BADGE_MAX = 40, 52
METRICS_MIN_WIDTH_MIN, METRICS_MIN_WIDTH_MAX = 158, 280
COMPACT_COLUMN_GAP = 20          # 紧凑档三列之间的水平间距（纸内宽 720 的预算内）
HEADER_TOP, HEADER_TOP_COMPACT = 8, 6       # 与统一页头高度配合
HEADER_BOTTOM, HEADER_BOTTOM_COMPACT = 6, 4
PAPER_BOTTOM_ROOM = 16           # 纸张底边与窗口底部的留白（不压到底部导航）


def _num(v, digits=0) -> str:
    """无数据（None）显示 —，真实的 0 显示 0：零与未记录必须区分。"""
    if v is None:
        return '—'
    if digits and isinstance(v, float):
        return f'{v:,.{digits}f}'
    if isinstance(v, float):
        return f'{v:,.0f}'
    return f'{v:,}'


_LINE_HEIGHTS: dict = {}


def _line_height(pixel: int, weight: int = 0) -> int:
    """按 QSS 实际生效的字号取行高（构造一次性 QLabel 量，结果按字号缓存）。

    只按字号猜测会低估或高估：不同字体/DPR 下同一个 `font-size: 32px` 行高不同，
    偏小会把标签压到裁字，偏大则让纸张出现无谓空白。
    """
    key = (int(pixel), int(weight))
    cached = _LINE_HEIGHTS.get(key)
    if cached is not None:
        return cached
    probe = QLabel('Ag字')
    css = f'font-size:{int(pixel)}px;'
    if weight:
        css += f'font-weight:{int(weight)};'
    probe.setStyleSheet(css)
    probe.ensurePolished()
    fm = QFontMetrics(probe.font())
    # +4：留出上下各 2px 的呼吸空间，避免最紧的环境下字顶/字底贴边
    height = max(int(round(pixel * 1.4)), fm.height(), probe.sizeHint().height()) + 4
    _LINE_HEIGHTS[key] = height
    return height


class _StatBlock(QWidget):
    """对齐的数据列：标签（paperField）→ 数值 + 单位 → 说明（paperMuted）。

    数值与单位合成同一个标签：拆成并排两个标签时，窄字体环境下单位会被挤到
    数值上方并把它顶出裁剪区（离屏预览实测）。
    行高按 QSS 声明字号钉住，避免字体度量偏小的环境把行压到重叠。
    """

    def __init__(self, label, unit='', hint='', *, metric=False, parent=None):
        super().__init__(parent)
        self._metric = bool(metric)
        self._unit = unit or ''
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self.label = QLabel(label)
        self.label.setProperty('textRole', 'paperField')
        self.label.setMinimumHeight(_line_height(FONT_LABEL, 600))
        v.addWidget(self.label)
        self.value = QLabel('—')
        self.value.setProperty('textRole', 'paperMetric' if metric else 'paperField')
        if not metric:
            self.value.setStyleSheet(f'font-size:{FONT_BODY + 4}px; font-weight:700;')
        self.value.setTextFormat(Qt.PlainText)
        self.value.setMinimumHeight(_line_height(
            FONT_METRIC if metric else FONT_BODY + 4, 700))
        v.addWidget(self.value)
        self.hint = QLabel(hint)
        self.hint.setProperty('textRole', 'paperMuted')
        self.hint.setWordWrap(True)
        self.hint.setMinimumHeight(_line_height(FONT_HELPER))
        self._hint_allowed = bool(hint)
        self.hint.setVisible(bool(hint))
        v.addWidget(self.hint)

    def _text(self, number: str) -> str:
        return f'{number} {self._unit}'.strip() if number != '—' else '—'

    def set_value(self, text: str, tooltip: str = '') -> None:
        self.value.setText(self._text(text))
        self.value.setToolTip(tooltip)

    def set_unit(self, text: str) -> None:
        """单位变化后重排数值文本（保留旧调用点）。"""
        self._unit = text or ''
        self.value.setText(self._text(self.value.text().split(' ')[0]))

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.set_hint_visible(True)

    def set_hint_visible(self, visible: bool) -> None:
        """紧凑窗口把说明行收起（口径仍写在数值的提示气泡里）。"""
        self.hint.setVisible(bool(visible) and self._hint_allowed)


class Dashboard(QWidget):
    training_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._compact = None
        self._exp_value = 0
        self._scale = scale_for(1440, 1024)
        self._card_w = TRAIN_CARD_WIDTH_MIN
        self._card_pad = TRAIN_CARD_PAD_MIN
        self._badge_px = TRAIN_BADGE_MIN

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 页面骨架：纸张靠左（1440 上限 1100 / 900x640 上限 760），右侧留给交付插画
        self._page = PaperPage(self, compact=is_compact(1440, 1024))
        self._paper = self._page.paper
        self._paper_body = self._page.body
        root.addWidget(self._page)
        paper = self._paper_body

        # ---- 1. 页头：转曲艺术标题 + 文字副标题，放在纸张之外的画布上 ----
        header = QWidget()
        self._header_layout = QVBoxLayout(header)
        self._header_layout.setContentsMargins(0, HEADER_TOP, 0, HEADER_BOTTOM)
        self._header_layout.setSpacing(10)
        self._welcome = ArtHeading('today', HEADING_SUBTITLE)
        self._header_layout.addWidget(self._welcome)
        self._page.set_header(header)

        # ---- 2. 纸张抬头：等级 / 连签 / 称号（真实数据）+ 右侧数据来源说明 ----
        paper_head = QHBoxLayout()
        paper_head.setContentsMargins(0, 0, 0, 0)
        paper_head.setSpacing(12)
        self._level_badge = QLabel('')
        paper_head.addWidget(self._level_badge)
        self._streak_label = QLabel('')
        paper_head.addWidget(self._streak_label)
        self._band_label = QLabel('')
        self._band_label.setProperty('textRole', 'paperMuted')
        paper_head.addWidget(self._band_label)
        paper_head.addStretch(1)
        self._paper_note = QLabel('本页数据全部来自今日真实统计')
        self._paper_note.setProperty('textRole', 'paperMuted')
        paper_head.addWidget(self._paper_note, 0, Qt.AlignVCenter)
        paper.addLayout(paper_head)

        # 等级进度（真实经验进度；保留 LevelBar 供既有脚本直接调用）
        exp_row = QHBoxLayout()
        exp_row.setContentsMargins(0, 0, 0, 0)
        exp_row.setSpacing(10)
        self._level_bar = LevelBar()
        self._level_bar.setFixedWidth(_interp(LEVEL_BAR_WIDTH_MIN, LEVEL_BAR_WIDTH_MAX,
                                              self._scale))
        exp_row.addWidget(self._level_bar)
        self._exp_text = QLabel('')
        self._exp_text.setProperty('textRole', 'paperMuted')
        exp_row.addWidget(self._exp_text)
        exp_row.addStretch(1)
        paper.addLayout(exp_row)

        # ---- 3. 主统计（左）+ 纸内右侧深色训练卡（右）；紧凑窗口卡片落到下方 ----
        main_grid = QGridLayout()
        main_grid.setContentsMargins(0, 0, 0, 0)
        main_grid.setHorizontalSpacing(32)
        main_grid.setVerticalSpacing(10)
        self._primary = _StatBlock('今日有效字数', '', '输入 − 删除', metric=True)
        main_grid.addWidget(self._primary, 0, 0, Qt.AlignTop | Qt.AlignLeft)
        secondary_col = QVBoxLayout()
        secondary_col.setContentsMargins(0, 0, 0, 0)
        secondary_col.setSpacing(10)
        self._secondary = {}
        for key, label, unit, hint in (
            ('minutes', '活跃时长', '分钟', ''),
            ('avg_speed', '平均速度', '', '按有输入的分钟计算'),
            ('accuracy', '输入准确率（估算）', '', '有效 ÷ 输入'),
        ):
            block = _StatBlock(label, unit, hint)
            self._secondary[key] = block
            secondary_col.addWidget(block)
        main_grid.addLayout(secondary_col, 0, 1, Qt.AlignTop)
        self._main_grid = main_grid
        self._metrics_col = secondary_col
        paper.addLayout(main_grid)

        # 训练入口卡（纸内右侧深色卡片）：徽标 + 标题 + 辅助行 + 主按钮
        # 视觉按配方：深色卡无描边（render_design.py 第 26 行 `stroke=None`）、
        # 圆角 16 → 20、同色系深靛填充（card_fill 由 surface 向 surface_text 派生）。
        card = Panel()
        self._train_card = card
        card.setMinimumWidth(TRAIN_CARD_WIDTH_MIN)
        card.setMaximumWidth(TRAIN_CARD_WIDTH_MAX)
        card.setMinimumHeight(140)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        card_layout = QVBoxLayout(card)
        self._card_layout = card_layout
        self._apply_card_metrics(False)
        self._train_badge = QLabel('A')
        self._train_badge.setAlignment(Qt.AlignCenter)
        self._train_badge.setFixedSize(TRAIN_BADGE_MIN, TRAIN_BADGE_MIN)
        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.addWidget(self._train_badge)
        badge_row.addStretch(1)
        card_layout.addLayout(badge_row)
        self._train_title = QLabel('准备一次专心练习？')
        self._train_title.setWordWrap(True)
        self._train_helper = QLabel('内置范文，随时开始。')
        self._train_helper.setWordWrap(True)
        card_layout.addWidget(self._train_title)
        card_layout.addWidget(self._train_helper)
        card_layout.addStretch(1)
        self._practice_btn = QPushButton('去练习 →')
        self._practice_btn.setProperty('buttonRole', 'primary')
        self._practice_btn.setAccessibleName('进入训练')
        self._practice_btn.setCursor(Qt.PointingHandCursor)
        self._practice_btn.clicked.connect(self.training_requested)
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.addWidget(self._practice_btn)
        btn_row.addStretch(1)
        card_layout.addLayout(btn_row)
        self._card_row = 0
        main_grid.addWidget(card, 0, 2, Qt.AlignLeft | Qt.AlignTop)
        main_grid.setColumnStretch(2, 0)

        # 空态说明（有数据时换成今日节奏摘要；紧凑档该行收起，见 set_compact）
        self._summary = QLabel('')
        self._summary.setProperty('textRole', 'paperMuted')
        self._summary.setWordWrap(True)
        paper.addWidget(self._summary)

        # ---- 4. 折叠明细：详细统计 / 累计记录 / 逐分钟曲线（展开后内部滚动） ----
        details = Disclosure('详细统计、累计记录与今日曲线')
        self._details = details
        details.toggle.toggled.connect(self._on_details_toggled)
        details_scroll = QScrollArea()
        details_scroll.setFrameShape(QFrame.NoFrame)
        details_scroll.setWidgetResizable(True)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        details_scroll.setMinimumHeight(DETAILS_MIN)
        details_scroll.setMaximumHeight(DETAILS_MAX)
        self._details_scroll = details_scroll
        details_body = QWidget()
        details_layout = QVBoxLayout(details_body)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(12)
        details_scroll.setWidget(details_body)
        details.content.addWidget(details_scroll)
        detail_grid = QGridLayout()
        detail_grid.setContentsMargins(0, 0, 0, 0)
        detail_grid.setHorizontalSpacing(24)
        detail_grid.setVerticalSpacing(8)
        self._details_blocks = {}
        for i, (key, label) in enumerate((
            ('typed', '今日输入'), ('deleted', '今日删除'), ('tw', '今日 tw'),
            ('revision', '改写率'), ('pred_hanzi', '预测汉字/分'),
            ('pred_letters', '预测字母/分'), ('exp', '本届等级经验'),
        )):
            block = _StatBlock(label)
            self._details_blocks[key] = block
            detail_grid.addWidget(block, i // 3, i % 3)
        details_layout.addLayout(detail_grid)

        self._lifetime = QLabel('')
        self._lifetime.setProperty('textRole', 'paperMuted')
        self._lifetime.setWordWrap(True)
        details_layout.addWidget(self._lifetime)

        self._chart_label = QLabel('今日逐分钟 tw 曲线')
        self._chart_label.setProperty('textRole', 'paperField')
        details_layout.addWidget(self._chart_label)
        self._mini_plot = pg.PlotWidget()
        self._mini_plot.setMinimumHeight(PLOT_HEIGHT_MIN)
        self._mini_plot.setAccessibleName('今日逐分钟 tw 曲线')
        self._mini_plot.setMouseEnabled(x=False, y=False)
        self._mini_plot.showGrid(x=False, y=True, alpha=0.25)
        self._mini_plot.setLabel('bottom', '')
        self._mini_plot.getPlotItem().getViewBox().setDefaultPadding(0.06)
        self._mini_curve = self._mini_plot.plot([], [], pen=pg.mkPen(P.paper_muted, width=2))
        details_layout.addWidget(self._mini_plot)
        self._chart_empty = QLabel('今天还没有逐分钟记录。')
        self._chart_empty.setProperty('textRole', 'paperMuted')
        details_layout.addWidget(self._chart_empty)
        details_layout.addStretch(1)
        paper.addWidget(details)

        # ---- 5. 就近状态（钩子 / 统计是否在跑 + 托盘提示）：两行，不省略失败原因 ----
        status_box = QFrame()
        status_box.setObjectName('hookStatus')
        status_box.setAttribute(Qt.WA_StyledBackground, True)
        status = QVBoxLayout(status_box)
        status.setContentsMargins(0, 0, 0, 0)
        status.setSpacing(4)
        self._status_layout = status
        self._hook_status = QLabel('统计中')
        self._hook_status.setWordWrap(True)
        # 状态文案必须整段可读：给足一行宽度，避免被右侧同类提示挤成两行
        self._hook_status.setMinimumWidth(STATUS_MIN_WIDTH)
        self._hook_info = QLabel('')
        self._hook_info.setProperty('textRole', 'paperMuted')
        status_line = QHBoxLayout()
        status_line.setContentsMargins(0, 0, 0, 0)
        status_line.setSpacing(10)
        status_line.addWidget(self._hook_status)
        status_line.addWidget(self._hook_info, 1)
        status.addLayout(status_line)
        self._hint = QLabel('提示：关闭窗口后驻留系统托盘，后台继续统计打字。')
        self._hint.setProperty('textRole', 'paperMuted')
        self._hint.setWordWrap(True)
        status.addWidget(self._hint)
        paper.addWidget(status_box)
        paper.addItem(QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding))

        self.set_hook_status(True)
        self.set_compact(is_compact(1440, 1024))
        self._page.scroll.viewport().installEventFilter(self)
        self.apply_theme()

    # ---------- 版式（弹性：上下限区间 + 尺度系数 + 布局 stretch） ----------
    def set_compact(self, compact: bool) -> None:
        """紧凑窗口：纸张内边距 32→20、控件 52→44，字号不缩（纸张宽度由 PaperPage 降级）。"""
        from .widgets.responsive import stage_layout_for
        compact = stage_layout_for(self).compact
        if compact == self._compact:
            return
        self._compact = compact
        self._page.set_compact(compact)          # 外边距 + 纸张宽度上限 + 页头下间距一起降级
        self._header_layout.setContentsMargins(
            0, HEADER_TOP_COMPACT if compact else HEADER_TOP, 0,
            HEADER_BOTTOM_COMPACT if compact else HEADER_BOTTOM)
        self._paper_body.setSpacing(10 if compact else 16)
        self._main_grid.setVerticalSpacing(6 if compact else 8)
        self._main_grid.setHorizontalSpacing(
            COMPACT_COLUMN_GAP if compact else 32)
        for block in self._secondary.values():
            block.layout().setSpacing(2)
        self._sync_scale()
        # 紧凑窗口：训练卡仍在统计块右侧同排（与设计稿 today 页一致），只收窄卡片，
        # 不换行堆到下方——换行会把纸张撑到 744px，超出 900x640 的 411px 视口。
        self._place_train_card(compact)
        self._apply_paper_height()
        # 紧凑窗口：次要指标的单行说明收起（口径已写在数值的提示气泡里），
        # 保证纸张高度收进 900x640 的 411px 视口——卡片被裁的根因就是纸张高达 744。
        for key in ('avg_speed', 'accuracy'):
            self._secondary[key].set_hint_visible(not compact)
        # 主指标「今日有效字数 / 输入 − 删除」在紧凑档收起说明行：字段名已自解释，
        # 省下的 24px 用于把纸张压进视口（数值的提示气泡仍保留完整口径）
        self._primary.set_hint_visible(not compact)
        # 紧凑档：摘要行与托盘提示行收起。900x640 纸张可用高只有 411px，而纸内
        # 内容（纸头 + 指标 + 深色卡 + 折叠入口 + 状态行）实测需要 417px；这两行
        # 是规范允许降级的次要文字（统计口径仍在数值提示气泡与折叠明细里）。
        self._summary.setVisible(not compact)
        self._hint.setVisible(not compact)
        self._status_layout.setSpacing(4 if not compact else 2)
        self._details_scroll.setMinimumHeight(
            DETAILS_MIN_COMPACT if compact else DETAILS_MIN)
        # 紧凑窗口省去来源说明（规范允许的次要文字降级，数据本身不隐藏）
        self._paper_note.setVisible(not compact)

    def _sync_scale(self) -> None:
        """按窗口尺寸更新尺度系数，把写死值换成区间取值（字号不变）。"""
        self._scale = scale_for(max(1, self.width()), max(1, self.height()))
        self._card_w = _interp(TRAIN_CARD_WIDTH_MIN, TRAIN_CARD_WIDTH_MAX, self._scale)
        if self._compact:
            # 紧凑档纸内要同排放下指标列 + 卡片，卡片宽度收在区间下限附近
            self._card_w = min(self._card_w, TRAIN_CARD_WIDTH_MIN)
        self._card_pad = _interp(TRAIN_CARD_PAD_MIN, TRAIN_CARD_PAD_MAX, self._scale)
        self._badge_px = _interp(TRAIN_BADGE_MIN, TRAIN_BADGE_MAX, self._scale)
        self._apply_card_metrics(self._compact)
        self._sync_button_size()
        self._level_bar.setFixedWidth(
            _interp(LEVEL_BAR_WIDTH_MIN, LEVEL_BAR_WIDTH_MAX, self._scale))
        self._train_badge.setFixedSize(self._badge_px, self._badge_px)
        height = _interp(PLOT_HEIGHT_MIN, PLOT_HEIGHT_MAX, self._scale)
        if self._compact:
            height = PLOT_HEIGHT_MIN
        self._mini_plot.setMinimumHeight(height)
        self._sync_card_style()

    def _sync_button_size(self) -> None:
        """主按钮固定设计尺寸（52/44）。

        单独成方法是因为主题 QSS 会在本页构造之后才应用到窗口上，而
        `QPushButton { min-height: 26px; padding: … }` 这条全局规则的优先级高于控件上
        设置的最小尺寸——只调 `setFixedSize` 会被主题那一次 polish 覆盖回 26px。
        因此这里同时写一条**控件级** `min-height`（内联样式优先于 app 级 QSS），
        再加 `setFixedHeight` 兜住上限与下限。
        """
        width = (TRAIN_BUTTON_WIDTH_MIN if self._compact
                 else _interp(TRAIN_BUTTON_WIDTH_MIN, TRAIN_BUTTON_WIDTH_MAX, self._scale))
        height = BUTTON_HEIGHT_COMPACT if self._compact else BUTTON_HEIGHT
        self._practice_btn.setStyleSheet(f'min-height: {height}px;')
        self._practice_btn.setFixedSize(width, height)

    def _apply_card_metrics(self, compact: bool) -> None:
        """训练卡宽度/内边距/间距按尺度系数在区间内取值（紧凑档取下限）。"""
        pad = self._card_pad
        self._card_layout.setContentsMargins(pad, pad, pad, pad)
        self._card_layout.setSpacing(
            _interp(TRAIN_CARD_SPACING_MIN, TRAIN_CARD_SPACING_MAX, self._scale))
        self._train_card.setMinimumWidth(self._card_w)
        self._train_card.setMaximumWidth(max(self._card_w, TRAIN_CARD_WIDTH_MAX))
        self._train_card.setMinimumHeight(_interp(140, 170, self._scale))

    def _sync_card_style(self) -> None:
        """深色练习卡：同色系深填充 + 大圆角 + **无描边**（配方第 100 行 Qt.NoPen）。

        这是「黑色边框很碍眼」的主要来源之一（旧实现走 `designPanel`，主题 QSS 给
        了 1px `card_border`）。这里用对象名限定作用域，改成配方口径。
        """
        radius = _interp(16, 22, self._scale)
        self._train_card.setObjectName('trainCard')
        self._train_card.setStyleSheet(
            f'QFrame#trainCard {{ background: {card_fill()}; border: none;'
            f' border-radius: {radius}px; }}')

    def _place_train_card(self, compact: bool) -> None:
        """训练卡与统计块同排（0=主指标 / 1=次要指标 / 2=深色练习卡），紧凑档只收窄。

        设计稿 today 页是「左侧大数字与指标 + 右侧深色练习卡」的水平排布；紧凑档
        把卡片收窄到区间下限、指标列宽度下限同步下调，使 720px 纸内宽容得下三者，
        而不是把卡片换行堆到下方（换行会把纸张撑到 744px，超出 900x640 的 411px 视口）。
        """
        self._card_row = 0
        self._main_grid.setColumnMinimumWidth(
            1, _interp(METRICS_MIN_WIDTH_MIN, METRICS_MIN_WIDTH_MAX, self._scale)
            if not compact else METRICS_MIN_WIDTH_MIN)
        self._main_grid.setColumnStretch(0, 3)
        self._main_grid.setColumnStretch(1, 2)
        self._main_grid.setColumnStretch(2, 0)

    def resizeEvent(self, event):
        self.set_compact(is_compact(self.width(), self.height()))
        self._sync_scale()
        self._apply_paper_height()
        super().resizeEvent(event)

    def eventFilter(self, obj, event):
        """页内滚动视口尺寸变化后重算纸张上限（视口高度是纸张可见高度的依据）。"""
        if obj is self._page.scroll.viewport() and event.type() == QEvent.Resize:
            self._apply_paper_height()
        return super().eventFilter(obj, event)

    def _apply_paper_height(self) -> None:
        """纸张高度 = 内容所需高度；窗口放不下时由 PaperPage 的页内滚动接管。

        `PaperPage` 只约束宽度与左右边距，这里补高度：下限取内容所需高度
        （不把训练卡/指标压扁），上限取**页内滚动视口**的可见高度（不是窗口高度：
        紧凑档页头 + 外边距 + 滚动条会吃掉近百像素，用窗口高度算会让纸张越过
        底部导航，卡片被切在视口外）。多出视口的高度交给页内滚动。
        """
        room = self._visible_room()
        need = self._paper_body.sizeHint().height()
        if self._paper.minimumHeight() != need:
            self._paper.setMinimumHeight(need)
        cap = max(need, room)
        if self._paper.maximumHeight() != cap:
            self._paper.setMaximumHeight(cap)

    def _visible_room(self) -> int:
        """纸张可用高度：页内滚动视口高度减去纸张顶边以上的页头部分。"""
        data = getattr(self._page, 'scroll', None)
        viewport = data.viewport() if data is not None else None
        if viewport is None:
            margin_y = PAGE_MARGIN_TOP_COMPACT if self._compact else PAGE_MARGIN_TOP
            return max(280, self.height() - margin_y - PAPER_BOTTOM_ROOM)
        bar = data.verticalScrollBar()
        visible = max(200, viewport.height() - (bar.sizeHint().width() if bar else 0))
        top = self._paper.mapTo(data, self._paper.rect().topLeft()).y()
        if top <= 0:
            top = PAGE_MARGIN_TOP_COMPACT if self._compact else PAGE_MARGIN_TOP
        return max(280, visible - top - PAPER_BOTTOM_ROOM)

    def _on_details_toggled(self, _expanded: bool = False) -> None:
        """明细展开后内容高度变化，纸张上限要重新算（展开内容本身在内部滚动）。"""
        self._apply_paper_height()

    # ---------- 主题 ----------
    def apply_theme(self):
        """纸张内的文字/数值走 QSS 语义角色；这里只处理纸张外的页头、训练卡与图表。"""
        # 页头在纸张外的深色画布上：艺术标题是交付 SVG（颜色自带），副标题用画布语义色
        self._welcome.subtitle.setStyleSheet(
            f'color:{P.surface_muted}; font-size:{FONT_HELPER}px;')
        # 纸张上的强调色只能是 on-paper 角色（accent/primary 在奶油纸上 <2:1，不可用于文字）
        self._level_badge.setStyleSheet(
            f'color:{P.paper_text}; font-size:{FONT_BODY}px; font-weight:800;')
        self._streak_label.setStyleSheet(
            f'color:{P.danger_on_paper}; font-size:{FONT_BODY}px; font-weight:700;')
        self._hook_status.setStyleSheet(
            f'color:{P.success}; font-size:{FONT_HELPER}px; font-weight:700;')
        # 进度槽在奶油纸上要有可辨识的底色（LevelBar 默认槽是黑色 70 透明）
        self._level_bar.setStyleSheet(
            f'background:{rgba(P.paper_muted, 0.22)}; border-radius:10px;')
        # 训练卡是深色面板：卡内文字用 surface 语义色（纸面墨色在深色面板上不可读）
        self._sync_card_style()
        # 主题 QSS 重新 polish 会复位最小尺寸约束，主按钮尺寸要再设一次
        self._sync_button_size()
        badge_px = self._badge_px
        self._train_badge.setStyleSheet(
            f'background:{P.primary}; color:{P.primary_text};'
            f'font-size:{max(18, badge_px - 26)}px; font-weight:800;'
            f' border-radius:{max(10, badge_px // 4)}px;')
        self._train_title.setStyleSheet(
            f'color:{P.surface_text}; font-size:{FONT_BODY}px; font-weight:600;')
        self._train_helper.setStyleSheet(
            f'color:{P.surface_muted}; font-size:{FONT_HELPER}px;')
        self._mini_plot.setBackground(P.paper)
        axis_pen = pg.mkPen(P.paper_muted)
        for axis in ('bottom', 'left'):
            item = self._mini_plot.getAxis(axis)
            item.setPen(axis_pen)
            item.setTextPen(axis_pen)
        # 曲线同样受「纸上对比度」约束：用 paper_text（10:1），不用 accent_ochre（1.6:1）
        self._mini_curve.setPen(pg.mkPen(P.paper_text, width=2))

    # ---------- 钩子状态 ----------
    def resume_animations(self, on: bool) -> None:
        """窗口可见性变化时暂停/恢复装饰动画（托盘驻留时省电）。"""
        self._level_bar.set_visible_anim(on)

    def set_hook_status(self, ok: bool):
        self._hook_status.setText(
            '键盘钩子运行正常，正在统计' if ok
            else '键盘钩子未运行，不会统计打字——请重启应用')
        self._hook_status.setStyleSheet(
            f'color:{P.success if ok else P.danger_on_paper};'
            f'font-size:{FONT_HELPER}px; font-weight:700;')

    def set_hook_info(self, event_count: int, ime_readable: bool, errs=None,
                      tsf_ok: bool = False):
        text = f'本次运行已捕获 {event_count:,} 个按键事件'
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

    # ---------- 数据刷新（只读 snap） ----------
    def refresh(self, snap, level, progress, band, streak, unit, exp=0):
        self._exp_value = exp
        unit = unit or '字'

        self._level_badge.setText(f'Lv.{level}')
        self._band_label.setText(f'称号：{band}　·　{unit} 单位')
        self._streak_label.setText(f'连签 {streak} 天')
        self._level_bar.set_progress(progress)
        self._exp_text.setText(f'等级进度 {round(progress * 100)}%')

        valid = snap['valid']
        self._primary.set_unit(unit)
        self._primary.set_value(
            _num(valid), '今日有效字数 = 输入 − 删除（只统计真实按键）')

        minutes = snap['minutes']
        avg = snap['avg_tw']
        acc = snap['accuracy']
        self._secondary['minutes'].set_value(
            _num(minutes), '今日有输入记录的分钟数')
        self._secondary['avg_speed'].set_unit(f'{unit}/分')
        self._secondary['avg_speed'].set_value(
            f'{avg:,.1f}' if avg is not None else '—',
            f'平均速度（{unit}/分）：当日 tw ÷ 有输入的分钟数')
        self._secondary['accuracy'].set_value(
            f'{acc * 100:,.1f}%' if acc is not None else '—',
            '正确率 = 有效 ÷ 输入（删除按键计入失误）')

        typed = snap['typed']
        deleted = snap['deleted']
        rev = deleted / typed if typed else None
        if valid <= 0 and not minutes:
            self._summary.setText('今天还没有记录；开一段练习，这里会显示今日节奏。')
        elif rev is not None and rev > 0.15:
            self._summary.setText('今天改动较多，删改占比偏高——放松一点，先求稳。')
        else:
            self._summary.setText(
                f'今天已连续记录 {_num(minutes)} 分钟，'
                f'本篇数据只统计今日，不会并入终身累计。')

        detail_values = {
            'typed': (_num(typed), '今日按下的输入按键数'),
            'deleted': (_num(deleted), '今日删除按键数'),
            'tw': (_num(snap['tw']), '今日累计 tw'),
            'revision': (f'{rev * 100:,.1f}%' if rev is not None else '—',
                         '改写率 = 删除 ÷ 输入；写作场景比正确率更诚实'),
            'pred_hanzi': (f'{tw_to_hanzi_per_min(avg):,.1f}' if avg is not None else '—',
                           '按当前平均速度换算的汉字/分'),
            'pred_letters': (f'{tw_to_letters_per_min(avg):,.1f}' if avg is not None else '—',
                             '按当前平均速度换算的字母/分'),
            'exp': (_num(exp), '本届等级累计经验'),
        }
        for key, (text, tip) in detail_values.items():
            self._details_blocks[key].set_value(text, tip)

        self._lifetime.setText(
            f'累计记录　输入 {_num(snap["lifetime_typed"])} 字　·　'
            f'有效 {_num(snap["lifetime_valid"])} 字　·　'
            f'tw {_num(snap["lifetime_tw"])}　·　'
            f'活跃 {_num(snap["lifetime_minutes"])} 分钟')

        series = snap.get('minutes_series') or []
        if series:
            series = sorted(series, key=lambda item: item[0])
            xs = list(range(len(series)))
            self._mini_curve.setData(xs, [v[1] for v in series])
            step = max(1, len(series) // 6)
            self._mini_plot.getAxis('bottom').setTicks(
                [[(i, series[i][0]) for i in range(len(series)) if i % step == 0]])
            self._chart_empty.setVisible(False)
            self._mini_plot.setVisible(True)
        else:
            self._mini_curve.setData([], [])
            self._mini_plot.getAxis('bottom').setTicks([[]])
            self._mini_plot.setVisible(False)
            self._chart_empty.setVisible(True)
