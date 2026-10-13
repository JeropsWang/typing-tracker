"""Qt presentation for asynchronous update checks, downloads and exit coordination."""
from __future__ import annotations
import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import __version__
from ..integrations.updates import UpdateCancelled, installation_kind
from ..integrations.updates.service import background
from .tasks import TaskBridge
from .presenters import PracticeState


class UpdateController(QObject):
    changed = Signal()
    progressed = Signal(object, object)
    install_requested = Signal(object)

    def __init__(self, application, service, parent=None, *, kind=None, clock=time.time):
        super().__init__(parent)
        self.application, self.service = application, service
        self.kind = kind or installation_kind()
        self.clock = clock
        self.release = None
        self.installer = None
        self.busy = False
        self.downloading = False
        self.status = '尚未检查更新。'
        self.progress = (0, 0)
        self._cancel = threading.Event()
        self._paused = False
        self._last_attempt = 0
        self._tasks = TaskBridge(self)
        self.progressed.connect(self._progress, Qt.QueuedConnection)
        self._timer = QTimer(self)
        self._timer.setInterval(60 * 60 * 1000)
        self._timer.timeout.connect(self.auto_check)
        self._timer.start()
        QTimer.singleShot(8_000, self.auto_check)

    def auto_check(self):
        if self._paused or self.application.models.get_setting('updates_auto_check', '1') == '0':
            return
        try:
            previous = float(self.application.models.get_setting('updates_last_check', '0'))
        except (ValueError, TypeError):
            previous = 0
        previous = max(previous, self._last_attempt)
        if self.clock() - previous >= 24 * 60 * 60:
            self.check()

    def check(self, manual=False):
        if self.busy or self._paused:
            return
        self.busy = True
        self.status = '正在检查 GitHub 正式版本…'
        self.changed.emit()
        # Persist attempts as well as successes, so outages do not cause startup retries.
        self._last_attempt = self.clock()
        self.application.set_setting('updates_last_check', str(self._last_attempt))
        self._tasks.resolve(background(self.service.check), self._checked, self._failed)

    def _checked(self, release):
        self.busy = False
        self.release = release
        self.installer = None
        if release is None:
            self.status = '当前已是最新正式版本。'
        else:
            self.status = f'发现新版本 {release.version}。'
            if self.kind == 'source':
                self.status += ' 源码运行，请在版本页查看更新。'
            elif self.kind == 'installed' and release.installer is None:
                self.status += ' 此版本没有 Windows x64 安装包。'
            elif self.kind == 'portable' and release.portable is None:
                self.status += ' 此版本没有便携包。'
        self.changed.emit()

    def _failed(self, error):
        self.busy = self.downloading = False
        self.status = str(error) if not isinstance(error, UpdateCancelled) else '下载已取消。'
        self.changed.emit()

    def download(self):
        if self.busy or self._paused or self.kind != 'installed' or not self.release or not self.release.installer:
            return
        self._cancel = threading.Event()
        self.busy = self.downloading = True
        self.installer = None
        self.progress = (0, self.release.installer.size)
        self.status = '正在下载安装包…'
        self.changed.emit()
        self._tasks.resolve(background(lambda: self.service.download(self.release, self._cancel, self.progressed.emit)),
                            self._downloaded, self._failed)

    def _progress(self, received, total):
        if self.downloading:
            self.progress = (received, total)
            self.changed.emit()

    def _downloaded(self, installer):
        self.busy = self.downloading = False
        self.installer = installer
        self.status = '安装包已通过大小与 SHA-256 校验，可以退出并安装。'
        self.changed.emit()

    def cancel(self):
        if self.downloading:
            self._cancel.set()
            self.status = '正在取消下载…'
            self.changed.emit()

    def request_install(self):
        if self.busy or self.installer is None or self._paused:
            return
        self.busy = True
        self.status = '正在重新校验安装包…'
        self.changed.emit()
        def verified(installer):
            self.busy = False
            self.status = '安装包已校验。'
            self.changed.emit()
            self.install_requested.emit(installer)
        self._tasks.resolve(background(self.installer.verify), verified, self._failed)

    def set_paused(self, paused):
        self._paused = paused

    def shutdown(self):
        self._paused = True
        self._timer.stop()
        self.cancel()


