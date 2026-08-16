"""主窗口：今日概览 + 1 秒刷新 + 关闭即驻留托盘 + 星空背景/动效/弹窗。"""
from __future__ import annotations

import json
from datetime import date, timedelta

from PySide6.QtCore import Qt, QEasingCurve, QPropertyAnimation, QTimer
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect, QLabel, QMainWindow, QSystemTrayIcon, QTabWidget,
    QToolBar,
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
from .settings_dialog import SettingsDialog
from .widgets.checkin_popup import CheckinPopup
from .widgets.starfield import StarField
from .widgets.toast_popup import ToastPopup


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
                 theme_manager=None, challenge=None):
        super().__init__()
        self._engine = engine
        self._repo = repo
        self._balance = balance
        self._tray = tray
        self._theme_mgr = theme_manager
        self._effects = {}
        self._accent = '#60a5fa'
        self._dark = True
        self._popups = []
        self._last_level = None
        self._tab_anims = []

        self.setWindowTitle(f'打字管家 v{__version__}')
        self.resize(900, 640)

        # 星空背景（主题 effects 控制显隐）
        self._starfield = StarField(self)
        self._starfield.setGeometry(self.rect())
        self._starfield.lower()

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
            self._profile_page = ProfilePage(repo, balance, engine,
                                             achievements, rewards)
            self._tabs.addTab(self._profile_page, '个人中心')
            self._tabs.setTabIcon(4, svg_icon('user', '#94A3B8'))
        if challenge is not None:
            self._challenge_page = ChallengePage(repo, balance, challenge)
            self._tabs.addTab(self._challenge_page, '竞速')
            self._tabs.setTabIcon(5, svg_icon('zap', '#94A3B8'))
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self._tabs)

        tb = QToolBar('工具')
        tb.setMovable(False)
        act_settings = tb.addAction('设置…')
        act_settings.triggered.connect(self.open_settings)
        self.addToolBar(tb)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    def _on_reward_granted(self):
        self.refresh()

    # ---------- 主题 effects ----------
    def apply_effects(self, effects: dict) -> None:
        """主题切换时应用动态效果配置（星空/渐变/光效/配色）。"""
        self._effects = effects or {}
        self._starfield.configure(self._effects)
        colors = self._effects.get('levelbar', {}).get('colors')
        if colors:
            self._dashboard.set_level_colors(colors)
        accent = self._effects.get('accent')
        if accent:
            self._accent = accent
        self._dark = bool(self._effects.get('dark', True))
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

    def resizeEvent(self, event):
        self._starfield.setGeometry(self.rect())
        self._starfield.lower()
        super().resizeEvent(event)

    # ---------- 弹窗 ----------
    def show_checkin_popup(self, result: dict) -> None:
        """每日签到弹窗（居中显示，动态动画）。"""
        if not self.isVisible():
            return
        popup = CheckinPopup(self, result, self._balance,
                             accent=self._accent, dark=self._dark)
        popup.adjustSize()
        popup.move((self.width() - popup.width()) // 2,
                   (self.height() - popup.height()) // 2 - 30)
        popup.show()
        popup.raise_()
        popup.start_animation()

    def show_toast(self, title: str, msg: str, kind: str = 'star') -> None:
        """成就/升级/鼓励小弹窗（右上角堆叠，动画滑入，自动消失）。"""
        if not self.isVisible():
            return
        popup = ToastPopup(self, title, msg, kind=kind,
                           accent=self._accent, dark=self._dark)
        popup.adjustSize()
        y = 46 + len(self._popups) * (popup.height() + 10)
        popup.move(self.width() - popup.width() - 18, y)
        popup.show()
        popup.raise_()
        popup.start_animation()
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
        if index == 1:
            self._reports.refresh()
        elif index == 2 and hasattr(self, '_checkin_page'):
            self._checkin_page.refresh()
        elif index == 3 and hasattr(self, '_ach_page'):
            self._ach_page.refresh()
        elif index == 4 and hasattr(self, '_profile_page'):
            self._profile_page.refresh()
        elif index == 5 and hasattr(self, '_challenge_page'):
            self._challenge_page._refresh_recent()
        # 页面淡入
        page = self._tabs.widget(index)
        if page is not None:
            eff = QGraphicsOpacityEffect(page)
            page.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b'opacity', self)
            anim.setDuration(180)
            anim.setStartValue(0.25)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            self._tab_anims.append(anim)
            anim.finished.connect(lambda: self._tab_anims_done(anim))
            anim.start()

    def _tab_anims_done(self, anim) -> None:
        if anim in self._tab_anims:
            self._tab_anims.remove(anim)

    # ---------- 刷新 ----------
    def refresh(self):
        snap = self._engine.snapshot()
        exp = self._repo.get_exp()
        level, progress, _ = level_and_progress(exp, self._balance)
        title = band_title(level, self._balance, _load_bands(self._balance, self._repo))
        active = self._repo.get_setting('active_title', '')
        if active:
            title = active
        unit = self._repo.get_setting('unit_name', self._balance['unit']['name'])
        streak = current_streak(self._repo, self._engine.current_day())
        self._dashboard.refresh(snap, level, progress, title, streak, unit)

        # 升级检测 → 小弹窗
        if self._last_level is not None and level > self._last_level:
            self.show_toast('🎉 升级！',
                            f'Lv.{self._last_level} → Lv.{level}　称号「{title}」',
                            kind='level')
        self._last_level = level

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

    def open_settings(self):
        dlg = SettingsDialog(self._repo, self._balance, self,
                             theme_manager=self._theme_mgr)
        if dlg.exec():
            self._engine.update_day_start()   # 日切起点设置即时生效
            if self._hook is not None:
                self._hook.set_excluded_apps(self.load_excluded_apps())
            self.refresh()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if self._tray is not None:
            self._tray.showMessage(
                '打字管家', '已最小化到托盘，后台继续统计打字。',
                QSystemTrayIcon.Information, 2000)
