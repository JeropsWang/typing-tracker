"""系统托盘：驻留后台、快捷菜单、今日速览。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon(QSystemTrayIcon):
    show_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(self._make_icon())
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

    @staticmethod
    def _make_icon() -> QIcon:
        pm = QPixmap(64, 64)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor('#3b82f6'))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(4, 4, 56, 56, 14, 14)
        p.setPen(QColor('white'))
        f = p.font()
        f.setBold(True)
        f.setPixelSize(22)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, 'TW')
        p.end()
        return QIcon(pm)
