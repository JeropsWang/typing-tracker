"""Qt-thread presenter for network-only companion runs and reusable overlays."""
from PySide6.QtCore import QObject, Signal, Qt, QTimer, QEvent, QPoint
from PySide6.QtGui import QCursor
from ...modules.companion.api import AgentConfig
from ...bootstrap.features import companion_agent_service, companion_setup_service
from ..tasks import TaskBridge
from .desktop import clamp_position, available_screens
from .agent_widgets import AgentActions, AgentInputDialog, AgentDialogueCard, AgentReportDialog, agent_style
from .agent_settings import AgentSettingsDialog
from .artwork import sprite_icon


class CompanionAgentController(QObject):
    """Qt 主线程的智能体展示控制器：管理浮层、请求标识和桌宠反馈，不持有数据库。"""
    progress_arrived = Signal(object)

    def __init__(self, companion, *, service=None, data_dir=None):
        """装配轮盘、输入、报告和异步桥接，连接网络进度信号及悬停/思考计时器。"""
        super().__init__(companion)
        self.companion = companion
        self.presenter = companion.presenter
        self.setup = companion_setup_service()
        self.service = service or companion_agent_service()
        self.tasks = TaskBridge(self)
        self.actions = AgentActions()
        self.input = AgentInputDialog()
        self.card = AgentDialogueCard()
        self.detail = AgentReportDialog()
        self.settings = None
        self.report = None
        self._request_id = None
        self._busy = False
        self._stopped = False
        self._card_dismissed = False
        self._thinking_stage = 'searching'
        self._thinking_index = 0
        self.actions.search_requested.connect(self.open_search)
        self.input.submitted.connect(self.search)
        self.card.detail_requested.connect(self.open_detail)
        self.card.config_requested.connect(self.open_settings)
        self.card.cancel_requested.connect(self.cancel)
        self.card.search_requested.connect(self.open_search)
        self.progress_arrived.connect(self._progress, Qt.QueuedConnection)
        companion.view.installEventFilter(self)
        companion.window.installEventFilter(self)
        self._hover = QTimer(self)
        self._hover.setInterval(200)
        self._hover.timeout.connect(self._hover_tick)
        self._thinking = QTimer(self)
        self._thinking.setInterval(6000)
        self._thinking.timeout.connect(self._thinking_tick)

    def sync_motion(self):
        """读取减弱动态效果设置，同步轮盘和阶段指示器的动效开关。"""
        enabled = self.presenter.get_setting('reduced_motion', '0') != '1'
        self.actions.set_motion_enabled(enabled)
        self.card.journey.set_motion_enabled(enabled)

    def _pet_feedback(self, stage):
        """按真实任务阶段和短句序号请求桌宠专注反馈，交给桌宠控制器处理显示优先级。"""
        lines = {'searching': ('好奇心出发！我去找找线索。', '正在资料海里捞小星星…'),
                 'reading': ('找到啦，让我核对一下原文。', '认真读一读，帮你少走弯路。'),
                 'summarizing': ('我在努力思考，把重点串起来。', '小脑袋转呀转，手信快写好了。')}
        self.companion.set_agent_feedback('focused', lines.get(stage, lines['summarizing'])[self._thinking_index % 2])

    def _thinking_tick(self):
        """任务仍有效且桌宠可见时轮换思考短句；否则停止视觉计时器。"""
        if self._request_id is None or not self.companion.view.isVisible():
            self._thinking.stop()
            return
        self._thinking_index += 1
        self._pet_feedback(self._thinking_stage)

    def eventFilter(self, watched, event):
        """跟随主窗口/桌宠移动定位浮层，处理悬停入口及隐藏后的视觉收起。"""
        if watched is self.companion.window and event.type() == QEvent.Move:
            for widget in (self.actions, self.card, self.input):
                if widget.isVisible():
                    self._place(widget, above=widget is not self.actions)
        if watched is self.companion.view:
            if event.type() == QEvent.Enter and not self._stopped:
                self.sync_motion()
                self.actions.setStyleSheet(agent_style())
                self._place(self.actions, above=False)
                self.actions.show()
                self.companion._render()
                self._hover.start()
            elif event.type() == QEvent.Show and self._request_id is not None:
                self._thinking.start()
            elif event.type() in (QEvent.Hide, QEvent.Close):
                self.hide_overlays()
            elif event.type() in (QEvent.Move, QEvent.Resize):
                if self.actions.isVisible():
                    self._place(self.actions, above=False)
                if self.card.isVisible():
                    self._place(self.card)
                if self.input.isVisible():
                    self._place(self.input)
        return False

    def _hover_tick(self):
        """鼠标离开桌宠和轮盘区域后隐藏工具入口，并停止悬停轮询。"""
        point = QCursor.pos()
        view = self.companion.view
        if not (view.isVisible() and (view.rect().contains(view.mapFromGlobal(point)) or
                                     self.actions.rect().contains(self.actions.mapFromGlobal(point)))):
            self.actions.hide()
            self.companion._render()
            self._hover.stop()

    def _place(self, widget, *, above=True):
        """以桌宠全球坐标定位浮层；上方不足时改放侧边，并限制在可用屏幕内。"""
        view = self.companion.view
        origin = view.mapToGlobal(QPoint())
        x = origin.x() + (view.width() - widget.width()) // 2
        pet = view.image_rect()
        if widget is self.actions:
            y = origin.y() + pet.top() - 60
        else:
            y = origin.y() - widget.height() - 4 if above else origin.y() + view.height() + 4
            area = next((r for r in available_screens() if r.contains(origin)), available_screens()[0])
            if above and y < area.top():
                # Beside the pet when there is no room above; never cover its face.
                x = origin.x() - widget.width() - 8
                if x < area.left():
                    x = origin.x() + view.width() + 8
                y = origin.y()
        widget.move(clamp_position(QPoint(x, y), widget.width(), widget.height()))
        if hasattr(widget, 'set_anchor'):
            widget.set_anchor(origin + QPoint(view.width() // 2, pet.top()))

    def open_search(self):
        """显示话题输入；未启用时打开配置，在途任务则展示当前卡片，保留已有草稿。"""
        if self._stopped:
            return
        if self._busy:
            self._card_dismissed = False
            self._place(self.card)
            self.card.show()
            return
        config = AgentConfig.from_settings(self.presenter)
        if not config.enabled:
            self.open_settings()
            return
        if not self.input.topic.text():
            self.input.topic.setText(config.default_topic)
        self.input.setStyleSheet(agent_style())
        self.sync_motion()
        self.input.feedback.setText('')
        self._place(self.input)
        self.input.show()
        self.input.raise_()
        self.input.activateWindow()
        self.input.topic.setFocus()

    def search(self, topic):
        """用已提交配置启动后台搜索，记录请求 ID，切换忙碌展示并异步接收结果。"""
        if self._busy or self._stopped:
            return
        try:
            request_id, future = self.service.search(AgentConfig.from_settings(self.presenter), topic,
                                                       self.progress_arrived.emit)
        except Exception as error:
            self.input.feedback.setText(str(error))
            return
        self._request_id = request_id
        self._busy = True
        self._thinking_stage = 'searching'
        self._thinking_index = 0
        self.sync_motion()
        self.actions.set_busy(True)
        self._pet_feedback('searching')
        if self.companion.view.isVisible():
            self._thinking.start()
        self._card_dismissed = False
        self.input.hide()
        self.actions.hide()
        self.card.setStyleSheet(agent_style())
        self.card.show_progress('我在努力找资料，稍等一下就回来。')
        self._place(self.card)
        self.card.show()
        self.tasks.resolve(future, lambda report: self._finished(request_id, report),
                           lambda error: self._failed(request_id, error))

    def _progress(self, progress):
        """仅接收当前有效请求的排队进度，更新正文草稿或阶段及桌宠姿态。"""
        if not self._stopped and progress.request_id == self._request_id:
            if progress.stage == 'streaming':
                self.card.show_partial(progress.text)
            else:
                self.card.show_progress(progress.text, progress.stage)
                self._thinking_stage = progress.stage
                self._thinking_index = 0
                self._pet_feedback(progress.stage)

    def _finished(self, request_id, report):
        """回收忙碌状态并拒绝迟到报告；保存有效报告到内存，按可见性决定是否弹卡片。"""
        if self._stopped:
            return
        self._busy = False
        self._thinking.stop()
        self.actions.set_busy(False)
        if request_id != self._request_id:
            return
        self._request_id = None
        self.report = report
        self.card.show_report(report)
        self.companion.set_agent_feedback('happy' if not report.warning else 'surprised',
            '回来啦！把新鲜事装进手信给你。' if not report.warning else '先带回这些线索，我们再看看。', duration=5)
        if self.companion.view.isVisible() and not self._card_dismissed:
            self._place(self.card)
            self.card.show()

    def _failed(self, request_id, error):
        """回收忙碌状态并过滤失效请求，展示可读错误和桌宠失败回应。"""
        if self._stopped:
            return
        self._busy = False
        self._thinking.stop()
        self.actions.set_busy(False)
        if request_id != self._request_id:
            return
        self._request_id = None
        self.card.show_error(str(error))
        self.companion.set_agent_feedback('pout', '线索打了个结，陪你再试一次。', duration=5)

    def cancel(self):
        """取消网络任务并立即作废 UI 请求 ID；后台准入由服务在实际结束后释放。"""
        self.service.cancel()
        self._request_id = None
        self._thinking.stop()
        self.actions.set_busy(False)
        self.companion.set_agent_feedback()
        self.card.show_error('已经取消。正在结束在途请求，结束后可以重新搜索。')

    def open_detail(self):
        """将内存中的有效报告装入详情窗口，定位后激活，不重新请求网络。"""
        if self.report is not None and not self._stopped:
            self.detail.setStyleSheet(agent_style())
            self.detail.set_report(self.report)
            self._place(self.detail)
            self.detail.show()
            self.detail.raise_()
            self.detail.activateWindow()

    def show_last_report(self):
        """重新展示最近一次内存报告，不保存数据库也不重新搜索。"""
        if self.report is not None and not self._stopped:
            self.card.show_report(self.report)
            self._place(self.card)
            self.card.show()

    def open_settings(self, parent=None):
        """复用已打开的配置窗口，或用当前桌宠头像创建新的草稿配置页。"""
        if self._stopped:
            return
        if self.settings is not None and self.settings.isVisible():
            self.settings.raise_()
            self.settings.activateWindow()
            return
        if self.settings is not None:
            self.settings.deleteLater()
        sprite = self.companion.pack.asset_for('idle')
        self.settings = AgentSettingsDialog(self.presenter, parent, setup=self.setup,
                                           portrait=sprite_icon(sprite.path, sprite.rect))
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def hide_overlays(self):
        """收起全部搜索浮层并停止视觉计时器，保留输入草稿和报告。"""
        self._card_dismissed = True
        self._hover.stop()
        self._thinking.stop()
        for widget in (self.actions, self.input, self.card, self.detail):
            widget.hide()

    def shutdown(self):
        """停止接收结果，取消网络与检查服务，销毁浮层，供桌宠退出调用。"""
        if self._stopped:
            return
        self._stopped = True
        self._thinking.stop()
        self.companion.set_agent_feedback()
        self.service.close()
        self.setup.close()
        self._request_id = None
        self.hide_overlays()
        for widget in (self.actions, self.input, self.card, self.detail, self.settings):
            if widget is not None:
                widget.hide()
                widget.deleteLater()
