"""系统托盘：驻留后台、快捷菜单、今日速览。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import APP_DISPLAY_NAME, APP_NAME
from .assets.app_icon import tray_icon


class TrayIcon(QSystemTrayIcon):
    """Qt 主线程系统托盘入口，展示只读摘要并通过信号请求显示、配置或退出。"""
    show_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        """创建品牌图标、今日摘要和托盘操作菜单，不访问数据库。"""
        super().__init__(parent)
        # tray_icon() 内部：交付 PNG 优先，缺失/读不出时回退程序化绘制
        self.setIcon(tray_icon())
        self.setToolTip(APP_DISPLAY_NAME)

        menu = QMenu()
        act_show = menu.addAction('显示主界面')
        act_show.triggered.connect(self.show_requested)
        self._act_summary = menu.addAction('今日：加载中…')
        self._act_summary.setEnabled(False)
        menu.addSeparator()
        act_settings = menu.addAction('设置…')
        act_settings.triggered.connect(self.settings_requested)
        act_quit = menu.addAction('退出')
        act_quit.triggered.connect(self.quit_requested)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason):
        """用户普通点击托盘时发布显示主窗口信号。"""
        if reason == QSystemTrayIcon.Trigger:
            self.show_requested.emit()

    def update_summary(self, text: str):
        """同步今日摘要菜单与托盘提示，不改变统计口径。"""
        self._act_summary.setText(f'今日：{text}')
        self.setToolTip(f'{APP_NAME}\n今日：{text}')

    def bind_companion(self, controller):
        """为已装配桌宠增加显示/模式/工坊菜单，操作转交桌宠控制器。"""
        menu = self.contextMenu()
        companion = menu.addMenu('Sariana 小伙伴')
        companion.addAction('显示角色', controller.show_companion)
        companion.addAction('收起角色', controller.hide_companion)
        companion.addSeparator()
        companion.addAction('应用窗口内', lambda: controller.switch_mode('window'))
        companion.addAction('桌面宠物', lambda: controller.switch_mode('desktop'))
        companion.addAction('本地二创工坊…', controller.open_workshop)
