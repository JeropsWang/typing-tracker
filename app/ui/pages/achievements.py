"""成就墙：37 项成就以徽章卡片展示（图案 + 名称 + 状态 + 奖励）。

- 奶油纸张承载分类页签与成就卡片，卡片按行列整齐对齐（数据列不做非对称）
- 图标按素材包 v2 `achievement-map.json` 的 4 类 × 3 态映射（speed / chars /
  min_acc / total_acc），**状态一律来自 AchievementService 返回的
  `unlocked_at` / `claimed`，不由图标或 code 推算**；资源缺失时回退
  `config/achievements.json` 的 emoji（配置本身不改）。
- 状态用「图标形态 + 文字 + 填充深浅」三重表达：已领取打勾徽章 / 待领取高亮徽章 /
  未解锁灰底 + 挂锁（挂锁是自绘矢量，不用 Microsoft YaHei UI 里会渲染成空白方框的
  🔒 字符）。
- 卡片按配方改为「同色系浅填充 + 更大圆角 + 无描边」的贴纸感；高度用上下限区间，
  由 `scale_for` 尺度系数与布局 stretch 决定，不再是一个写死的像素。
- 解锁后的奖励仍由用户在卡片上手动领取（AchievementService.claim），领取后刷新。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ..palette import P
from ..widgets import design as _design
from ..widgets.design import ArtHeading, PaperPage, is_compact, rgba


def scale_for(width: int, height: int) -> float:
    """共享层尺度系数 `design.scale_factor`（唯一口径，不自己另造 token）。

    共享层缺失该接口时退回同一公式，保证页面自洽。
    """
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

CAT_TITLES = {
    'speed': '平均速度',
    'chars': '累计字数',
    'min_acc': '每分钟正确率',
    'total_acc': '总正确率',
}
CATS = ['speed', 'chars', 'min_acc', 'total_acc']

# 版式 token（纸张位置/宽度由 PaperPage 统一：1100/760 宽，左右 48/24）
# 卡片高度按内容自然高度定：40 图标 + 23 名称 + 51 说明 + 34 奖励 + 状态行/按钮行 + 行距与内边距。
# 这里给「区间」而不是单值：下限保证内容不被压扁，上限配合 Expanding 让一行卡片
# 随可用高度长大；具体值由 scale_for 尺度系数在区间内插值。
CARD_HEIGHT_MIN, CARD_HEIGHT_MAX = 168, 190
CARD_MIN_WIDTH = 160
CARD_MIN_WIDTH_MAX = 240
CARD_COLS = 4
CARD_SPACING_MIN, CARD_SPACING_MAX = 10, 14
DESC_HEIGHT, DESC_HEIGHT_MAX = 51, 58
REWARD_HEIGHT, REWARD_HEIGHT_MAX = 34, 38
ICON_SIZE, ICON_SIZE_MAX = 40, 50

DEFAULT_SIZE = (900, 640)

# 成就图标资源：素材包 v2 复制到应用资源目录；映射 JSON 与 SVG 同级。
ASSETS = Path(__file__).resolve().parents[1] / 'assets'
ACHIEVEMENT_DIR = ASSETS / 'achievements'
ACHIEVEMENT_MAP = ASSETS / 'achievement-map.json'
FALLBACK_MAP = (Path(__file__).resolve().parents[3] / '.local' / 'ui-night-stage'
                / 'deepseek-materials' / 'v2' / 'achievement-map.json')
_ICON_CACHE: dict = {}
_MAP_CACHE: dict = {}


def _interp(low: int, high: int, scale: float) -> int:
    """在上下限区间里按尺度系数取值（0.85 → low，1.0 → 中值，1.15 → high）。"""
    t = max(0.0, min(1.0, (float(scale) - 0.85) / 0.30))
    return int(round(low + (high - low) * t))


def _load_map() -> dict:
    """读取 UI 侧成就图标映射；缺失时返回空字典（调用方回退 emoji）。"""
    if 'data' in _MAP_CACHE:
        return _MAP_CACHE['data']
    data: dict = {}
    for path in (ACHIEVEMENT_MAP, FALLBACK_MAP):
        try:
            if path.is_file():
                data = json.loads(path.read_text(encoding='utf-8'))
                break
        except (OSError, ValueError):
            data = {}
    _MAP_CACHE['data'] = data
    return data


def achievement_icon_path(code: str, *, unlocked: bool, claimed: bool):
    """按服务给出的状态选资源（未解锁 / 已解锁待领取 / 已领取）。

    返回 `None` 表示没有可用资源，调用方回退 `config/achievements.json` 的 emoji。
    资源路径以映射表里的 `assets/...` 相对路径为基准（`assets` 的父目录是
    `app/ui/`），文件不存在时同样回退。
    """
    item = (_load_map().get('items') or {}).get(code)
    if not item:
        return None
    state = 'claimed' if (claimed and unlocked) else ('unlocked' if unlocked else 'locked')
    rel = (item.get('states') or {}).get(state)
    if not rel:
        return None
    path = ASSETS.parent / rel
    return path if path.is_file() else None


def achievement_icon(code: str, *, unlocked: bool, claimed: bool, size: int = ICON_SIZE):
    """渲染成就 SVG 为 QPixmap；无资源返回 None（供页面回退 emoji）。"""
    path = achievement_icon_path(code, unlocked=unlocked, claimed=claimed)
    if path is None:
        return None
    key = (str(path), int(size))
    if key not in _ICON_CACHE:
        pixmap = QPixmap(int(size), int(size))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            painter.end()
            return None
        renderer.render(painter, QRectF(0, 0, int(size), int(size)))
        painter.end()
        _ICON_CACHE[key] = pixmap
    return _ICON_CACHE[key]


# 未解锁挂锁：自绘矢量（YaHei UI 下 🔒 是空白方框，不能用字符）
_LOCK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" '
    'stroke="{c}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M5 7.2V5.4a3 3 0 0 1 6 0v1.8"/>'
    '<rect x="3.4" y="7.2" width="9.2" height="6.4" rx="2.2"/></svg>'
)
_LOCK_CACHE: dict = {}


def lock_pixmap(color: str, size: int = 14) -> QPixmap:
    key = (color, int(size))
    if key not in _LOCK_CACHE:
        pixmap = QPixmap(int(size), int(size))
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        QSvgRenderer(QByteArray(_LOCK_SVG.replace('{c}', color).encode('utf-8'))).render(painter)
        painter.end()
        _LOCK_CACHE[key] = pixmap
    return _LOCK_CACHE[key]


def _card_style(widget: QFrame, name: str, bg: str, border: str = '', *,
                radius: int = 16, width: int = 1, dash: bool = False) -> None:
    """纸张上的卡片：同色系浅填充 + 大圆角；无描边时不发 border 声明。"""
    widget.setObjectName(name)
    edge = (f' border: {width}px {"dashed" if dash else "solid"} {border};'
            if border else ' border: none;')
    widget.setStyleSheet(
        f'QFrame#{name} {{ background: {bg};{edge} border-radius: {radius}px; }}')


def _label(text: str, role: str = '', size: int = 0, *, bold: bool = False,
           align=None, wrap: bool = False, color: str = '') -> QLabel:
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


def _text_line(pixel: int, *, bold: bool = False) -> int:
    """按 QSS 声明字号量一行文字高度（不同字体/DPR 下同一个 px 值行高不同）。"""
    from PySide6.QtGui import QFontMetrics
    probe = QLabel('Ag字')
    css = f'font-size:{int(pixel)}px;'
    if bold:
        css += 'font-weight:600;'
    probe.setStyleSheet(css)
    probe.ensurePolished()
    metrics = QFontMetrics(probe.font())
    return max(int(round(pixel * 1.4)), metrics.height(), probe.sizeHint().height()) + 4


def _wrapped_lines(text: str, pixel: int, width: int, *, bold: bool = False) -> int:
    """文字在给定宽度下需要几行（用真实字体度量，不靠猜）。"""
    from PySide6.QtGui import QFontMetrics
    probe = QLabel(text)
    css = f'font-size:{int(pixel)}px;'
    if bold:
        css += 'font-weight:600;'
    probe.setStyleSheet(css)
    probe.ensurePolished()
    metrics = QFontMetrics(probe.font())
    line = metrics.height()
    if line <= 0:
        return 1
    rect = metrics.boundingRect(0, 0, max(24, int(width)), 10000,
                               int(Qt.TextWordWrap), text)
    return max(1, (rect.height() + line - 1) // line)


def _activate_tree(widget: QWidget) -> None:
    """递归激活布局树（离屏截图/紧凑切换可能只跑一轮事件循环）。"""
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        _activate_tree(child)


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
        self._compact = None
        self._paper_min = 0
        self._ready = False
        self._scale = scale_for(*DEFAULT_SIZE)
        self._card_min_h = CARD_HEIGHT_MIN
        self._card_max_h = CARD_HEIGHT_MAX
        self._desc_h = DESC_HEIGHT
        self._reward_h = REWARD_HEIGHT
        self._icon_px = ICON_SIZE

        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 页面骨架：纸张之外的页头（画布上）+ 左侧奶油纸张（上限 1100/760 宽）
        self._page = PaperPage(self, compact=is_compact(*DEFAULT_SIZE))
        self._paper = self._page.paper
        self._content = self._page.body
        self._content.setSpacing(12)
        root.addWidget(self._page)

        # 交付的转曲艺术标题（成长三页共用 role='growth'）；副标题仍是普通可读文字
        self._welcome = ArtHeading('growth', '解锁的成就会在这里亮起来，奖励需要手动领取。')
        self._heading = self._welcome.subtitle   # 兼容既有属性名
        self._subtitle = self._welcome.subtitle
        header = QWidget()
        header_v = QVBoxLayout(header)
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(8)
        header_v.addWidget(self._welcome)
        self._page.set_header(header)

        # 纸张首行留给主窗口挂入的成长子导航（打卡/成就/个人资料）
        self._summary = _label('', role='paperMuted', wrap=True)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._summary, 1)
        self._pending_badge = _label('', size=14, bold=True)
        head.addWidget(self._pending_badge, 0, Qt.AlignTop)
        self._content.addLayout(head)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        # 4 个短页签在 900 宽度下也放得下；关掉滚动按钮，避免滚动箭头压住页签文字
        self._tabs.setUsesScrollButtons(False)
        # 高度优先跟卡片墙自然高度（页内滚动统一交给 PaperPage，不做滚动套滚动）；
        # Preferred 而不是 Minimum/Fixed：QTabWidget 的 minimumSizeHint 会反过来
        # 把纸张撑高，900 宽度下纸张会比内容高出一大截。
        self._tabs.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._content.addWidget(self._tabs, 1)
        self._content.addStretch(1)

        self.set_compact(is_compact(*DEFAULT_SIZE))
        self._sync_card_metrics()
        self.apply_theme()
        self._ready = True
        self.refresh()

    # ---------- 主题 ----------
    def apply_theme(self):
        # QSS 字号晚于 sizeHint 生效，显式给一行文字高度，避免中文被裁掉字头
        self._subtitle.setMinimumHeight(self._subtitle.fontMetrics().height() + 6)
        self._tabs.setStyleSheet(f'''
        QTabWidget::pane {{ border: none; background: transparent; }}
        QTabBar {{ background: transparent; }}
        QTabBar::tab {{
            background: {rgba(P.paper_text, 0.06)};
            color: {P.paper_text};
            padding: 8px 16px;
            margin: 0px 8px 8px 0px;
            border-radius: 12px;
            font-size: 14px;
        }}
        QTabBar::tab:selected {{
            background: {rgba(P.primary, 0.42)};
            color: {P.paper_text};
            font-weight: 600;
        }}
        QTabBar::tab:hover {{ background: {rgba(P.primary, 0.24)}; }}
        ''')
        self._paper.update()
        if self._ready:
            self.refresh()

    # ---------- 刷新 ----------
    def refresh(self):
        items = self._ach.all_achievements()
        unlocked = [i for i in items if i['unlocked_at']]
        pending = [i for i in unlocked if not i['claimed']]
        self._summary.setText(
            f'已解锁 {len(unlocked)} / {len(items)}　·　'
            f'解锁后可在卡片上手动领取奖励')
        if pending:
            self._pending_badge.setText(f'● 待领取 {len(pending)} 项')
            self._pending_badge.setStyleSheet(
                f'color: {P.danger_on_paper}; font-size: 14px; font-weight: 600;')
        else:
            self._pending_badge.setText('√ 全部已领取')
            self._pending_badge.setStyleSheet(
                f'color: {P.success_on_paper}; font-size: 14px; font-weight: 600;')

        # QTabWidget.clear() 只移除页签、不删除页面 widget；
        # 先逐个 deleteLater，避免每次刷新泄漏整棵控件树
        while self._tabs.count():
            page = self._tabs.widget(0)
            self._tabs.removeTab(0)
            if page is not None:
                page.setParent(None)
                page.deleteLater()

        self._tab_pages = {}
        for cat in CATS:
            cat_items = [i for i in items if i['category'] == cat]
            page = self._build_tab(cat_items)
            self._tab_pages[cat] = page
            done = sum(1 for i in cat_items if i['unlocked_at'])
            self._tabs.addTab(page, f'{CAT_TITLES[cat]}（{done}/{len(cat_items)}）')
            for card in page.findChildren(QFrame):
                card.show()   # 新建控件默认隐藏，布局会把隐藏项算成 0 高度
        self._hide_tab_scrollers()
        _activate_tree(self)
        self._fit_paper()

    def _hide_tab_scrollers(self) -> None:
        """QTabBar 在窗口很窄时会显示左右滚动按钮，窗口变宽后不一定收回，
        会把两个 24x23 的按钮压在第一个页签上；4 个短页签不需要它们，
        这里直接隐藏并把尺寸压到 0，避免它再被显示出来时留下残影。"""
        for button in self._tabs.tabBar().findChildren(QToolButton):
            if button.objectName() in ('ScrollLeftButton', 'ScrollRightButton'):
                button.hide()
                button.setFixedSize(0, 0)

    def _fit_paper(self) -> None:
        """按内容自然高度给纸张定最小高度，并让骨架滚动区立刻重算。

        PaperPage 的滚动区只在视口尺寸变化时重算；紧凑切换/重建内容后若不主动触发，
        纸张会被压到视口高度，卡片会互相重叠。
        - 高度用 heightForWidth 逐项累加：换行标签的 sizeHint 不含换行，直接用会低估
        - 重建出来的子控件若仍处于「显式隐藏」，布局会把它算成 0，
          所以重建时逐个 show()（见 refresh 里的卡片、_build_tab）
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
        # 与布局自身的尺寸提示取大：卡片隐藏时布局会低估，取大只多留一点纸面空白
        needed = max(needed, self._content.sizeHint().height()
                     + margins.top() + margins.bottom())
        if needed > 0 and needed != self._paper_min:
            self._paper_min = needed
            self._paper.setMinimumHeight(needed)
        holder = self._page.scroll.widget()
        if holder is not None:
            layout = holder.layout()
            top = layout.contentsMargins().top() if layout is not None else 0
            holder.resize(holder.width(), max(holder.height(), needed + top))

    def _build_tab(self, cat_items: list) -> QWidget:
        # 卡片网格直接铺在页签内，由页面骨架统一滚动（不做滚动套滚动）
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(self._card_spacing)
        for col in range(CARD_COLS):
            grid.setColumnStretch(col, 1)
        for idx, item in enumerate(cat_items):
            grid.addWidget(self._card(item), idx // CARD_COLS, idx % CARD_COLS)
        rows = (len(cat_items) + CARD_COLS - 1) // CARD_COLS
        # 末行伸缩把多余高度留给卡片行，卡片在上下限区间内长高，而不是留一片空白
        grid.setRowStretch(rows, 1)
        grid.activate()
        return page

    # ---------- 徽章卡片 ----------
    def _card(self, item) -> QWidget:
        frame = QFrame()
        height = self._card_height
        frame.setFixedHeight(height)
        frame.setMinimumWidth(CARD_MIN_WIDTH)
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        unlocked = bool(item['unlocked_at'])
        claimed = bool(item['claimed'])

        # 状态 → 填充/描边/标记。配方（design-recipe.md §2）：大面积卡片一律无描边，
        # 只用「同色系浅填充」表达状态；未解锁保留虚线边（无法用颜色表达的禁用语义，
        # 用同色系淡描边而非 1px 深灰硬边）。
        if not unlocked:
            _card_style(frame, 'achCard', rgba(P.paper_text, 0.045),
                        rgba(P.paper_muted, 0.45), dash=True)
            mark, mark_color = '未解锁', P.paper_muted
        elif claimed:
            _card_style(frame, 'achCard', rgba(P.paper_text, 0.075))
            # 勾号用 U+221A：U+2713/U+2714 在 Microsoft YaHei UI 下是空白方框
            mark, mark_color = '√ 已领取', P.success_on_paper
        else:
            _card_style(frame, 'achCard', rgba(P.primary, 0.26))
            mark, mark_color = '● 待领取', P.danger_on_paper

        v = QVBoxLayout(frame)
        pad = self._card_pad
        v.setContentsMargins(pad, pad - 2, pad, pad - 2)
        v.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        # 图标：素材包 v2 的 4 类 × 3 态 SVG；缺资源回退配置里的 emoji
        icon = QLabel()
        pixmap = achievement_icon(item['code'], unlocked=unlocked, claimed=claimed,
                                  size=self._icon_px)
        if pixmap is not None:
            icon.setPixmap(pixmap)
            icon.setToolTip({'locked': '未解锁', 'unlocked': '已解锁，待领取',
                             'claimed': '已领取'}[
                'claimed' if (claimed and unlocked) else
                ('unlocked' if unlocked else 'locked')])
        else:
            icon.setPixmap(_icon_pixmap(item.get('icon', '🎯'), unlocked))
        icon.setFixedSize(self._icon_px, self._icon_px)
        icon.setAlignment(Qt.AlignCenter)
        top.addWidget(icon)
        top.addStretch(1)
        mark_label = _label(mark, size=13, bold=True, color=mark_color)
        if not unlocked:
            # 挂锁是自绘矢量：🔒 在微软雅黑下渲染成空白方框
            lock = QLabel()
            lock.setPixmap(lock_pixmap(mark_color, 14))
            lock.setFixedSize(14, 14)
            lock.setToolTip('未解锁')
            top.addWidget(lock, 0, Qt.AlignVCenter)
        top.addWidget(mark_label, 0, Qt.AlignVCenter)
        v.addLayout(top)

        v.addWidget(_label(item['name'], size=15, bold=True,
                           align=Qt.AlignCenter, color=P.paper_text))
        inner = max(60, self._card_inner_width)
        desc_lines = _wrapped_lines(item['desc'], 13, inner)
        desc = _label(item['desc'], size=13, wrap=True, align=Qt.AlignCenter,
                      color=P.paper_muted)
        desc.setFixedHeight(desc_lines * _text_line(13))
        v.addWidget(desc)
        reward_lines = min(2, _wrapped_lines(f'奖励：{reward_text(item)}', 13, inner))
        reward = _label(f'奖励：{reward_text(item)}', size=13, wrap=True,
                        align=Qt.AlignCenter, color=P.paper_muted)
        reward.setFixedHeight(max(1, reward_lines) * _text_line(13))
        v.addWidget(reward)

        if unlocked and not claimed:
            v.addStretch(1)
            btn = QPushButton('领取奖励')
            btn.setProperty('buttonRole', 'primary')
            btn.setAccessibleName(f'领取「{item["name"]}」的奖励')
            btn.setMinimumHeight(32)
            btn.setMaximumHeight(40)
            btn.clicked.connect(lambda _=False, c=item['code']: self._do_claim(c))
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addStretch(1)
            row.addWidget(btn)
            row.addStretch(1)
            v.addLayout(row)
        else:
            tip = ('奖励已发放' if claimed else '达成后解锁')
            # 状态行贴卡片底部：与「领取奖励」按钮行同一条基线，整行卡片对齐
            v.addStretch(1)
            v.addWidget(_label(tip, size=13, align=Qt.AlignCenter,
                               color=P.paper_muted))
        frame.setToolTip(f'{item["name"]}　{item["desc"]}　奖励：{reward_text(item)}')
        return frame

    def _do_claim(self, code):
        granted = self._ach.claim(code)
        if granted:
            self.claimed.emit()
            self.refresh()

    # ---------- 版式 ----------
    @property
    def _card_spacing(self) -> int:
        return _interp(CARD_SPACING_MIN, CARD_SPACING_MAX, self._scale)

    @property
    def _card_pad(self) -> int:
        return _interp(12, 18, self._scale)

    @property
    def _card_inner_width(self) -> int:
        """卡片内的可用文字宽度 = （纸张宽 − 纸张内边距×2 − 列距×3）÷ 4 − 卡内左右边距。"""
        margins = self._content.contentsMargins()
        paper = self._paper.width() if self._paper is not None else 720
        avail = max(200, paper - margins.left() - margins.right())
        spacing = self._card_spacing
        col = (avail - spacing * (CARD_COLS - 1)) / CARD_COLS
        return int(col - 2 * self._card_pad)

    @property
    def _card_height(self) -> int:
        """卡片高度 = 按尺度系数定出的区间值，且不低于自身内容需求（不裁字）。

        内容需求用真实字体度量算：图标行 + 名称 + 说明（按卡宽折行）+ 奖励（按卡宽
        折行）+ 状态行/按钮行 + 内边距与行距。窗口越大，区间与列宽一起变大，
        卡内文字行数变少、卡片变高，是一个随窗口变化的区间而不是固定像素。
        """
        low = self._card_min_h
        inner = max(60, self._card_inner_width)
        desc_h = _wrapped_lines('星光照亮夜空，指尖轻轻起舞。', 13, inner) \
            * _text_line(13)
        reward_h = _text_line(13) * 2
        need = (self._icon_px + 4
                + _text_line(15, bold=True)
                + desc_h + reward_h
                + 32
                + 2 * self._card_pad + 3 * 4)
        return max(low, need)

    def _sync_card_metrics(self) -> None:
        """卡片尺寸按尺度系数在上下限区间内取值（字号不变）。"""
        scale = self._scale
        self._card_min_h = _interp(CARD_HEIGHT_MIN, CARD_HEIGHT_MAX, scale)
        self._card_max_h = max(self._card_min_h, _interp(CARD_HEIGHT_MAX, 212, scale))
        self._desc_h = _interp(DESC_HEIGHT, DESC_HEIGHT_MAX, scale)
        self._reward_h = _interp(REWARD_HEIGHT, REWARD_HEIGHT_MAX, scale)
        self._icon_px = _interp(ICON_SIZE, ICON_SIZE_MAX, scale)

    def _is_compact_now(self) -> bool:
        """与主窗口同口径：有顶层窗口时按窗口尺寸判断。"""
        from ..widgets.responsive import stage_layout_for
        return stage_layout_for(self).compact

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        changed = compact != self._compact
        self._compact = compact
        # 骨架统一调整外边距与纸张宽度上限（1100/760，左对齐）
        self._page.set_compact(compact)
        self._content.setSpacing(10 if compact else 12)
        if changed and self._ready:
            self.refresh()

    def set_scale(self, scale: float) -> None:
        """尺度系数变化（窗口尺寸变化）后重排卡片尺寸；字号不变。"""
        scale = float(scale)
        if abs(scale - self._scale) < 0.005:
            return
        self._scale = scale
        self._sync_card_metrics()
        if self._ready:
            self.refresh()

    def resizeEvent(self, event):
        if getattr(self, '_page', None) is not None:
            compact = self._is_compact_now()
            if compact != self._compact:
                self.set_compact(compact)
            self.set_scale(scale_for(max(1, self.width()), max(1, self.height())))
            # 纸张宽度随窗口变化：同步激活布局并重算纸张高度，
            # 避免只跑一轮事件时内容停在旧几何/被压到视口高度
            _activate_tree(self)
            self._fit_paper()
        super().resizeEvent(event)

    def showEvent(self, event):
        if getattr(self, '_page', None) is not None:
            self.set_compact(self._is_compact_now())
            self.set_scale(scale_for(max(1, self.width()), max(1, self.height())))
            _activate_tree(self)
            self._fit_paper()
        super().showEvent(event)


def _icon_pixmap(emoji: str, unlocked: bool, size: int = ICON_SIZE):
    """回退用：把配置里的 emoji 绘制为 QPixmap（未解锁半透明，模拟"灰掉"）。

    只在素材包 SVG 资源缺失时使用；正常路径见 `achievement_icon()`。

    注意：不使用 QGraphicsColorizeEffect——无边框透明窗口上效果残留会
    导致整体渲染偏移（v0.8.6 修复；此处曾漏网，v0.8.9 移除）。
    """
    from PySide6.QtCore import QRectF, QSize, Qt
    from PySide6.QtGui import QFont, QPixmap, QPainter
    size = int(size)
    pm = QPixmap(QSize(size, size))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setOpacity(0.42 if not unlocked else 1.0)
    f = QFont()
    f.setPixelSize(max(12, int(size * 0.85)))
    p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, emoji)
    p.end()
    return pm
