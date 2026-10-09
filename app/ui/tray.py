"""系统托盘：驻留后台、快捷菜单、今日速览。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .assets.app_icon import tray_icon


class TrayIcon(QSystemTrayIcon):
    show_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # tray_icon() 内部：交付 PNG 优先，缺失/读不出时回退程序化绘制
        self.setIcon(tray_icon())
        self.setToolTip('打字管家')

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
        if reason == QSystemTrayIcon.Trigger:
            self.show_requested.emit()

    def update_summary(self, text: str):
        self._act_summary.setText(f'今日：{text}')
        self.setToolTip(f'打字管家\n今日：{text}')

    def bind_companion(self, controller):
        menu = self.contextMenu()
        companion = menu.addMenu('Sariana 小伙伴')
        companion.addAction('显示角色', controller.show_companion)
        companion.addAction('收起角色', controller.hide_companion)
        companion.addSeparator()
        companion.addAction('应用窗口内', lambda: controller.switch_mode('window'))
        companion.addAction('桌面宠物', lambda: controller.switch_mode('desktop'))
        companion.addAction('本地二创工坊…', controller.open_workshop)
