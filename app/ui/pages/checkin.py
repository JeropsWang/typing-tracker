"""打卡页（夜色手稿）：连签大数字 + 最近 7 天打卡格 + 月历 + 里程碑礼包 + 道具库存。

- 复用公共骨架 PaperPage：奶油纸张靠左（上限 1100/760），右侧留给交付插画
- 「最近 7 天」是主视图；既有能力「月历 + 上月/下月」放在折叠区里，默认收起
- 格子/芯片/深色卡按配方（design-recipe.md §2）改成「同色系浅填充 + 大圆角」的
  贴纸感：大面积卡片一律不描深灰硬边（设计稿 `box(..., stroke=None)`），未达成这类
  需要「非颜色」线索的状态用同色系虚线淡边，而不是 1px `paper_text@0.16` 的硬边
- 紧凑档纸张内边距 16px（口径：仅纸面内容从 20 收到 16，外层 24 页面边距不变）
- 动作按钮高度不低于 44px，一行放不下时整行换行（两行各自仍然是完整按钮）
- 格子状态用「符号 + 文字 + 底色」三重表达，不单靠颜色区分
- 紧凑窗口只降内边距与控件高度，字号不缩；页面内容超出时由骨架滚动
- 业务仍走既有服务（CheckinService / RewardService），页面不写 SQL
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
)

from ..palette import P, mix
from ..widgets import design as _design
from ..widgets.design import (
    BUTTON_HEIGHT, BUTTON_HEIGHT_COMPACT, PAPER_PAD, ArtHeading, Disclosure, PaperPage,
    is_compact, rgba,
)
# 未达成挂锁是自绘矢量（🔒 在微软雅黑下渲染成空白方框）；与成就墙共用同一枚
from .achievements import lock_pixmap

#: 口径（DECISIONS.md 第 3 条）：成长/打卡页**纸面内容**内边距紧凑档 16px。
#: 共享层 `PAPER_PAD_COMPACT` 是全局基准（20px，用于训练等页），成长页单独取 16，
#: 外层 24px 页面边距不动。
GROWTH_PAD_COMPACT = 16


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


# 版式 token（纸张位置/宽度由 PaperPage 统一：1100/760 宽，左右 48/24）
STATUS_WIDTH, STATUS_WIDTH_COMPACT = 300, 232
STATUS_WIDTH_MAX = 330
DAY_CELL_MIN_W, DAY_CELL_MIN_W_COMPACT = 78, 62
DAY_CELL_MIN_H_MIN, DAY_CELL_MIN_H_MAX = 84, 118
MILESTONE_CHIP_H_MIN, MILESTONE_CHIP_H_MAX = 82, 100
MONTH_CELL, MONTH_CELL_COMPACT = 46, 44
MILESTONE_COLS = 4
DEFAULT_SIZE = (900, 640)
WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日']
STRIP_DAYS = 7
CAL_NAV_HEIGHT, CAL_NAV_HEIGHT_COMPACT = 36, 32
# 纸张内的动作按钮：不低于 44px（口径：空间不足改两行，不允许压扁）
ACTION_BUTTON_MIN_H = 44
# 纸面卡片圆角（配方：纸面浅卡 12 / 打卡格 10；这里统一放大到 12–16 的贴纸感）
CARD_RADIUS_MIN, CARD_RADIUS_MAX = 12, 16

# 格子状态（符号 + 文字 + 底色三重表达）
STATE_SIGNED = 'signed'
STATE_TODAY_MISS = 'today_miss'
STATE_MISSED = 'missed'
STATE_FUTURE = 'future'

# 状态 → (底色, 描边, 虚线, 描边宽, 符号, 符号色, 文字)
# 底色按配方「纸面加深一档」的派生方式（同色系浅填充），不再用高透明度主题色盖纸面
STATE_STYLE = {
    STATE_SIGNED: ('primaryLight', 'primarySoft', False, 1, '√', 'success', '已签'),
    STATE_TODAY_MISS: ('roseLight', 'roseSoft', False, 1, '○', 'muted', '今天 · 未签'),
    STATE_MISSED: ('paperDim', 'paperSoft', False, 1, '○', 'muted', '未签'),
    STATE_FUTURE: ('paperBlank', 'paperSoft', True, 1, '·', 'muted', '未来'),
}


def _dstr(d: date) -> str:
    return d.isoformat()


def _state_style(state: str) -> tuple:
    """状态 → (底色, 描边, 虚线, 描边宽, 符号, 符号色, 状态文字)。

    配方依据：大面积卡片无描边（对齐 render_design.py 第 26 行 `stroke=None`），
    底色统一由纸张色与墨色混合派生（等价于设计稿 `#DCD2E2`/`#DED4CB` 这类同色系浅填充）。
    """
    bg, border, dash, width, symbol, color, text = STATE_STYLE[state]
    backgrounds = {
        'primaryLight': rgba(P.primary, 0.30),
        'roseLight': rgba(P.accent_rose, 0.26),
        'paperDim': rgba(P.paper_text, 0.055),
        'paperBlank': rgba(P.paper_text, 0.025),
    }
    borders = {
        # 未签/未来用同色系淡墨虚线（不能用颜色单独表达的禁用语义，只做辅助线索）
        'primarySoft': rgba(P.primary, 0.55),
        'roseSoft': rgba(P.accent_rose, 0.55),
        'paperSoft': rgba(P.paper_muted, 0.38),
    }
    colors = {
        'success': P.success_on_paper,
        'muted': P.paper_muted,
    }
    return (backgrounds[bg], borders[border], dash, width, symbol,
            colors[color], text)


def _card_style(widget: QFrame, name: str, bg: str, border: str = '', *,
                radius: int = 14, width: int = 1, dash: bool = False,
                pad: str = '') -> None:
    """纸张上的卡片：同色系浅填充 + 大圆角；无描边时不发 border 声明。

    对象名限定选择器作用域，不影响子控件。
    """
    widget.setObjectName(name)
    edge = (f' border: {width}px {"dashed" if dash else "solid"} {border};'
            if border else ' border: none;')
    widget.setStyleSheet(
        f'QFrame#{name} {{ background: {bg};{edge} border-radius: {radius}px;{pad} }}')


def _dark_card_style(widget: QFrame, name: str, *, radius: int = 18) -> None:
    """深色卡片：设计稿把「今日已自动签到」做成深靛底 + 白字（surface 语义色）。

    配方第 100 行：深色卡**无描边**，只用 surface 填充 + 16px 圆角；与训练页输入区、
    今日页练习卡同一套深色表面语言。子标签的白色由各自的 `surface*` 显式设置
    （QSS 的 `[paperSurface] QLabel` 会把它们拉回纸张正文色）。
    """
    widget.setObjectName(name)
    widget.setStyleSheet(f'QFrame#{name} {{ background: {P.surface};'
                         f' border: none; border-radius: {radius}px; }}')


def _state_of(day: date, today: date, rows: dict) -> str:
    """格子状态（完全由仓储里已有的签到行决定，不由 UI 推算）。"""
    iso = _dstr(day)
    if iso in rows:
        return STATE_SIGNED
    if day == today:
        return STATE_TODAY_MISS
    if day < today:
        return STATE_MISSED
    return STATE_FUTURE


# 深色状态卡的两个字形：自绘矢量（与成就/里程碑的挂锁同一套做法，
# 避免 🏆/⏳ 这类字符在 Microsoft YaHei UI 下渲染成空白方框）
_GLYPH_SVG = {
    'award': ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" '
              'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
              '<circle cx="16" cy="12" r="7"/>'
              '<path d="M11 18.5 8.5 29l7.5-4 7.5 4-2.5-10.5"/>'
              '<path d="m16 8.4 1.3 2.6 2.9.4-2.1 2 .5 2.9-2.6-1.4-2.6 1.4.5-2.9-2.1-2 2.9-.4Z"/>'
              '</svg>'),
    'hourglass': ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" '
                  'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
                  '<path d="M9 4h14M9 28h14"/>'
                  '<path d="M11 4v4.5c0 3 5 5.5 5 7.5s-5 4.5-5 7.5V28"/>'
                  '<path d="M21 4v4.5c0 3-5 5.5-5 7.5s5 4.5 5 7.5V28"/>'
                  '</svg>'),
}
_GLYPH_CACHE: dict = {}


def _status_glyph(name: str, size: int, color: str):
    """自绘状态字形（深色卡上使用；颜色随主题）。"""
    from PySide6.QtCore import QByteArray, QRectF
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    key = (name, int(size), color)
    if key not in _GLYPH_CACHE:
        pixmap = QPixmap(int(size), int(size))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer = QSvgRenderer(QByteArray(
            _GLYPH_SVG[name].replace('{c}', color).encode('utf-8')))
        renderer.render(painter, QRectF(0, 0, int(size), int(size)))
        painter.end()
        _GLYPH_CACHE[key] = pixmap
    return _GLYPH_CACHE[key]


def _clear_layout(layout) -> None:
    """立即脱离父级再销毁，避免重建期间瞬时双重绘制。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


