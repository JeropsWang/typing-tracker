"""主窗口：今日概览 + 1 秒刷新 + 关闭即驻留托盘 + 星空背景/动效/弹窗。"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QMainWindow, QPushButton, QSystemTrayIcon, QTabWidget,
    QVBoxLayout, QWidget,
)

from .. import __version__
from ..services.exp_service import band_title, level_and_progress
from .assets.icons import icon as svg_icon
from .dashboard import Dashboard
from .palette import P
from .pages.achievements import AchievementsPage
from .pages.challenge import ChallengePage
from .pages.checkin import CheckinPage
from .pages.profile import ProfilePage
from .pages.reports import ReportsPage
from .english.page import EnglishPage
from .settings_dialog import SettingsDialog
from .widgets.checkin_popup import CheckinPopup
from .widgets.confetti import ConfettiOverlay
from .widgets.design import (
    TITLEBAR_HEIGHT, asset_path, is_compact, scale_px, widget_scale,
)
from .widgets.navigation import BottomNav, NavigationDock
from .widgets.responsive import FIXED_WINDOW_SIZE, WINDOW_CHROME_HEIGHT, stage_layout_for
from .widgets.window_policy import FixedWindowPolicy
from .widgets.starfield import BackdropImage, StarField
from .widgets.title_bar import TitleBar
from .widgets.toast_popup import ToastPopup

# 底部导航项 → 交付图标名（assets/nav/*.svg）
NAV_ICONS = {'今日': 'today', '训练': 'training', '英语': 'english', '统计': 'stats',
             '成长': 'growth', '设置': 'settings'}


def _load_bands(balance, repo):
    raw = repo.get_setting('level_bands')
    if raw:
        try:
            bands = json.loads(raw)
            if isinstance(bands, list) and bands:
                return bands
        except Exception:
            pass
    return balance['level']['bands']


def current_streak(repo, day_iso) -> int:
    """今日已打卡取今日连签，否则取昨日连签。"""
    s = repo.get_streak(day_iso)
    if s:
        return s
    yesterday = (date.fromisoformat(day_iso) - timedelta(days=1)).isoformat()
    return repo.get_streak(yesterday)


class MainWindow(QMainWindow):
    def __init__(self, engine, repo, balance, tray=None,
                 checkin=None, rewards=None, achievements=None,
                 theme_manager=None, challenge=None, ai_service=None,
                 data_dir=None):
        super().__init__()
        self.setProperty('stageChromeHeight', WINDOW_CHROME_HEIGHT)
        self._engine = engine
        self._repo = repo
        self._balance = balance
        self._tray = tray
        self._theme_mgr = theme_manager
        self._data_dir = data_dir
        self._effects = {}
        self._accent = '#60a5fa'
        self._dark = True
        self._popups = []
        self._last_level = None

        self.setWindowTitle(f'打字管家 v{__version__}')
        # 无边框窗口 + 自定义标题栏 + 圆角壳层 + 投影（窗户质感）
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint
                            | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint)
        self._window_policy = FixedWindowPolicy(self, FIXED_WINDOW_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._shell_bg = ('qlineargradient(x1:0, y1:0, x2:0.6, y2:1,'
                          ' stop:0 #1A1240, stop:0.45 #241B52, stop:1 #160F33)')

        self._dashboard = Dashboard()
        self._reports = ReportsPage(repo, engine, balance)
        self._hook = None
        self._tabs = QTabWidget()
        self._tabs.setObjectName('mainTabs')
        self._tabs.addTab(self._dashboard, '今日概览')
        self._tabs.setTabIcon(0, svg_icon('home', '#94A3B8'))
        self._tabs.addTab(self._reports, '报表')
        self._tabs.setTabIcon(1, svg_icon('chart', '#94A3B8'))
        if checkin is not None and rewards is not None:
            self._checkin_page = CheckinPage(repo, balance, checkin, rewards, engine)
            self._tabs.addTab(self._checkin_page, '打卡')
            self._tabs.setTabIcon(2, svg_icon('calendar', '#94A3B8'))
        if achievements is not None:
            self._ach_page = AchievementsPage(repo, balance, achievements)
            self._ach_page.claimed.connect(self._on_reward_granted)
            self._tabs.addTab(self._ach_page, '成就')
            self._tabs.setTabIcon(3, svg_icon('trophy', '#94A3B8'))
        if achievements is not None and rewards is not None:
            self._profile_page = ProfilePage(
                repo, balance, engine, achievements, rewards,
                avatar_dir=Path(data_dir) / 'avatars' if data_dir else None)
            self._profile_page.settings_requested.connect(self.open_settings)
            self._tabs.addTab(self._profile_page, '个人中心')
            self._tabs.setTabIcon(4, svg_icon('user', '#94A3B8'))
        if challenge is not None:
            self._challenge_page = ChallengePage(repo, balance, challenge,
                                                 ai_service=ai_service)
            self._challenge_page.confetti_requested.connect(self.play_confetti)
            self._challenge_page.settings_requested.connect(lambda: self.open_settings(section='ai'))
            self._tabs.addTab(self._challenge_page, '竞速')
            self._tabs.setTabIcon(5, svg_icon('zap', '#94A3B8'))
        self._english_page = EnglishPage(repo, balance, ai_service)
        self._english_page.settings_requested.connect(lambda: self.open_settings(section='ai'))
        self._english_page.running_changed.connect(self._sync_motion)
        self._tabs.addTab(self._english_page, '英语')
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().hide()
        self._dashboard.training_requested.connect(self.open_training)
        self._dashboard._practice_btn.setEnabled(hasattr(self, '_challenge_page'))
        if hasattr(self, '_challenge_page'):
            self._challenge_page.running_changed.connect(self._sync_motion)

        # 导航映射保留页面对象及原服务边界，旧页面索引供现有脚本兼容。
        self._navigation = {
            '今日': self._dashboard, '训练': getattr(self, '_challenge_page', None),
            '英语': self._english_page, '统计': self._reports,
            '成长': next((getattr(self, name) for name in
                          ('_checkin_page', '_ach_page', '_profile_page') if hasattr(self, name)), None),
        }
        self._nav = BottomNav(compact=is_compact(self.width(), self.height()))
        for title, page in self._navigation.items():
            self._nav.add_item(title, NAV_ICONS[title], enabled=page is not None)
        self._nav.add_item('设置', NAV_ICONS['设置'])
        self._nav.selected.connect(self._on_nav_selected)
        self._nav_buttons = self._nav.buttons
        self._nav.set_current('今日')

        self._growth_bar = QWidget()
        growth = QHBoxLayout(self._growth_bar)
        growth.setContentsMargins(0, 0, 0, 8)
        growth.setSpacing(16)
        self._growth_group = QButtonGroup(self)
        self._growth_buttons = {}
        for title, name in [('打卡', '_checkin_page'), ('成就', '_ach_page'), ('个人资料', '_profile_page')]:
            page = getattr(self, name, None)
            if page is None:
                continue
            button = QPushButton(title)
            button.setCheckable(True)
            button.setProperty('growthTab', True)   # 纸面上的分段按钮（设计稿的成长子导航）
            button.setMinimumHeight(34)
            button.clicked.connect(lambda checked=False, target=page: self._tabs.setCurrentWidget(target))
            self._growth_group.addButton(button)
            self._growth_buttons[title] = button
            growth.addWidget(button)
        growth.addStretch()
        self._growth_bar.setFixedHeight(46)     # 子导航高度固定，避免被不同页面布局拉伸
        self._growth_bar.hide()
        pages = QWidget()
        self._pages = pages
        page_layout = QVBoxLayout(pages)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(self._growth_bar)
        page_layout.addWidget(self._tabs, 1)

        # 圆角壳层（窗户质感；不使用 QGraphicsEffect——无边框透明窗口上
        # 效果残留会导致整体渲染偏移，见 v0.8.6 修复）
        self._shell = QFrame(self)
        self._shell.setObjectName('shellFrame')
        # 背景层：静态插画在最底层，星空粒子在其上（主题未交付插画时自动隐藏）
        self._backdrop = BackdropImage(self._shell)
        self._backdrop.lower()
        self._starfield = StarField(self._shell)
        self._starfield.lower()
        self._backdrop.lower()
        v = QVBoxLayout(self._shell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._titlebar = TitleBar(self, '打字管家  /  TypingTracker')
        v.addWidget(self._titlebar)
        v.addWidget(pages, 1)
        # 导航条按规范内缩（非紧凑 32/16，紧凑 16/12）
        nav_wrap = NavigationDock(self._nav)
        self._nav_dock = nav_wrap
        self._nav_wrap_layout = nav_wrap.layout()
        v.addWidget(nav_wrap)
        self.setCentralWidget(self._shell)

        # 彩带庆祝覆盖层
        self._confetti = ConfettiOverlay(self)
        self._confetti.setGeometry(self.rect())

        self._update_shell_style()
        # 构造期就确定紧凑布局（offscreen 冒烟可能不再触发 resizeEvent）
        stage = self.rect().adjusted(0, TITLEBAR_HEIGHT, 0, 0)
        self._backdrop.setGeometry(stage)
        self._starfield.setGeometry(stage)
        self._apply_compact()
        self._apply_nav_margins()

        # 悬浮设置按钮（右下角，永远可见）
        self._floating_settings = QPushButton(self)
        self._floating_settings.setIcon(svg_icon('settings', '#ffffff', 17))
        self._floating_settings.setFixedSize(42, 42)
        self._floating_settings.setToolTip('设置（AI 配置 / 主题 / 头像…）')
        self._floating_settings.setAccessibleName('设置')
        self._floating_settings.setStyleSheet(
            'QPushButton { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,'
            ' stop:0 #6366F1, stop:1 #EC4899); border: none; border-radius: 21px; }'
            'QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,'
            ' stop:0 #4F46E5, stop:1 #DB2777); }')
        self._floating_settings.clicked.connect(self.open_settings)
        self._floating_settings.hide()  # 设置移到固定导航，避免遮挡练习内容。

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()
        self._on_tab_changed(self._tabs.currentIndex())

    def _on_reward_granted(self):
        self.refresh()

    # ---------- 主题 effects ----------
    def apply_effects(self, effects: dict) -> None:
        """主题切换时应用动态效果配置（星空/渐变/光效/配色）。"""
        self._effects = effects or {}
        self._starfield.configure(self._effects)
        # 动画元数据由主题显式声明，其余插画保持静态。
        backdrop = self._effects.get('backdrop')
        character_motion = self._effects.get('character_motion')
        self._backdrop.set_source(asset_path(backdrop) if backdrop else None,
                                 asset_path(character_motion) if character_motion else None)
        self._backdrop.set_corner_radius(self._shell_radius())
        colors = self._effects.get('levelbar', {}).get('colors')
        if colors:
            self._dashboard.set_level_colors(colors)
        accent = self._effects.get('accent')
        if accent:
            self._accent = accent
        self._dark = bool(self._effects.get('dark', True))
        self._titlebar.apply_theme()
        # Tab 图标颜色跟随主题（线性图标）
        for i, name in enumerate(['home', 'chart', 'calendar', 'trophy', 'user', 'zap']):
            if i < self._tabs.count():
                self._tabs.setTabIcon(i, svg_icon(name, P.muted if not self._dark else '#94A3B8'))
        # 星空模式下页面容器透明（主题 QSS 已处理 pane，这里处理窗口属性）
        self._tabs.setAttribute(
            Qt.WA_TranslucentBackground,
            self._effects.get('background') == 'stars')
        # 各页面刷新文字/卡片颜色（可读性）
        self._dashboard.apply_theme()
        self._reports.apply_theme()
        if hasattr(self, '_checkin_page'):
            self._checkin_page.apply_theme()
        if hasattr(self, '_ach_page'):
            self._ach_page.apply_theme()
        if hasattr(self, '_profile_page'):
            self._profile_page.apply_theme()
        if hasattr(self, '_challenge_page'):
            self._challenge_page.apply_theme()
        self._english_page.apply_theme()
        self._sync_motion()

    def apply_shell_style(self, shell_bg: str) -> None:
        """主题切换时注入壳层背景渐变（manifest shell_bg）。"""
        if shell_bg:
            self._shell_bg = shell_bg
        self._update_shell_style()

    def _shell_radius(self) -> int:
        """固定窗口中的壳层、标题栏与背景共用圆角。"""
        return scale_px(16, widget_scale(self), minimum=12)

    def _update_shell_style(self) -> None:
        """固定窗口的圆角壳层（纯 QSS，无 QGraphicsEffect）。

        配方 `render_design.py` 第 108 行：窗口壳层本身**没有描边**。
        这里保持 `border: none`——旧实现曾给壳层/标题栏加深色 1px 边，
        就是用户说的“黑色边框碍眼”。
        """
        radius = self._shell_radius()
        self._shell.setStyleSheet(
            f'QFrame#shellFrame {{ background: {self._shell_bg};'
            f' border-radius: {radius}px; border: none; }}')
        self._titlebar.set_corner_radius(radius)
        self._backdrop.set_corner_radius(radius)
        self._starfield.set_corner_radius(radius)

    def _on_nav_selected(self, title: str) -> None:
        """底部导航：设置打开既有对话框，其余切换到既有页面对象。"""
        if title == '设置':
            self.open_settings()
            self._sync_nav_selection()
            return
        page = self._navigation.get(title)
        if page is not None:
            self._tabs.setCurrentWidget(page)

    def _place_growth_bar(self, page) -> None:
        """成长子导航在设计稿里位于纸张顶部：把它挂到当前成长页纸张 body 的首行。

        未迁移到 PaperPage 的页面回退到「页面区顶部」的旧位置，行为不变。
        """
        body = getattr(getattr(page, '_page', None), 'body', None)
        if body is None:
            return
        if self._growth_bar.parentWidget() is not body.parentWidget():
            body.insertWidget(0, self._growth_bar)

    def _sync_nav_selection(self) -> None:
        page = self._tabs.currentWidget()
        if page in [getattr(self, name, None) for name in ('_checkin_page', '_ach_page', '_profile_page')]:
            current = '成长'
        else:
            current = next((title for title, target in self._navigation.items() if target is page), '今日')
        self._nav.set_current(current)

    def _apply_nav_margins(self) -> None:
        """将停靠槽几何交给导航组件，窗口不重复计算断点或宽度。"""
        self._nav_dock.set_stage_layout(stage_layout_for(self))

    def _apply_compact(self) -> None:
        """页面与导航使用同一稳定窗口预算；控件几何连续变化，正文保持可读。"""
        stage = stage_layout_for(self)
        compact = stage.compact
        self._apply_nav_margins()
        self._growth_bar.setFixedHeight(stage.blend(38, 46))
        if compact == getattr(self, '_compact', None):
            return
        self._compact = compact
        for page in (self._dashboard, self._reports, getattr(self, '_challenge_page', None),
                     getattr(self, '_checkin_page', None), getattr(self, '_ach_page', None),
                     getattr(self, '_profile_page', None)):
            setter = getattr(page, 'set_compact', None)
            if callable(setter):
                setter(compact)

    def play_confetti(self, tier: int = 1) -> None:
        if not self._motion_active():
            return
        self._confetti.setGeometry(self.rect())
        self._confetti.start(tier)

    def resizeEvent(self, event):
        # 背景层只覆盖标题栏以下的内容区（标题栏自带底色）
        stage = self.rect().adjusted(0, TITLEBAR_HEIGHT, 0, 0)
        self._backdrop.setGeometry(stage)
        self._backdrop.lower()
        self._starfield.setGeometry(stage)
        self._confetti.setGeometry(self.rect())
        self._floating_settings.move(self.width() - 58, self.height() - 66)
        self._apply_compact()
        self._apply_nav_margins()
        super().resizeEvent(event)

    # ---------- 弹窗 ----------
    def show_checkin_popup(self, result: dict) -> None:
        """每日签到弹窗（居中显示，动态动画）。"""
        if not self.isVisible():
            return
        popup = CheckinPopup(self, result, self._balance,
                             accent=self._accent, dark=self._dark)
        popup.set_motion_enabled(self._motion_active())
        popup.adjustSize()
        popup.move((self.width() - popup.width()) // 2,
                   (self.height() - popup.height()) // 2 - 30)
        popup.show()
        popup.raise_()
        popup.start_animation()

    def show_toast(self, title: str, msg: str, kind: str = 'star') -> None:
        """成就/升级/鼓励小弹窗（右上角堆叠，位置滑入动画，自动消失）。"""
        if not self.isVisible():
            return
        popup = ToastPopup(self, title, msg, kind=kind,
                           accent=self._accent, dark=self._dark)
        popup.set_motion_enabled(self._motion_active())
        popup.adjustSize()
        y = 46 + len(self._popups) * (popup.height() + 10)
        popup.show()
        popup.raise_()
        popup.start_animation(QPoint(self.width() - popup.width() - 18, y))
        self._popups.append(popup)
        QTimer.singleShot(3800, lambda: self._popups_discard(popup))

    def _popups_discard(self, popup) -> None:
        if popup in self._popups:
            self._popups.remove(popup)

    def notify(self, title: str, msg: str, kind: str = 'star') -> None:
        """兼容旧调用：统一走小弹窗。"""
        self.show_toast(title, msg, kind)

    # ---------- Tab 动效 ----------
    def _on_tab_changed(self, index: int):
        page = self._tabs.widget(index)
        if page is self._reports:
            self._reports.refresh()
        elif page is getattr(self, '_checkin_page', None):
            self._checkin_page.refresh()
        elif page is getattr(self, '_ach_page', None):
            self._ach_page.refresh()
        elif page is getattr(self, '_profile_page', None):
            self._profile_page.refresh()
        elif page is getattr(self, '_challenge_page', None):
            self._challenge_page._refresh_recent()
        elif page is self._english_page:
            self._english_page.refresh()
        if hasattr(self, '_nav_buttons'):
            in_growth = page in [getattr(self, name, None) for name in ('_checkin_page', '_ach_page', '_profile_page')]
            if in_growth:
                self._place_growth_bar(page)
            self._growth_bar.setVisible(in_growth)
            self._sync_nav_selection()
            for title, name in [('打卡', '_checkin_page'), ('成就', '_ach_page'), ('个人资料', '_profile_page')]:
                if title in self._growth_buttons:
                    self._growth_buttons[title].setChecked(page is getattr(self, name, None))
            self._sync_motion()
        # 注意：不再使用 QGraphicsOpacityEffect 页面淡入——
        # 无边框透明窗口上效果残留会导致整体渲染偏移（v0.8.6 修复）

    # ---------- 刷新 ----------
    def refresh(self):
        if not self.isVisible():
            return  # 驻留托盘时停止每秒刷新（UI 与 SQL 都省）
        snap = self._engine.snapshot()
        exp = self._repo.get_exp()
        level, progress, _ = level_and_progress(exp, self._balance)
        title = band_title(level, self._balance, _load_bands(self._balance, self._repo))
        active = self._repo.get_setting('active_title', '')
        if active:
            title = active
        unit = self._repo.get_setting('unit_name', self._balance['unit']['name'])
        streak = current_streak(self._repo, self._engine.current_day())
        self._dashboard.refresh(snap, level, progress, title, streak, unit,
                                exp=exp)
        # 导航左侧用户摘要（紧凑窗口自动隐藏）
        nickname = self._repo.get_setting('nickname', '') or '打字新星'
        self._nav.set_summary(nickname, f'Lv.{level} · {title}')

        # 升级检测 → 小弹窗
        if self._last_level is not None and level > self._last_level:
            self.show_toast('🎉 升级！',
                            f'Lv.{self._last_level} → Lv.{level}　称号「{title}」',
                            kind='level')
            ai_unlock = self._balance.get('ai', {}).get('unlock_level', 45)
            if self._last_level < ai_unlock <= level and hasattr(self, '_challenge_page'):
                self.show_toast('🎉 解锁 AI 定制训练！',
                                '前往「竞速」页，生成你的专属训练文本 ✨',
                                kind='level')
        self._last_level = level
        if hasattr(self, '_challenge_page'):
            self._challenge_page.update_ai_access()

        if self._hook is not None:
            self._dashboard.set_hook_info(
                self._hook.event_count, self._hook.ime_readable,
                self._hook.errors, self._hook.tsf_ok)
        if self._tray is not None:
            self._tray.update_summary(self._summary_text(snap, unit))

    def set_hook_status(self, ok: bool):
        self._dashboard.set_hook_status(ok)

    def set_hook(self, hook):
        """注入键盘钩子引用，实时显示事件计数（诊断可见性）。"""
        self._hook = hook
        self.refresh()

    def load_excluded_apps(self) -> set:
        """读取排除程序列表（主线程调用），供钩子快照。"""
        text = self._repo.get_setting('excluded_apps') or ''
        return {line.strip().lower() for line in text.splitlines() if line.strip()}

    def _summary_text(self, snap, unit) -> str:
        avg = snap['avg_tw']
        avg_s = f'{avg:.1f}{unit}/分' if avg is not None else '—'
        acc = snap['accuracy']
        acc_s = f'{acc * 100:.1f}%' if acc is not None else '—'
        return f'{snap["valid"]:,} 字 · {avg_s} · 正确率 {acc_s}'

    def show_and_raise(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def open_training(self):
        if hasattr(self, '_challenge_page'):
            self._tabs.setCurrentWidget(self._challenge_page)

    def _motion_active(self):
        running = any(bool(getattr(getattr(self, name, None), '_running', False))
                      for name in ('_challenge_page', '_english_page'))
        return (self.isVisible() and not self.isMinimized() and not running
                and self._repo.get_setting('reduced_motion', '0') != '1')

    def _sync_motion(self, *_):
        active = self._motion_active()
        self._backdrop.set_motion_enabled(active)
        self._starfield.set_paused(not active)
        self._dashboard.resume_animations(active)
        self._nav.set_motion_enabled(active)
        self._english_page.set_motion_enabled(active)
        if not active:
            self._confetti.stop()
        for popup in self.findChildren(CheckinPopup) + self.findChildren(ToastPopup):
            popup.set_motion_enabled(active)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_motion()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sync_motion()

    def open_settings(self, checked=False, *, section=''):
        dlg = SettingsDialog(self._repo, self._balance, self,
                             theme_manager=self._theme_mgr,
                             data_dir=self._data_dir)
        if section == 'ai':
            dlg._sections.setCurrentRow(3)
        if dlg.exec():
            self._engine.update_day_start()   # 日切起点设置即时生效
            if self._hook is not None:
                self._hook.set_excluded_apps(self.load_excluded_apps())
            if hasattr(self, '_profile_page'):
                self._profile_page.refresh()
            self.refresh()
        self._sync_motion()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if self._tray is not None:
            self._tray.showMessage(
                '打字管家', '已最小化到托盘，后台继续统计打字。',
                QSystemTrayIcon.Information, 2000)

    def changeEvent(self, event):
        """隐藏和恢复时同步装饰动画；窗口尺寸约束由独立策略处理。"""
        if event.type() == event.Type.WindowStateChange:
            self._sync_motion()
        super().changeEvent(event)
