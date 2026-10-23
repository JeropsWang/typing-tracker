"""Qt presentation for asynchronous update checks, downloads and exit coordination."""
from __future__ import annotations
import threading
import time

from PySide6.QtCore import QObject, QTimer, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .. import __version__
from ..integrations.updates import UpdateCancelled, installation_kind, RELEASES_URL
from ..integrations.updates.service import background
from .tasks import TaskBridge
from .presenters import PracticeState


class UpdateController(QObject):
    """Qt 主线程更新展示控制器，网络异步执行，自动检查限频且安装请求独立交接。"""
    changed = Signal()
    progressed = Signal(object, object)
    install_requested = Signal(object)

    def __init__(self, application, service, parent=None, *, kind=None, clock=time.time):
        """装配应用/网络/安装类型和检查时钟，创建异步桥及低频自动检查计时器。"""
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
        """仅开关允许且未暂停时按最后尝试时间每天最多检查一次。"""
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
        """异步检查正式版本并记录尝试时刻，网络故障不会导致启动反复检查。"""
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
        """显示较新版本或当前版本状态，依据源码/安装/便携类型提示可用附件。"""
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
        """恢复检查/下载状态并区分用户取消与可见错误。"""
        self.busy = self.downloading = False
        self.status = str(error) if not isinstance(error, UpdateCancelled) else '下载已取消。'
        self.changed.emit()

    def download(self):
        """仅安装版合格附件启动后台下载，创建本次取消信号和真实字节进度。"""
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
        """仅下载仍在进行时更新排队的接收/总字节数。"""
        if self.downloading:
            self.progress = (received, total)
            self.changed.emit()

    def _downloaded(self, installer):
        """记录已校验安装器并开放后续退出安装，不自动启动安装包。"""
        self.busy = self.downloading = False
        self.installer = installer
        self.status = '安装包已通过大小与 SHA-256 校验，可以退出并安装。'
        self.changed.emit()

    def cancel(self):
        """请求取消本次下载，实际网络结束前保留忙碌状态。"""
        if self.downloading:
            self._cancel.set()
            self.status = '正在取消下载…'
            self.changed.emit()

    def request_install(self):
        """安装前后台再次核对缓存文件，成功才发布独立安装请求。"""
        if self.busy or self.installer is None or self._paused:
            return
        self.busy = True
        self.status = '正在重新校验安装包…'
        self.changed.emit()
        def verified(installer):
            """重新校验成功后发布安装器，交应用退出协调流程处理。"""
            self.busy = False
            self.status = '安装包已校验。'
            self.changed.emit()
            self.install_requested.emit(installer)
        self._tasks.resolve(background(self.installer.verify), verified, self._failed)

    def set_paused(self, paused):
        """暂停新的检查/下载/安装入口，供退出交接使用。"""
        self._paused = paused

    def shutdown(self):
        """停止自动检查并取消当前下载，供应用退出清理。"""
        self._paused = True
        self._timer.stop()
        self.cancel()


