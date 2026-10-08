"""个人中心（夜色手稿）：头像 / 昵称 / 签名 / 等级徽章 / 称号收藏 / 终身统计 / 道具 / 成就进度。

- 奶油纸张承载表单与数据列，卡片按列对齐；长内容在纸张内部滚动
- 卡片视觉按配方（`design-recipe.md` §2）：**同色系浅填充 + 大圆角 + 无 1px 深灰硬边**；
  统计格是纸面「同色系浅填充」的小方块，深色卡保持深色
- 尺寸不再写死：卡片高度/内边距/圆角按共享层尺度系数 `design.scale_factor`
  在上下限区间内取值，列宽用布局 stretch 吸收余量（字号仍守 16/20/14/13/28/32）
- 称号点击佩戴后写回既有设置（active_title），主界面每秒刷新自动同步
- 头像优先使用上传图片，否则展示 avatar_preset 指定的 Sariana 素材
- 页头用交付的转曲艺术标题 `ArtHeading('growth')`（成长三页共用同一 role）
"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..palette import P
from ..widgets.profile_hero import ProfileHero
from ..widgets.scrapbook import ScrapbookCard
from ..widgets import design as _design
from ..widgets.design import (
    BUTTON_HEIGHT, BUTTON_HEIGHT_COMPACT, PAPER_PAD, ArtHeading, PaperPage, is_compact, rgba,
)

#: 口径（DECISIONS.md 第 3 条）：成长/打卡页**纸面内容**内边距紧凑档 16px
#: （标准档仍 32px），外层 24px 页面边距不动。
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


def _interp(low: int, high: int, scale: float) -> int:
    """在上下限区间里按尺度系数取值（0.85 → low，1.00 → high）。"""
    t = max(0.0, min(1.0, (float(scale) - 0.85) / 0.15))
    return int(round(low + (high - low) * t))


# 版式 token（纸张位置/宽度由 PaperPage 统一：1100/760 宽，左右 48/24）
AVATAR_SIZE_MIN, AVATAR_SIZE_MAX = 110, 126
TITLE_COLS = 4
STAT_COLS = 3
INV_COLS = 2
TITLE_BUTTON_HEIGHT, TITLE_BUTTON_HEIGHT_COMPACT = 40, 36
STAT_CELL_MIN_H_MIN, STAT_CELL_MIN_H_MAX = 52, 68
CARD_RADIUS_MIN, CARD_RADIUS_MAX = 14, 20
DEFAULT_SIZE = (900, 640)


def _card_style(widget: QFrame, name: str, bg: str, border: str = '', *,
                radius: int = 16, width: int = 1, dash: bool = False) -> None:
    """纸张上的卡片：同色系浅填充 + 大圆角；无描边时不发 border 声明。

    配方（`design-recipe.md` §2）：大面积卡片一律 `stroke=None`（无描边），只有
    输入类控件带 1px 描边。旧实现给每张卡都加了 1px `paper_text@0.16` 的深灰硬边，
    正是用户说的「黑色边框很碍眼」。
    """
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


def _activate_tree(widget: QWidget) -> None:
    """递归激活布局树（离屏截图/紧凑切换可能只跑一轮事件循环）。"""
    layout = widget.layout()
    if layout is not None:
        layout.activate()
    for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
        _activate_tree(child)


def _clear_layout(layout) -> None:
    """立即脱离父级再销毁，避免重建期间瞬时双重绘制。"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class ProfilePage(QWidget):
    settings_requested = Signal()

    def __init__(self, repo, balance, engine, ach_service, reward_service,
                 avatar_dir=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._engine = engine
        self._ach = ach_service
        self._rewards = reward_service
        self._avatar_dir = avatar_dir
        self._compact = None
        self._paper_min = 0
        self._ready = False
        # 弹性尺寸：尺度系数与由它派生的区间值（构造期先按基准尺寸取一档）
        self._scale = scale_for(*DEFAULT_SIZE)
        self._radius = _interp(CARD_RADIUS_MIN, CARD_RADIUS_MAX, self._scale)
        self._cell_min_h = _interp(STAT_CELL_MIN_H_MIN, STAT_CELL_MIN_H_MAX, self._scale)
        self._avatar_px = _interp(AVATAR_SIZE_MIN, AVATAR_SIZE_MAX, self._scale)

        root = QVBoxLayout(self)
        self._root = root
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 页面骨架：纸张之外的页头（画布上）+ 左侧奶油纸张（上限 1100/760 宽）
        self._page = PaperPage(self, compact=is_compact(*DEFAULT_SIZE))
        self._paper = self._page.paper
        self._content = self._page.body
        self._content.setSpacing(10)
        root.addWidget(self._page)

        # 交付的转曲艺术标题（growth.svg）；副标题仍是普通可读文字
        self._welcome = ArtHeading('growth', '头像、称号、终身统计与道具库存，都收在这里。')
        self._heading = self._welcome.subtitle   # 兼容既有属性名（外部脚本/测试引用）
        self._subtitle = self._welcome.subtitle
        header = QWidget()
        header_v = QVBoxLayout(header)
        header_v.setContentsMargins(0, 0, 0, 0)
        header_v.setSpacing(8)
        header_v.addWidget(self._welcome)
        self._page.set_header(header)

        self._build_sections()
        self._reflow_cells()

        self.set_compact(is_compact(*DEFAULT_SIZE))
        self.apply_theme()
        self._ready = True
        self.refresh()

    # ---------- 静态结构 ----------
    def _build_sections(self) -> None:
        # 纸张首行留给主窗口挂入的成长子导航（打卡/成就/个人资料）

        # 身份主视觉与错位双列；资料、库存与成就各自保持独立容器。
        self._head_card = ProfileHero()
        self._avatar = self._head_card.avatar
        self._nick_label = self._head_card.nickname
        self._sig_label = self._head_card.signature
        self._level_badge = self._head_card.level_badge
        self._level_label = self._head_card.level_label
        self._streak_badge = self._head_card.streak
        self._content.addWidget(self._head_card)
        columns = QWidget()
        row = QHBoxLayout(columns)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(18)
        left, right = QWidget(), QWidget()
        self._identity_column, self._collection_column = QVBoxLayout(left), QVBoxLayout(right)
        self._identity_column.setContentsMargins(0, 0, 0, 0)
        self._collection_column.setContentsMargins(0, 24, 0, 0)
        self._identity_column.setSpacing(12)
        self._collection_column.setSpacing(16)
        row.addWidget(left, 7)
        row.addWidget(right, 4)
        self._content.addWidget(columns)

        # 2. 称号收藏
        self._title_card = ScrapbookCard('rose')
        tv = QVBoxLayout(self._title_card)
        tv.setContentsMargins(18, 12, 18, 12)
        tv.setSpacing(6)
        # 🏅 在微软雅黑下可能渲染成空白方框：改用纯文字标题（语义不变）
        tv.addWidget(_label('称号收藏（点击佩戴）', size=14, bold=True,
                            color=P.paper_text))
        self._active_title_label = _label('', role='paperMuted', wrap=True)
        tv.addWidget(self._active_title_label)
        title_host = QWidget()
        self._titles_box = QGridLayout(title_host)
        self._titles_box.setContentsMargins(0, 0, 0, 0)
        self._titles_box.setSpacing(8)
        for col_i in range(TITLE_COLS):
            self._titles_box.setColumnStretch(col_i, 1)
        tv.addWidget(title_host)

        # 3. 终身统计（数据列：等宽对齐）
        self._stat_card = ScrapbookCard('lavender')
        sv = QVBoxLayout(self._stat_card)
        sv.setContentsMargins(18, 12, 18, 12)
        sv.setSpacing(8)
        sv.addWidget(_label('终身统计', size=14, bold=True, color=P.paper_text))
        stat_host = QWidget()
        self._stat_host = stat_host
        self._stat_grid = QGridLayout(stat_host)
        self._stat_grid.setContentsMargins(0, 0, 0, 0)
        self._stat_spacing = 10
        self._stat_grid.setSpacing(self._stat_spacing)
        self._stat_defs = [
            ('累计输入', 'total_typed'), ('累计有效', 'total_valid'),
            ('累计 tw', 'total_tw'), ('累计活跃（分钟）', 'total_minutes'),
            ('打卡总天数', 'checkin_days'),
        ]
        sv.addWidget(stat_host)
        self._identity_column.addWidget(self._stat_card)
        self._identity_column.addWidget(self._title_card)
        self._identity_column.addStretch()

        # 4. 道具库存
        self._inv_card = ScrapbookCard('rose')
        iv = QVBoxLayout(self._inv_card)
        iv.setContentsMargins(18, 12, 18, 12)
        iv.setSpacing(8)
        iv.addWidget(_label('道具库存', size=14, bold=True, color=P.paper_text))
        inv_host = QWidget()
        inv_grid = QGridLayout(inv_host)
        inv_grid.setContentsMargins(0, 0, 0, 0)
        inv_grid.setSpacing(self._stat_spacing)
        self._inv_defs = [
            ('补签卡', 'makeup_cards'), ('经验加成卡', 'boost_cards'),
            ('AI 训练券', 'ai_passes'), ('已获称号', 'titles_count'),
        ]
        inv_grid.addWidget(QWidget(), 0, 0)   # 占位：单元格由 _reflow_cells 统一重建
        for col_i in range(INV_COLS):
            inv_grid.setColumnStretch(col_i, 1)
        iv.addWidget(inv_host)
        self._inv_host = inv_host
        self._inv_grid = inv_grid
        self._collection_column.addWidget(self._inv_card)

        # 5. 成就进度
        self._ach_card = ScrapbookCard('lavender')
        av = QVBoxLayout(self._ach_card)
        av.setContentsMargins(18, 12, 18, 12)
        av.setSpacing(6)
        self._intro = _label('', size=14, bold=True, color=P.paper_text)
        av.addWidget(self._intro)
        self._ach_bar = QProgressBar()
        self._ach_bar.setFixedHeight(14)
        self._ach_bar.setTextVisible(False)
        av.addWidget(self._ach_bar)
        self._ach_hint = _label('', role='paperMuted', wrap=True)
        av.addWidget(self._ach_hint)
        self._collection_column.addWidget(self._ach_card)
        self._collection_column.addStretch()

        # 6. 设置入口（纸张最后一项，页面滚动到底即可触达）
        # ⚙️ 在微软雅黑下可能渲染成空白方框：改用纯文字标签（语义不变）
        self._settings_btn = QPushButton('编辑我的资料 ↗')
        self._settings_btn.setProperty('buttonRole', 'secondary')
        self._settings_btn.clicked.connect(self.settings_requested)
        self._settings_row = QWidget()
        settings_row = QHBoxLayout(self._settings_row)
        settings_row.setContentsMargins(0, 0, 0, 0)
        settings_row.addWidget(self._settings_btn)
        settings_row.addStretch(1)
        self._head_card.actions.insertWidget(2, self._settings_row)

    # ---------- 数据单元格（紧凑档横排，避免统计卡被视口底边切开） ----------

    def _reflow_cells(self) -> None:
        """按当前尺寸档重建终身统计 / 道具库存单元格。

        - 常规档：数值在上、名称在下（设计稿的数据列）
        - 紧凑档：名称在左、数值在右。900×640 首屏只有约 520px 可视高度，
          竖排单元格会让「终身统计」卡整块超出视口、和下面的卡片挤在一起；
          横排后每行矮近一半，首屏能完整放下头部卡、称号卡与统计卡。
        """
        for grid, defs in ((self._stat_grid, self._stat_defs),
                           (self._inv_grid, self._inv_defs)):
            while grid.count():
                item = grid.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.setParent(None)
                    widget.deleteLater()
        self._stat_values = {}
        self._stat_cells = []
        for grid, defs, cols in ((self._stat_grid, self._stat_defs, STAT_COLS),
                                 (self._inv_grid, self._inv_defs, INV_COLS)):
            for idx, (name, key) in enumerate(defs):
                cell = QFrame()
                cell.setMinimumHeight(self._cell_min_h)
                cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                if self._compact:
                    row = QHBoxLayout(cell)
                    row.setContentsMargins(12, 6, 12, 6)
                    row.setSpacing(8)
                    value = _label('—', size=18, bold=True, color=P.paper_text)
                    row.addWidget(_label(name, role='paperMuted'), 1)
                    row.addWidget(value, 0, Qt.AlignRight | Qt.AlignVCenter)
                else:
                    row = QVBoxLayout(cell)
                    row.setContentsMargins(12, 8, 12, 8)
                    row.setSpacing(2)
                    value = _label('—', size=18, bold=True, color=P.paper_text)
                    row.addWidget(value)
                    row.addWidget(_label(name, role='paperMuted'))
                self._stat_values[key] = value
                self._stat_cells.append(cell)
                grid.addWidget(cell, idx // cols, idx % cols)
                cell.show()   # 新建控件默认隐藏，布局会把隐藏项算成 0 高度
        self._style_cards()

    # ---------- 主题 ----------
    def apply_theme(self):
        # QSS 字号晚于 sizeHint 生效，显式给一行文字高度，避免中文被裁掉字头
        self._subtitle.setMinimumHeight(self._subtitle.fontMetrics().height() + 6)
        self._avatar.update()
        self._paper.update()
        if self._ready:
            self.refresh()

    # ---------- 刷新 ----------
    def refresh(self):
        nickname = self._repo.get_setting('nickname', '打字新星')
        signature = self._repo.get_setting('signature', '键盘上的舞者 ✨')
        self._avatar.set_preset(self._repo.get_setting('avatar_preset', 'default'))
        if self._avatar_dir is not None:
            img = self._avatar_dir / 'avatar.png'
            self._avatar.set_image(
                img if img.exists() and self._repo.get_setting('avatar_image', '') == '1'
                else None)
        self._nick_label.setText(nickname)
        self._sig_label.setText(signature)

        from ...services.exp_service import band_title, level_and_progress
        exp = self._repo.get_exp()
        level, progress, _ = level_and_progress(exp, self._balance)
        band = band_title(level, self._balance)
        self._level_badge.setText(f'Lv.{level}')
        self._level_badge.setStyleSheet(
            f'color: {P.paper_text}; font-size: 18px; font-weight: 600;'
            f' background: {rgba(P.primary, 0.38)}; border: 1px solid {P.primary};'
            f' border-radius: 10px; padding: 2px 12px;')
        self._level_label.setText(
            f'称号段位：{band}　·　经验 {exp:,}　·　升级进度 {round(progress * 100)}%')

        today = date.fromisoformat(self._engine.current_day())
        streak = self._repo.get_streak(today.isoformat()) or self._repo.get_streak(
            (today - timedelta(days=1)).isoformat())
        # 🔥 在微软雅黑下可能渲染成空白方框：改用文字表达连签
        self._streak_badge.setText(f'连签 {streak} 天')
        self._streak_badge.setStyleSheet(
            f'color: {P.paper_text}; font-size: 14px; font-weight: 600;'
            f' background: {rgba(P.accent_rose, 0.28)}; border-radius: 10px;'
            f' padding: 6px 12px;')

        life = self._repo.get_lifetime() or {}
        self._stat_values['total_typed'].setText(f'{life.get("total_typed", 0):,}')
        self._stat_values['total_valid'].setText(
            f'{max(0, life.get("total_typed", 0) - life.get("total_deleted", 0)):,}')
        self._stat_values['total_tw'].setText(f'{life.get("total_tw", 0):,}')
        self._stat_values['total_minutes'].setText(
            f'{life.get("total_active_minutes", 0):,}')
        checkin_days = self._repo.get_checkins('0000-01-01', '9999-12-31')
        self._stat_values['checkin_days'].setText(str(len(checkin_days)))

        titles = self._rewards.titles()
        self._stat_values['makeup_cards'].setText(str(self._rewards.count('makeup_card')))
        self._stat_values['boost_cards'].setText(str(self._rewards.count('exp_boost')))
        self._stat_values['ai_passes'].setText(str(self._rewards.count('ai_pass')))
        self._stat_values['titles_count'].setText(str(len(titles)))

        self._build_titles(level, band, titles)
        self._build_achievement_progress()
        self._style_cards()

        self._content.activate()
        _activate_tree(self)
        self._fit_paper()

    def _fit_paper(self) -> None:
        """按内容自然高度给纸张定最小高度，并让骨架滚动区立刻重算。

        PaperPage 的滚动区只在视口尺寸变化时重算；紧凑切换/重建内容后若不主动触发，
        纸张会被压到视口高度，卡片会互相重叠。
        - 高度用 heightForWidth 逐项累加：换行标签的 sizeHint 不含换行，直接用会低估
        - 重建出来的子控件若仍处于「显式隐藏」，布局会把它算成 0，
          所以重建时逐个 show()（见 _build_titles）
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
        # 与布局自身的尺寸提示取大：换行标签的提示偏保守，取大只多留一点纸面空白，
        # 不会把内容压到视口高度
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

    def _build_titles(self, level: int, band: str, titles: list) -> None:
        active = self._repo.get_setting('active_title', '')
        _clear_layout(self._titles_box)
        all_titles = [f'Lv.{level} {band}'] + list(titles)
        for idx, title in enumerate(all_titles):
            equipped = bool(active == title or (not active and title.startswith(f'Lv.{level}')))
            btn = QPushButton(('√ ' if equipped else '') + title)
            btn.setProperty('buttonRole', 'primary' if equipped else 'secondary')
            btn.setAccessibleName(f'佩戴称号 {title}')
            height = TITLE_BUTTON_HEIGHT_COMPACT if self._compact else TITLE_BUTTON_HEIGHT
            # 内联 min-height：主题 QSS 的 `QPushButton { min-height: 26px }` 会在
            # 主题应用后盖掉控件级 setFixedHeight，这里用控件级样式钉住
            btn.setStyleSheet(f'min-height: {height}px;')
            btn.setFixedHeight(height)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.clicked.connect(lambda _=False, t=title: self._equip_title(t))
            self._titles_box.addWidget(btn, idx // TITLE_COLS, idx % TITLE_COLS)
            btn.show()   # 新建控件默认隐藏，布局会把隐藏项算成 0 高度
        self._active_title_label.setText(
            f'当前佩戴：{active if active else f"Lv.{level} {band}"}')

    def _build_achievement_progress(self) -> None:
        items = self._ach.all_achievements()
        unlocked = sum(1 for a in items if a['unlocked_at'])
        total = len(items)
        pending = sum(1 for a in items if a['unlocked_at'] and not a['claimed'])
        # 🏆 在微软雅黑下可能渲染成空白方框：改用纯文字标签
        self._intro.setText(f'成就进度 {unlocked} / {total}')
        self._ach_bar.setRange(0, max(1, total))
        self._ach_bar.setValue(unlocked)
        self._ach_bar.setStyleSheet(
            f'QProgressBar {{ background: {rgba(P.paper_text, 0.12)}; border: none;'
            f' border-radius: 7px; }}'
            f'QProgressBar::chunk {{ background: {P.primary}; border-radius: 7px; }}')
        hint = '每天打打字，成为键盘上的明星。'
        if pending:
            hint = f'有 {pending} 项成就奖励待领取，去成就墙领取 →'
        self._ach_hint.setText(hint)

    def _style_cards(self) -> None:
        """卡片视觉：同色系浅填充 + 大圆角 + **无描边**（配方 `design-recipe.md` §2）。"""
        radius = self._radius
        for card in (self._head_card, self._title_card, self._stat_card, self._inv_card, self._ach_card):
            card.update()
        for cell in getattr(self, '_stat_cells', []):
            # 个人资料统计格：纸面加深一档的浅填充（配方第 97 行 `#DED4CB` 的同一手法）
            _card_style(cell, 'profileCell',
                        rgba(P.primary, 0.20) if not P.dark else rgba(P.paper_text, 0.06),
                        radius=max(10, radius - 4))

    def _equip_title(self, title: str) -> None:
        self._repo.set_setting('active_title', title)
        self.refresh()

    # ---------- 版式 ----------
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
        # 口径（DECISIONS.md 第 3 条）：成长页紧凑档纸面内容内边距 16px，标准档 32px；
        # 外层 24px 页面边距不动。
        pad = GROWTH_PAD_COMPACT if compact else PAPER_PAD
        self._content.setContentsMargins(pad, pad, pad, pad)
        self._content.setSpacing(10)
        # 紧凑切换改的是尺寸档，尺度系数与卡片区间值一并重算（`_sync_scale` 幂等）
        self._scale = scale_for(max(1, self.width()), max(1, self.height()))
        self._radius = _interp(CARD_RADIUS_MIN, CARD_RADIUS_MAX, self._scale)
        self._cell_min_h = _interp(STAT_CELL_MIN_H_MIN, STAT_CELL_MIN_H_MAX, self._scale)
        avatar_px = _interp(AVATAR_SIZE_MIN, AVATAR_SIZE_MAX, self._scale)
        if getattr(self, '_avatar', None) is not None:
            self._avatar.set_size(avatar_px)
            self._sync_scale()
        if getattr(self, '_stat_grid', None) is not None:
            self._reflow_cells()
        if changed and self._ready:
            self.refresh()

    def _sync_scale(self) -> None:
        """按窗口尺寸更新尺度系数，把写死值换成区间取值（字号不变）。"""
        self._scale = scale_for(max(1, self.width()), max(1, self.height()))
        self._radius = _interp(CARD_RADIUS_MIN, CARD_RADIUS_MAX, self._scale)
        self._cell_min_h = _interp(STAT_CELL_MIN_H_MIN, STAT_CELL_MIN_H_MAX, self._scale)
        self._avatar_px = _interp(AVATAR_SIZE_MIN, AVATAR_SIZE_MAX, self._scale)
        self._avatar.set_size(self._avatar_px)
        height = BUTTON_HEIGHT_COMPACT if self._compact else BUTTON_HEIGHT
        self._settings_btn.setStyleSheet(f'min-height: {height}px;')
        self._settings_btn.setFixedHeight(height)
        for btn in self._title_card.findChildren(QPushButton):
            btn_h = TITLE_BUTTON_HEIGHT_COMPACT if self._compact else TITLE_BUTTON_HEIGHT
            btn.setStyleSheet(f'min-height: {btn_h}px;')
            btn.setFixedHeight(btn_h)

    def resizeEvent(self, event):
        if getattr(self, '_page', None) is not None:
            compact = self._is_compact_now()
            if compact != self._compact:
                self.set_compact(compact)
            self._sync_scale()
            if self._ready:
                self._reflow_cells()
            # 纸张宽度随窗口变化：同步激活布局并重算纸张高度，
            # 避免只跑一轮事件时内容停在旧几何/被压到视口高度
            _activate_tree(self)
            self._fit_paper()
        super().resizeEvent(event)

    def showEvent(self, event):
        if getattr(self, '_page', None) is not None:
            self.set_compact(self._is_compact_now())
            self._sync_scale()
            _activate_tree(self)
            self._fit_paper()
        super().showEvent(event)