def _activate_tree(widget: QWidget) -> None:
    """递归激活布局树。

    离屏截图/紧凑切换可能只跑一轮事件循环；重建控件后若布局未被激活，
    大字号（32px）数字会停在旧几何上被裁掉字头（截图里表现为竖条）。
    """
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        _activate_tree(child)


def _label(text: str, role: str = '', size: int = 0, *, bold: bool = False,
           align=None, wrap: bool = False, color: str = '') -> QLabel:
    """纸张上的文字标签：优先用全局语义角色，必要时补字号/颜色。"""
    lab = QLabel(text)
    if role:
        lab.setProperty('textRole', role)
    css = []
    if color:
        css.append(f'color: {color}')
    if size:
        css.append(f'font-size: {size}px')
    if bold:
        css.append('font-weight: 600')
    if css:
        lab.setStyleSheet('; '.join(css))
    if align is not None:
        lab.setAlignment(align)
    if wrap:
        lab.setWordWrap(True)
    return lab


class CheckinPage(QWidget):
    def __init__(self, repo, balance, checkin_service, reward_service, engine,
                 parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._checkin = checkin_service
        self._rewards = reward_service
        self._engine = engine
        self._compact = None
        self._paper_min = 0
        self._ready = False
        # 弹性尺寸：尺度系数与由它派生的区间值（构造期先按基准尺寸取一档）
        self._scale = scale_for(*DEFAULT_SIZE)
        self._cell_radius = _interp(CARD_RADIUS_MIN, CARD_RADIUS_MAX, self._scale)
        self._day_cell_h = _interp(DAY_CELL_MIN_H_MIN, DAY_CELL_MIN_H_MAX, self._scale)
        self._chip_h = _interp(MILESTONE_CHIP_H_MIN, MILESTONE_CHIP_H_MAX, self._scale)
        self._month = date.fromisoformat(engine.current_day()).replace(day=1)

        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 页面骨架：纸张之外的页头（画布上）+ 左侧奶油纸张（上限 1100/760 宽）
        self._page = PaperPage(self, compact=is_compact(*DEFAULT_SIZE))
        self._paper = self._page.paper
        self._content = self._page.body
        self._content.setSpacing(14)
        root.addWidget(self._page)

        # 交付的转曲艺术标题（成长三页共用 role='growth'）；副标题仍是普通可读文字
        self._welcome = ArtHeading('growth', '打卡、成就与个人资料，都在这里。')
        self._heading = self._welcome.subtitle   # 兼容既有属性名
        self._subtitle = self._welcome.subtitle
        header = QWidget()
        header_v = QVBoxLayout(header)
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(8)
        header_v.addWidget(self._welcome)
        self._page.set_header(header)

        self._build_sections()

        self.set_compact(is_compact(*DEFAULT_SIZE))
        self._sync_scale()
        self.apply_theme()
        self._ready = True
        self.refresh()

    # ---------- 尺度系数（弹性尺寸） ----------
    def _sync_scale(self) -> None:
        """按当前窗口尺寸更新尺度系数，并重排卡片高度/宽度（字号不变）。"""
        window = self.window()
        width = window.width() if window is not None and window is not self else self.width()
        height = window.height() if window is not None and window is not self else self.height()
        self._scale = scale_for(max(1, width), max(1, height))
        self._cell_radius = _interp(CARD_RADIUS_MIN, CARD_RADIUS_MAX, self._scale)
        self._day_cell_h = _interp(DAY_CELL_MIN_H_MIN, DAY_CELL_MIN_H_MAX, self._scale)
        self._chip_h = _interp(MILESTONE_CHIP_H_MIN, MILESTONE_CHIP_H_MAX, self._scale)
        if getattr(self, '_status_card', None) is not None:
            width = _interp(STATUS_WIDTH_COMPACT, STATUS_WIDTH_MAX, self._scale)
            if self._compact:
                width = min(width, STATUS_WIDTH_COMPACT)
            self._status_card.setFixedWidth(width)
        if getattr(self, '_actions_host', None) is not None:
            self._sync_action_wrap()
        if getattr(self, '_bottom_room', None) is not None:
            self._bottom_room.changeSize(0, _interp(16, 28, self._scale))

    # ---------- 静态结构 ----------
    def _build_sections(self) -> None:
        # 纸张首行留给主窗口挂入的成长子导航（打卡/成就/个人资料），这里直接追加内容
        # 连签大数字 + 今日状态
        head = QWidget()
        head_row = QHBoxLayout(head)
        head_row.setContentsMargins(0, 0, 0, 0)
        head_row.setSpacing(16)

        # 连签大数字（设计稿的 "连续签到 7 天" 一行）；本月数据并入同一行的辅助文字，
        # 不再单占一行，紧凑档首屏留给格子与状态卡。
        self._streak_label = _label('连续签到', role='paperField')
        head_row.addWidget(self._streak_label, 0, Qt.AlignVCenter)
        self._streak_value = _label('0', role='paperMetric')
        head_row.addWidget(self._streak_value, 0, Qt.AlignVCenter)
        self._streak_unit = _label('天', role='paperField')
        head_row.addWidget(self._streak_unit, 0, Qt.AlignVCenter)
        # 月份/本月汇总仍可见（13px 辅助行），但不单独占一块高度
        self._streak_meta = _label('', role='paperMuted')
        head_row.addWidget(self._streak_meta, 1, Qt.AlignVCenter)

        # 深色状态卡（设计稿右侧深靛底 + 奖杯 + 白字）
        self._status_card = QFrame()
        self._status_card.setFixedWidth(STATUS_WIDTH)
        # 图标在 _build_status 里按状态换成矢量字形（深色卡上不用 emoji 字符）
        self._status_icon = _label('', size=32, align=Qt.AlignCenter)
        self._status_title = _label('', size=18, bold=True, wrap=True,
                                    align=Qt.AlignCenter)
        self._status_hint = _label('', wrap=True, align=Qt.AlignCenter)
        self._status_text_col = QWidget()
        text_col = QVBoxLayout(self._status_text_col)
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)
        text_col.addWidget(self._status_title)
        text_col.addWidget(self._status_hint)
        self._status_vertical = None      # 由 _reflow_status_card 按尺寸档决定
        self._reflow_status_card(False)
        # 卡与连签行顶端对齐（设计稿同一条基线）；否则竖排卡会把左侧文字推到行中间，
        # 页签下方多出一段空白。
        head_row.addWidget(self._status_card, 0, Qt.AlignTop)
        head_row.setAlignment(Qt.AlignTop)
        self._content.addWidget(head)

        # 最近 7 天格子（设计稿为 7 格等宽主视图；日期/状态见格子，不另加标题行）
        strip_widget = QWidget()
        self._strip_grid = QGridLayout(strip_widget)
        self._strip_grid.setContentsMargins(0, 0, 0, 0)
        self._strip_grid.setSpacing(8)
        for col in range(STRIP_DAYS):
            self._strip_grid.setColumnStretch(col, 1)
        self._content.addWidget(strip_widget)

        # 月历（既有能力）：折叠承载，默认收起，页面不因此变长
        self._calendar_disc = Disclosure('打卡日历')
        self._calendar_disc.toggle.setAccessibleName('打卡日历（展开/收起）')
        self._build_calendar_nav(self._calendar_disc.content)
        self._calendar_disc.toggle.toggled.connect(self._on_calendar_toggled)
        detail_row = QHBoxLayout()
        detail_row.setContentsMargins(0, 0, 0, 0)
        detail_row.setSpacing(12)
        detail_row.addWidget(self._calendar_disc, 1)
        self._content.addLayout(detail_row)

        # 里程碑礼包（标题 + 说明 + 芯片网格算一块：紧凑档把标题行与说明并成一行，
        # 避免「说明+芯片」被视口底边切成半截）
        ms_head = QWidget()
        ms_head_row = QHBoxLayout(ms_head)
        ms_head_row.setContentsMargins(0, 0, 0, 0)
        ms_head_row.setSpacing(8)
        self._ms_title = _label('连签里程碑礼包', role='paperField')
        ms_head_row.addWidget(self._ms_title, 0)
        self._ms_label = _label('', role='paperMuted')
        ms_head_row.addWidget(self._ms_label, 1)
        self._ms_head = ms_head
        self._milestone_disc = Disclosure('连签里程碑礼包')
        self._milestone_disc.content.addWidget(ms_head)
        self._milestone_disc.toggle.toggled.connect(lambda *_: self._fit_paper())
        detail_row.addWidget(self._milestone_disc, 1)
        ms_widget = QWidget()
        self._ms_host = ms_widget
        self._ms_grid = QGridLayout(ms_widget)
        self._ms_grid.setContentsMargins(0, 0, 0, 0)
        self._ms_grid.setSpacing(8)
        for col in range(MILESTONE_COLS):
            self._ms_grid.setColumnStretch(col, 1)
        self._milestone_disc.content.addWidget(ms_widget)

        # 道具库存
        self._inventory = QFrame()
        inv_row = QHBoxLayout(self._inventory)
        inv_row.setContentsMargins(14, 10, 14, 10)
        inv_row.setSpacing(10)
        inv_row.addWidget(_label('道具库存', role='paperField'))
        self._inv_label = _label('', role='paperMuted', wrap=True)
        inv_row.addWidget(self._inv_label, 1)
        self._content.addWidget(self._inventory)

        # 动作（同屏一个显著主动作）：两个按钮优先同排，一行放不下时整行换行；
        # 高度不低于 44px（口径：不允许被压扁，也不允许藏按钮）。
        self._repair_btn = QPushButton('使用补签卡')
        self._repair_btn.setProperty('buttonRole', 'secondary')
        self._repair_btn.setAccessibleName('使用补签卡补签昨天')
        self._repair_btn.setMinimumHeight(ACTION_BUTTON_MIN_H)
        self._repair_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._repair_btn.clicked.connect(self._repair)
        self._boost_btn = QPushButton('使用经验加成卡（30 分钟 ×2）')
        self._boost_btn.setProperty('buttonRole', 'primary')
        self._boost_btn.setAccessibleName('使用经验加成卡')
        self._boost_btn.setMinimumHeight(ACTION_BUTTON_MIN_H)
        self._boost_btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._boost_btn.clicked.connect(self._use_boost)
        self._actions_host = QWidget()
        self._actions = QGridLayout(self._actions_host)
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setHorizontalSpacing(12)
        self._actions.setVerticalSpacing(10)
        self._actions_wrapped = None
        self._place_actions(False)
        self._content.addWidget(self._actions_host)
        # 纸张底部呼吸位：动作按钮不贴纸张底边。否则页面滚动到底时按钮紧贴底栏，
        # 看起来像「按钮盒被底栏压住」（实测紧凑档按钮底 543 / 底栏顶 568 只剩 25px）。
        self._bottom_room = QSpacerItem(
            0, _interp(16, 28, self._scale), QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._content.addSpacerItem(self._bottom_room)
        self._content.addStretch(1)

    def _place_actions(self, wrapped: bool) -> None:
        """动作按钮排布：同排（两列）或换行（一列）。

        换行判据是「两个按钮的完整宽度 + 列距」是否超过纸张内容宽度——按钮在换行
        模式下各自占满一行，高度仍是 44px 以上，不被压扁也不被隐藏。
        """
        if self._actions_wrapped == wrapped:
            return
        self._actions_wrapped = wrapped
        while self._actions.count():
            self._actions.takeAt(0)
        if wrapped:
            self._actions.addWidget(self._repair_btn, 0, 0)
            self._actions.addWidget(self._boost_btn, 1, 0)
        else:
            self._actions.addWidget(self._repair_btn, 0, 0)
            self._actions.addWidget(self._boost_btn, 0, 1)
            self._actions.setColumnStretch(1, 1)
            self._actions.setColumnStretch(0, 0)
        self._actions.activate()

    def _sync_action_wrap(self) -> None:
        """按当前纸张可用宽度决定两按钮同排还是换行。"""
        margins = self._content.contentsMargins()
        paper = self._paper.width() if self._paper is not None else 720
        avail = max(200, paper - margins.left() - margins.right())
        need = (self._repair_btn.sizeHint().width()
                + self._boost_btn.sizeHint().width()
                + self._actions.horizontalSpacing())
        self._place_actions(need > avail)

    def _sync_action_heights(self) -> None:
        """动作按钮高度：不低于 44px（紧凑/常规都成立；口径不允许压扁按钮）。

        单独成方法是因为主题 QSS 重新 polish 会复位 Qt 的最小尺寸约束，
        所以主题切换、紧凑切换、刷新后都要再设一次。
        """
        height = max(ACTION_BUTTON_MIN_H,
                     BUTTON_HEIGHT_COMPACT if self._compact else BUTTON_HEIGHT)
        for button in (getattr(self, '_repair_btn', None), getattr(self, '_boost_btn', None)):
            if button is None:
                continue
            button.setMinimumHeight(height)
            button.setMaximumHeight(height + 12)
        nav_height = CAL_NAV_HEIGHT_COMPACT if self._compact else CAL_NAV_HEIGHT
        for button in (getattr(self, '_prev_btn', None), getattr(self, '_next_btn', None)):
            if button is None:
                continue
            button.setMinimumHeight(nav_height)
            button.setMaximumHeight(nav_height + 8)

    def _reflow_status_card(self, compact: bool) -> None:
        """状态卡两种排布，内容相同、只用尺寸档切换。

        - 常规档（1440×1024）：奖杯在上、标题与说明在下（设计稿 growth-1440 的卡内排布）
        - 紧凑档：图标在左、文字在右。卡片宽度固定 232，竖排在紧凑档会占掉 116px 行高，
          把里程碑首行和道具库存挤出 900×640 首屏；横排后整块降到约 80px，
          主内容与里程碑首行都能完整落在第一屏。
        """
        if self._status_vertical == (not compact):
            return
        self._status_vertical = not compact
        old = self._status_card.layout()
        if old is not None:
            while old.count():
                item = old.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
            # QWidget 不允许在已有布局上再 setLayout：把旧布局挂到一次性哑控件上，
            # 随哑控件一起销毁，才能给卡片换成另一种方向的布局。
            holder = QWidget()
            holder.setLayout(old)
            holder.deleteLater()
        layout = QHBoxLayout(self._status_card) if compact else QVBoxLayout(self._status_card)
        if not compact:
            layout.setContentsMargins(16, 12, 16, 12)
            layout.setSpacing(4)
            layout.addWidget(self._status_icon)
            self._status_icon.setAlignment(Qt.AlignCenter)
            self._status_title.setAlignment(Qt.AlignCenter)
            self._status_hint.setAlignment(Qt.AlignCenter)
            self._status_text_col.setParent(self._status_card)
            layout.addWidget(self._status_text_col)
            layout.addStretch(1)
        else:
            layout.setContentsMargins(14, 10, 14, 10)
            layout.setSpacing(12)
            self._status_icon.setAlignment(Qt.AlignCenter)
            self._status_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self._status_hint.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            layout.addWidget(self._status_icon, 0, Qt.AlignVCenter)
            self._status_text_col.setParent(self._status_card)
            layout.addWidget(self._status_text_col, 1)
        layout.activate()
        self._status_card.show()
        self._status_card.updateGeometry()
        self._status_card.update()

    def _build_calendar_nav(self, layout) -> None:
        """折叠区内容：‹ 上月 / 「YYYY 年 M 月」 / 下月 › + 按月网格（self._cal）。"""
        host = QWidget()
        column = QVBoxLayout(host)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(8)

        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(8)
        self._prev_btn = QPushButton('‹ 上月')
        self._prev_btn.setProperty('buttonRole', 'secondary')
        self._prev_btn.setAccessibleName('查看上一个月')
        self._prev_btn.clicked.connect(lambda: self._shift_month(-1))
        nav.addWidget(self._prev_btn)
        self._month_label = _label('', role='paperField')
        self._month_label.setAlignment(Qt.AlignCenter)
        self._month_label.setMinimumWidth(120)
        nav.addWidget(self._month_label)
        self._next_btn = QPushButton('下月 ›')
        self._next_btn.setProperty('buttonRole', 'secondary')
        self._next_btn.setAccessibleName('查看下一个月')
        self._next_btn.clicked.connect(lambda: self._shift_month(1))
        nav.addWidget(self._next_btn)
        nav.addStretch(1)
        column.addLayout(nav)

        cal_host = QWidget()
        self._cal = QGridLayout(cal_host)
        self._cal.setContentsMargins(0, 0, 0, 0)
        self._cal.setSpacing(6)
        self._cal.setColumnStretch(7, 1)   # 单元格固定宽，多余的横向空间留在右侧
        column.addWidget(cal_host)
        layout.addWidget(host)

    # ---------- 主题 ----------
    def apply_theme(self):
        """主题切换：页头取画布语义色（QSS 已给），这里补一行高度并重绘纸张内容。"""
        # QSS 字号晚于 sizeHint 生效，显式给一行文字高度，避免中文被裁掉字头
        self._subtitle.setMinimumHeight(self._subtitle.fontMetrics().height() + 6)
        # 主题 QSS 重新 polish 会复位最小高度约束，按钮高度要再设一次
        self._sync_action_heights()
        self._paper.update()
        if self._ready:
            self.refresh()

    # ---------- 刷新 ----------
    def refresh(self, *_):
        today = date.fromisoformat(self._engine.current_day())
        streak = self._repo.get_streak(_dstr(today)) or self._repo.get_streak(
            _dstr(today - timedelta(days=1)))
        cards = self._rewards.count('makeup_card')
        boost = self._rewards.count('exp_boost')
        titles = self._rewards.titles()
        signed_today = self._repo.has_checkin(_dstr(today))

        self._streak_value.setText(str(streak))
        first = today.replace(day=1)
        month_rows = self._repo.get_checkins(_dstr(first), _dstr(today))
        month_best = max((r['streak'] for r in month_rows.values()), default=0)
        self._streak_meta.setText(
            f'{today.strftime("%m月%d日")}　本月已签 {len(month_rows)} 天'
            f'　最高连签 {month_best} 天')
        self._streak_meta.setToolTip(
            f'今天 {today.isoformat()}　本月已签 {len(month_rows)} 天'
            f'　本月最高连签 {month_best} 天')

        self._build_strip(today)
        signed_today = self._repo.has_checkin(_dstr(today))
        self._build_status(signed_today, streak)
        self._build_calendar()
        self._build_milestones()
        self._build_inventory(boost, cards, titles)

        missed = not self._repo.has_checkin(_dstr(today - timedelta(days=1)))
        self._repair_btn.setEnabled(bool(missed and cards > 0))
        self._repair_btn.setText(
            '使用补签卡补签昨天' if missed else '昨日已打卡')
        # 按钮文案变了，同排/换行的判据跟着变（空间不足时整行换行，高度仍 ≥44px）
        self._sync_action_wrap()
        # 重建后的尺寸提示需要一次布局激活才生效；离屏截图/紧凑切换可能只跑一轮事件，
        # 不激活会让大数字停在旧几何上被裁剪
        _activate_tree(self)
        self._fit_paper()

    def _fit_paper(self) -> None:
        """按内容自然高度给纸张定最小高度，并让骨架滚动区立刻重算。

        PaperPage 的滚动区只在视口尺寸变化时重算；紧凑切换/重建内容后若不主动触发，
        纸张会被压到视口高度，纸张内的卡片会互相重叠（900x640 下真实出现过）。
        - 高度用 heightForWidth 逐项累加：换行标签的 sizeHint 不含换行，直接用会低估
        - 重建出来的子控件若仍处于「显式隐藏」，布局会把它算成 0，
          所以重建时逐个 show()（见 _build_calendar / _build_milestones）
        """
        self._content.activate()
        margins = self._content.contentsMargins()
        avail = max(1, self._paper.width() - margins.left() - margins.right())
        spacing = self._content.spacing()
        total = 0
        counted = 0
        for index in range(self._content.count()):
            item = self._content.itemAt(index)
            spacer = item.spacerItem()
            if spacer is not None and (
                    spacer.sizePolicy().verticalPolicy() == QSizePolicy.Expanding):
                continue  # 末尾伸缩空白不吃自然高度
            widget = item.widget()
            if widget is not None:
                # 用控件自身的 sizeHint：隐藏控件的 item.sizeHint() 是 0，
                # 主窗口的成长子导航在切换瞬间可能还没显示出来
                if widget.hasHeightForWidth():
                    height = max(widget.minimumSize().height(),
                                 widget.heightForWidth(avail))
                else:
                    height = widget.sizeHint().height()
                height = max(height, widget.minimumSize().height())
            else:
                height = item.sizeHint().height()
            if height <= 0:
                continue
            total += height
            counted += 1
        needed = total + spacing * max(0, counted - 1) + margins.top() + margins.bottom()
        # 与布局自身的尺寸提示取大：换行标签的提示会偏保守，取大只会多留一点纸面空白，
        # 不会把内容压到视口高度
        needed = max(needed, self._content.sizeHint().height())
        if needed > 0 and needed != self._paper_min:
            self._paper_min = needed
            self._paper.setMinimumHeight(needed)
        holder = self._page.scroll.widget()
        if holder is not None:
            layout = holder.layout()
            top = layout.contentsMargins().top() if layout is not None else 0
            holder.resize(holder.width(), max(holder.height(), needed + top))

    def _build_status(self, signed_today: bool, streak: int) -> None:
        """今日签到状态卡：深色表面（设计稿 growth-1440 右侧那一块），文字走 surface 语义色。

        与训练页输入区、今日页练习卡同一套深色语言：不因为「底」是奶油纸就把这张卡
        也做成浅色；两张卡（已签/未签）都保持深色，只换图标与文案。
        图标用交付的线性 SVG 或自绘矢量，不用会在雅黑下变成空白方框的字符。
        """
        if signed_today:
            self._status_icon.setPixmap(_status_glyph('award', 34, P.accent_ochre))
            self._status_title.setText('今日已自动签到')
            # 单行短文案：卡片宽度固定，两行会把整张卡撑高 15px，首屏就少一行里程碑
            self._status_hint.setText(f'连续第 {streak} 天，别断在今天。')
        else:
            self._status_icon.setPixmap(_status_glyph('hourglass', 34, P.surface_muted))
            self._status_title.setText('今日还没签到')
            self._status_hint.setText('启动应用或日切时自动完成。')
        self._status_icon.setFixedSize(34, 34)
        _dark_card_style(self._status_card, 'checkinStatus', radius=self._cell_radius + 4)
        summary = getattr(self, '_strip_summary', '')
        if summary:
            self._status_hint.setToolTip(summary)
        self._status_icon.setStyleSheet('background: transparent;')
        self._status_title.setStyleSheet(
            f'color: {P.surface_text}; font-size: 18px; font-weight: 600;'
            f' background: transparent;')
        self._status_hint.setStyleSheet(
            f'color: {P.surface_muted}; font-size: 13px; background: transparent;')

    # ---------- 最近 7 天格子（主视图） ----------
    def _build_strip(self, today: date) -> None:
        _clear_layout(self._strip_grid)

        days = [today - timedelta(days=STRIP_DAYS - 1 - i) for i in range(STRIP_DAYS)]
        rows = self._repo.get_checkins(_dstr(days[0]), _dstr(days[-1]))
        signed = sum(1 for d in days if _dstr(d) in rows)
        # 「已签 n/7」并入连签行的辅助文字，省掉一行标题
        self._strip_summary = f'最近 7 天已签 {signed} / {STRIP_DAYS} 天'

        min_w = DAY_CELL_MIN_W_COMPACT if self._compact else DAY_CELL_MIN_W
        min_h = 64 if self._compact else self._day_cell_h
        for col, day in enumerate(days):
            state = _state_of(day, today, rows)
            cell = self._day_cell(day, state, rows.get(_dstr(day), {}))
            cell.setMinimumSize(min_w, min_h)
            self._strip_grid.addWidget(cell, 0, col)
            cell.show()   # 新建控件默认隐藏，布局会把隐藏项算成 0 高度

    def _day_cell(self, day: date, state: str, row: dict) -> QFrame:
        bg, border, dash, width, symbol, symbol_color, text = _state_style(state)
        cell = QFrame()
        cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        _card_style(cell, 'dayCell', bg, border, width=width, dash=dash,
                    radius=self._cell_radius)

        v = QVBoxLayout(cell)
        # 紧凑档格子矮一些（内边距 8→5），首屏才放得下 7 天格子 + 状态卡 + 里程碑首行
        pad = 5 if self._compact else 8
        v.setContentsMargins(6, pad, 6, pad)
        v.setSpacing(2)
        if not self._compact:
            v.addWidget(_label(f'周{WEEKDAYS[day.weekday()]}', size=13,
                               align=Qt.AlignCenter, color=P.paper_text))
        v.addWidget(_label(str(day.day), size=18, bold=True,
                           align=Qt.AlignCenter, color=P.paper_text))
        v.addWidget(_label(f'{symbol} {text}', size=13,
                           align=Qt.AlignCenter, color=symbol_color))
        cell.setToolTip(self._cell_tip(day, text, row))
        return cell

    @staticmethod
    def _cell_tip(day: date, text: str, row: dict) -> str:
        tip = f'{day.isoformat()}　{text}'
        if row:
            tip += f'　连签 {row.get("streak", 0)} 天'
            if row.get('card_used'):
                tip += '（补签）'
        return tip

    # ---------- 月历（既有能力，折叠区） ----------
    def _shift_month(self, delta: int) -> None:
        month = self._month.month + delta
        year = self._month.year + (month - 1) // 12
        self._month = date(year, (month - 1) % 12 + 1, 1)
        self._build_calendar()
        _activate_tree(self)
        self._fit_paper()

    def _on_calendar_toggled(self, expanded: bool) -> None:
        """展开后纸张要跟着变长（折叠区默认收起，不占页面高度）。"""
        if expanded:
            self._build_calendar()
        _activate_tree(self)
        self._fit_paper()

    def _build_calendar(self) -> None:
        """按月网格（self._cal）：‹ 上月 / 年月 / 下月 › 由 _shift_month 驱动。"""
        _clear_layout(self._cal)

        today = date.fromisoformat(self._engine.current_day())
        first = self._month
        last = date(first.year, first.month + 1, 1) - timedelta(days=1)
        rows = self._repo.get_checkins(_dstr(first), _dstr(last))
        self._month_label.setText(f'{first.year} 年 {first.month} 月')

        for i, weekday in enumerate(WEEKDAYS):
            head = _label(weekday, size=13, align=Qt.AlignCenter,
                          color=P.paper_muted)
            head.setFixedWidth(MONTH_CELL_COMPACT if self._compact else MONTH_CELL)
            self._cal.addWidget(head, 0, i)

        size = MONTH_CELL_COMPACT if self._compact else MONTH_CELL
        day = first
        row = 1
        for col in range(first.weekday() % 7):   # 周一=0：月初先补空格子
            spacer = QWidget()
            spacer.setFixedSize(size, size)
            self._cal.addWidget(spacer, row, col)
        while day <= last:
            col = day.weekday()
            state = _state_of(day, today, rows)
            cell = self._month_cell(day, state, rows.get(_dstr(day), {}))
            cell.setFixedSize(size, size)
            self._cal.addWidget(cell, row, col)
            cell.show()
            if col == 6:
                row += 1
            day += timedelta(days=1)

    def _month_cell(self, day: date, state: str, row: dict) -> QFrame:
        bg, border, dash, width, symbol, symbol_color, text = _state_style(state)
        cell = QFrame()
        _card_style(cell, 'monthCell', bg, border, radius=10, width=width, dash=dash)
        v = QVBoxLayout(cell)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(0)
        v.addWidget(_label(str(day.day), size=15, bold=True,
                           align=Qt.AlignCenter, color=P.paper_text))
        # 46/44 的格子里放不下「○ 今天 · 未签」，今天用文字本身表达状态
        mark = '今天' if state == STATE_TODAY_MISS else f'{symbol} {text}'
        v.addWidget(_label(mark, size=13, align=Qt.AlignCenter, color=symbol_color))
        cell.setToolTip(self._cell_tip(day, text, row))
        return cell

    # ---------- 里程碑 ----------
    def _build_milestones(self) -> None:
        cfg = self._balance['checkin']
        milestones = cfg.get('milestones', [])
        rewards = cfg.get('milestone_rewards', {})
        granted = self._repo.get_setting('milestone_granted', '[]')
        try:
            granted = json.loads(granted)
        except (ValueError, TypeError):
            granted = []

        _clear_layout(self._ms_grid)
        for idx, days in enumerate(milestones):
            chip = self._milestone_chip(days, rewards.get(str(days), {}),
                                        days in granted)
            self._ms_grid.addWidget(chip, idx // MILESTONE_COLS,
                                    idx % MILESTONE_COLS)
            chip.show()   # 新建控件默认隐藏，布局会把隐藏项算成 0 高度
        full = f'连签达到里程碑天数时自动发放，已发放 {len(granted)} / {len(milestones)} 档。'
        # 紧凑档把标题行与说明并成一行：说明用短文案，完整文案留给工具提示
        self._ms_label.setText(
            f'已发放 {len(granted)} / {len(milestones)} 档' if self._compact else full)
        self._ms_label.setToolTip(full)
        self._ms_title.setToolTip(full)
        self._fit_milestone_rows()

    def _fit_milestone_rows(self) -> None:
        """紧凑档让里程碑芯片整行落在滚动区里，不出现「被切成半张卡」。

        早先的做法是把网格高度锁在第一行（88px），但纸张比视口高、滚动到底时，
        第二行会被网格边界**硬裁**成半张（实测截图里「第 60 天 / 100 exp + 加成卡×1」
        只剩上半截）。这里的口径改成：行高有下限、高度**不设上限**——整行要么完整
        在可视区里，要么完整落到下方的滚动区，不会被裁切。
        """
        rows = self._ms_grid.rowCount()
        if rows <= 0:
            return
        row_h = 0
        for col in range(self._ms_grid.columnCount()):
            item = self._ms_grid.itemAtPosition(0, col)
            if item is not None and item.widget() is not None:
                row_h = max(row_h, item.widget().sizeHint().height())
        row_h = max(row_h, self._chip_h)
        self._ms_host.setMinimumHeight(row_h)
        self._ms_host.setMaximumHeight(16777215)

    def _milestone_chip(self, days: int, reward: dict, granted: bool) -> QFrame:
        chip = QFrame()
        # 高度随尺度系数在区间内取值（紧凑档取区间下限，首行要整体落在首屏内）
        compact = bool(getattr(self, '_compact', False))
        height = self._chip_h
        if compact:
            height = min(height, MILESTONE_CHIP_H_MIN)
        chip.setMinimumHeight(height)
        chip.setMaximumHeight(max(height, MILESTONE_CHIP_H_MAX))
        chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if granted:
            bg, border = rgba(P.primary, 0.26), ''
            mark, mark_color = '√ 已发放', P.success_on_paper
        else:
            # 未达成：同色系虚线淡边（配方口径：大面积卡片不描深灰硬边；虚线是
            # 「非颜色」的禁用线索，与已发放形成可辨差异）
            bg, border = rgba(P.paper_text, 0.055), rgba(P.paper_muted, 0.42)
            mark, mark_color = '未达成', P.paper_muted
        _card_style(chip, 'milestoneChip', bg, border, dash=not granted,
                    radius=self._cell_radius)

        v = QVBoxLayout(chip)
        pad = 7 if compact else 8
        v.setContentsMargins(12, pad, 12, pad)
        v.setSpacing(2)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        head.addWidget(_label(f'第 {days} 天', size=14, bold=True,
                              color=P.paper_text))
        head.addStretch(1)
        if not granted:
            lock = QLabel()
            lock.setPixmap(lock_pixmap(mark_color, 14))
            lock.setFixedSize(14, 14)
            lock.setToolTip('未达成')
            head.addWidget(lock, 0, Qt.AlignVCenter)
        head.addWidget(_label(mark, size=13, color=mark_color), 0, Qt.AlignVCenter)
        v.addLayout(head)
        v.addWidget(_label(self._reward_text(reward), size=13, wrap=True,
                           color=P.paper_muted))
        v.addStretch(1)
        chip.setToolTip(f'连签 {days} 天奖励：{self._reward_text(reward)}')
        return chip

    @staticmethod
    def _reward_text(reward: dict) -> str:
        return ' + '.join(
            (f'{qty} exp' if kind == 'exp'
             else f'补签卡×{qty}' if kind == 'makeup_card'
             else f'加成卡×{qty}' if kind == 'exp_boost'
             else f'称号「{qty}」')
            for kind, qty in reward.items()) or '暂无奖励'

    # ---------- 库存与加成卡 ----------
    def _build_inventory(self, boost: int, cards: int, titles: list) -> None:
        # 同色系浅填充 + 大圆角，无深灰硬边（配方第 96/97 行的纸面浅卡）
        _card_style(self._inventory, 'checkinInventory',
                    rgba(P.paper_text, 0.055), radius=self._cell_radius,
                    pad=' padding: 10px 14px;')
        parts = [f'补签卡 ×{cards}', f'经验加成卡 ×{boost}']
        if self._rewards.boost_active():
            parts.append('加成卡生效中（×2）')
        if titles:
            parts.append('称号：' + '、'.join(titles))
        self._inv_label.setText('　·　'.join(parts))

        if self._rewards.boost_active():
            self._boost_btn.setText('经验加成卡生效中（×2）…')
            self._boost_btn.setEnabled(False)
        else:
            self._boost_btn.setText('使用经验加成卡（30 分钟 ×2）')
            self._boost_btn.setEnabled(boost > 0)

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
                # 先补签成功再扣卡（曾先扣卡后补签，失败时吞卡，v0.8.9 修复）
                r = self._checkin.apply_makeup_card(missed, today_iso=_dstr(today))
                if r:
                    self._repo.use_reward('makeup_card')
                    self.refresh()

    # ---------- 版式 ----------
    def _is_compact_now(self) -> bool:
        """与主窗口同口径：有顶层窗口时按窗口尺寸判断，避免两处结论不一致。"""
        from ..widgets.responsive import stage_layout_for
        return stage_layout_for(self).compact

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        changed = compact != self._compact
        self._compact = compact
        # 骨架统一调整外边距与纸张宽度上限（1100/760，左对齐）
        self._page.set_compact(compact)
        # 口径（DECISIONS.md 第 3 条）：成长/打卡页紧凑档**纸面内容**内边距 16px
        # （标准档仍 32px），外层 24px 页面边距不动。
        pad = GROWTH_PAD_COMPACT if compact else PAPER_PAD
        self._content.setContentsMargins(pad, pad, pad, pad)
        # 紧凑档区块间距一起收，把首屏留给连签数字 + 7 天格子 + 状态卡；
        # 字号不动（规范：紧凑只降内边距与控件高度）
        self._content.setSpacing(8 if compact else 14)
        self._ms_grid.setSpacing(8 if compact else 10)
        self._sync_action_heights()
        self._sync_scale()
        if getattr(self, '_ms_grid', None) is not None:
            self._fit_milestone_rows()
        self._reflow_status_card(compact)
        if changed and self._ready:
            self.refresh()

    def resizeEvent(self, event):
        if getattr(self, '_page', None) is not None:
            compact = self._is_compact_now()
            # 无条件套用一遍尺寸档：`PaperPage.set_compact` 会连带重设纸张内边距，
            # 而本页的口径是「紧凑 16 / 标准 32」（成长的 16px 只在紧凑档）。
            self.set_compact(compact)
            # 纸张宽度/窗口尺寸变化：尺度系数、按钮换行与纸张高度都要重算，
            # 避免只跑一轮事件时内容停在旧几何/被压到视口高度
            self._reflow_all()
        super().resizeEvent(event)

    def _reflow_all(self) -> None:
        """按当前纸张宽度重建与尺寸相关的部分（格子/芯片高度、按钮排布）。"""
        if self._ready:
            self._build_strip(date.fromisoformat(self._engine.current_day()))
            self._build_milestones()
        self._sync_action_wrap()
        _activate_tree(self)
        self._fit_paper()

    def showEvent(self, event):
        if getattr(self, '_page', None) is not None:
            self.set_compact(self._is_compact_now())
            self._sync_scale()
            _activate_tree(self)
            self._fit_paper()
        super().showEvent(event)