class UpdateExitCoordinator(QObject):
    """Serialize stop, final commit, helper launch and worker close without UI waits."""
    def __init__(self, application, stop_input, launch_helper, completed, failed, parent=None):
        super().__init__(parent)
        self.application = application
        self.stop_input, self.launch_helper = stop_input, launch_helper
        self.completed, self.failed = completed, failed
        self.busy = False
        self._helper = None
        self._tasks = TaskBridge(self)

    def begin(self, installer):
        if self.busy:
            return
        self.busy = True
        self._helper = None
        self._installer = installer
        self._tasks.resolve(background(self.stop_input), self._stopped, self._failed)

    def _stopped(self, _):
        self._tasks.resolve(self.application.prepare_update_exit(), self._prepared, self._failed)

    def _prepared(self, _):
        self._tasks.resolve(background(lambda: self.launch_helper(self._installer)), self._launched, self._failed)

    def _launched(self, helper):
        self._helper = helper
        self._tasks.resolve(self.application.finish_update_exit(), self._closed, self._failed)

    def _closed(self, _):
        if self._helper is not None:
            self._tasks.resolve(background(self._helper.authorize), self._authorized, self._failed)
        else:
            self._authorized(None)

    def _authorized(self, _):
        self.busy = False
        self.completed()

    def _failed(self, error):
        self.busy = False
        if self._helper is not None:
            helper,self._helper=self._helper,None
            background(helper.cancel)
        self.application.cancel_update_exit()
        self.failed(error)


class UpdatesWidget(QWidget):
    def __init__(self, queries, controller=None, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        title = QLabel(f'应用更新 · 当前版本 {__version__}')
        title.setProperty('textRole', 'paperField')
        layout.addWidget(title)
        self.auto_check = QCheckBox('自动检查正式版本（每天最多一次）')
        self.auto_check.setChecked(queries.get_setting('updates_auto_check', '1') != '0')
        layout.addWidget(self.auto_check)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setProperty('textRole', 'paperMuted')
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.check = QPushButton('检查更新')
        self.action = QPushButton('下载新版')
        self.cancel = QPushButton('取消下载')
        for button in (self.check, self.action, self.cancel):
            button.setProperty('buttonRole', 'secondary')
            button.setAutoDefault(False)
            button.setMinimumHeight(42)
            button.setStyleSheet('QPushButton { min-height:42px; }')
            row.addWidget(button)
        layout.addLayout(row)
        if controller:
            self.check.clicked.connect(lambda: controller.check(manual=True))
            self.action.clicked.connect(self._action)
            self.cancel.clicked.connect(controller.cancel)
            controller.changed.connect(self.refresh)
        self.refresh()

    def values(self):
        return {'updates_auto_check': '1' if self.auto_check.isChecked() else '0'}

    def _action(self):
        controller = self.controller
        if controller.kind == 'portable':
            if controller.release and controller.release.portable:
                QDesktopServices.openUrl(QUrl(controller.release.portable.url))
        elif controller.kind == 'source':
            if controller.release:
                QDesktopServices.openUrl(QUrl(controller.release.url))
        elif controller.installer:
            controller.request_install()
        else:
            controller.download()

    def refresh(self):
        controller = self.controller
        if not controller:
            self.status.setText('源码或预览环境未装配更新服务。')
            self.check.setEnabled(False)
            self.action.hide()
            self.cancel.hide()
            self.progress.hide()
            return
        self.status.setText(controller.status)
        self.check.setEnabled(not controller.busy)
        release = controller.release
        self.action.setVisible(release is not None)
        available = bool(release and (controller.kind == 'source' or
                         (release.portable if controller.kind == 'portable' else release.installer)))
        self.action.setEnabled(available and not controller.busy)
        self.action.setText('查看版本信息' if controller.kind == 'source' else '下载便携 ZIP' if controller.kind == 'portable'
                            else '退出并安装' if controller.installer else '下载安装包')
        self.cancel.setVisible(controller.downloading)
        self.progress.setVisible(controller.downloading)
        received, total = controller.progress
        self.progress.setValue(int(received * 100 / total) if total else 0)


def update_exit_status(window):
    """Return saving/unfinished flags across existing learning surfaces."""
    page = window._challenge_page
    keyboard = page.keyboard_panel
    state = page._presenter.state
    saving = (state == PracticeState.SAVING or page._material_saving or keyboard._saving)
    unfinished = (state in (PracticeState.RUNNING, PracticeState.SAVE_FAILED) or
                  keyboard.session is not None or page._pending_material is not None or
                  page._gen_thread is not None or page.chaos_panel.request is not None)
    english_saving, english_unfinished = window._english_page.update_exit_status()
    saving = saving or english_saving or window._application.has_pending_commands()
    # Includes an open settings dialog's unsaved asynchronous submission.
    saving = saving or any(getattr(child, '_saving', False) for child in window.findChildren(QWidget))
    return bool(saving), bool(unfinished or english_unfinished)


def discard_learning_for_update(window):
    page = window._challenge_page
    page._cancel_generation()
    page._reset()
    page.keyboard_panel.cancel()
    # Failed keyboard results are explicitly abandoned only after the user's choice.
    page.keyboard_panel.session = None
    page.keyboard_panel._pending = False
    page.chaos_panel.hide()
    window._english_page.discard_for_update()