class UpdateExitCoordinator(QObject):
    """Serialize stop, final commit, helper launch and worker close without UI waits."""
    def __init__(self, application, stop_input, launch_helper, completed, failed, parent=None):
        """装配停止输入、最终提交、辅助进程启动和退出回调，所有 UI 更新经 TaskBridge。"""
        super().__init__(parent)
        self.application = application
        self.stop_input, self.launch_helper = stop_input, launch_helper
        self.completed, self.failed = completed, failed
        self.busy = False
        self._helper = None
        self._tasks = TaskBridge(self)

    def begin(self, installer):
        """幂等开始更新退出，先异步停止输入采集再请求最后提交。"""
        if self.busy:
            return
        self.busy = True
        self._helper = None
        self._installer = installer
        self._tasks.resolve(background(self.stop_input), self._stopped, self._failed)

    def _stopped(self, _):
        """输入停止后排空并提交已接收写入，工作线程暂不关闭。"""
        self._tasks.resolve(self.application.prepare_update_exit(), self._prepared, self._failed)

    def _prepared(self, _):
        """最后保存成功后启动隐藏安装辅助进程，但尚不授权它执行安装。"""
        self._tasks.resolve(background(lambda: self.launch_helper(self._installer)), self._launched, self._failed)

    def _launched(self, helper):
        """记录本次辅助进程，再异步关闭已准备好的数据库工作线程。"""
        self._helper = helper
        self._tasks.resolve(self.application.finish_update_exit(), self._closed, self._failed)

    def _closed(self, _):
        """数据库实际关闭后才给辅助进程写授权，避免统计丢失时启动安装。"""
        if self._helper is not None:
            self._tasks.resolve(background(self._helper.authorize), self._authorized, self._failed)
        else:
            self._authorized(None)

    def _authorized(self, _):
        """授权完成后调用主程序退出回调，辅助进程继续等主进程终止。"""
        self.busy = False
        self.completed()

    def _failed(self, error):
        """取消本次辅助进程并恢复可重试应用状态，向 UI 返回失败。"""
        self.busy = False
        if self._helper is not None:
            helper,self._helper=self._helper,None
            background(helper.cancel)
        self.application.cancel_update_exit()
        self.failed(error)


class UpdatesWidget(QWidget):
    """设置页的更新展示/操作面板，保存检查开关草稿，网络动作交控制器。"""
    def __init__(self, queries, controller=None, parent=None):
        """创建版本、开关、检查/下载/取消控件并订阅更新展示变化。"""
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
        # 手动入口独立占一行；尚未查到版本、限流或断网时也能访问官方发布页。
        self.manual_download = QPushButton('打开版本页 · 手动下载')
        self.manual_download.setProperty('buttonRole', 'secondary')
        self.manual_download.setAutoDefault(False)
        self.manual_download.setMinimumHeight(44)
        self.manual_download.setStyleSheet('QPushButton { min-height:42px; }')
        self.manual_download.setToolTip('打开官方版本页，选择安装包或免安装 ZIP。')
        self.manual_download.clicked.connect(self._open_versions)
        layout.addWidget(self.manual_download)
        if controller:
            self.check.clicked.connect(lambda: controller.check(manual=True))
            self.action.clicked.connect(self._action)
            self.cancel.clicked.connect(controller.cancel)
            controller.changed.connect(self.refresh)
        self.refresh()

    def values(self):
        """交出自动检查开关草稿，供外层设置统一保存。"""
        return {'updates_auto_check': '1' if self.auto_check.isChecked() else '0'}

    def _open_versions(self):
        """打开固定仓库的官方最新版本页，不依赖 API 查询、不下载或启动安装器。"""
        QDesktopServices.openUrl(QUrl(RELEASES_URL))

    def _action(self):
        """按运行类型打开版本/便携下载链接，或请求安装版下载/交接。"""
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
        """按控制器状态同步按钮、文本和真实字节进度，无能力时禁用网络操作。"""
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
    """汇总学习、来信和设置的保存／未完成状态，更新不得吞掉内存待存报告。"""
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
    companion = getattr(window, '_companion', None)
    news = getattr(getattr(companion, 'agent', None), 'news', None)
    if news is not None:
        saving = saving or news.saving or news._claim_pending or news._transition
        unfinished = unfinished or news.busy
    return bool(saving), bool(unfinished or english_unfinished)


def discard_learning_for_update(window):
    """在用户已选择放弃之后清理未完成练习/生成，已受理保存不能由此撤销。"""
    page = window._challenge_page
    page._cancel_generation()
    page._reset()
    page.keyboard_panel.cancel()
    # Failed keyboard results are explicitly abandoned only after the user's choice.
    page.keyboard_panel.session = None
    page.keyboard_panel._pending = False
    page.chaos_panel.hide()
    window._english_page.discard_for_update()
    companion = getattr(window, '_companion', None)
    news = getattr(getattr(companion, 'agent', None), 'news', None)
    if news is not None:
        news.discard_for_update()
