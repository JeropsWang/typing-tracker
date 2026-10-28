"""占卜专用Qt异步控制器；复用智能体网络准入，不读数据库或来信历史。"""
from PySide6.QtCore import QObject, Signal, Qt
from ...modules.companion.api import AgentConfig, OracleResult
from ..tasks import TaskBridge
from .agent_widgets import AgentInputDialog
from .oracle_widgets import OracleCard


class OracleController(QObject):
    """主线程管理占卜输入、请求所有者和已验证结果，后台只发送排队信号。"""
    progress_arrived = Signal(object)

    def __init__(self, agent):
        """建立独立占卜浮层，搜索与来信继续复用现有控制器。"""
        super().__init__(agent)
        self.agent, self.service = agent, agent.service
        self.tasks = TaskBridge(self)
        self.input = AgentInputDialog(title='想让星星判断什么？', limit=50, purpose='oracle')
        self.input.setWindowTitle('Sariana · 占卜')
        self.card = OracleCard()
        self.input.submitted.connect(self.submit)
        self.card.cancel_requested.connect(self.cancel)
        # 收起是用户的显示决定；任务可以继续，但迟到成功不能重新弹出卡片。
        self.card.close_button.clicked.connect(self.hide)
        self.card.dismissed.connect(self._card_hidden)
        self.progress_arrived.connect(self._progress, Qt.QueuedConnection)
        self._request_id = None
        self._stopped = False
        self._dismissed = False

    @property
    def busy(self):
        """只读表示当前Qt控制器是否仍接收占卜任务；网络准入由服务独立持有。"""
        return self._request_id is not None

    def open(self):
        """显示占卜草稿；搜索或自身在途时展示已有状态，不另发请求。"""
        if self._stopped:
            return
        if self.agent._busy:
            self.agent._place(self.agent.card)
            self.agent.card.show()
            return
        if self.busy:
            self._dismissed = False
            self.agent._place(self.card)
            self.card.show()
            return
        if not AgentConfig.from_settings(self.agent.presenter).enabled:
            self.agent.open_settings()
            return
        self.input.feedback.clear()
        self.agent._place(self.input)
        self.input.show()
        self.input.raise_()
        self.input.activateWindow()
        self.input.topic.setFocus()

    def submit(self, question):
        """捕获已提交配置并启动模型任务，失败保留输入，不接收正文流。"""
        if self.busy or self._stopped or self.agent._busy:
            return
        try:
            request_id, future = self.service.judge(AgentConfig.from_settings(self.agent.presenter),
                                                      question, self.progress_arrived.emit)
        except Exception as error:
            self.input.feedback.setText(str(error))
            return
        self._request_id = request_id
        self._dismissed = False
        self.input.hide()
        self.agent.actions.hide()
        self.card.question.setText(question)
        self.card.show_status('正在判断这个小问题。', busy=True)
        self.agent._place(self.card)
        self.card.show()
        self.agent.companion.set_agent_feedback('focused', '让我听听星星怎么说。')
        self.tasks.resolve(future, lambda result: self._finished(request_id, result),
                           lambda error: self._failed(request_id, error))

    def _progress(self, progress):
        """只接受本次请求的固定进度阶段，忽略供应商正文及已取消进度。"""
        if not self._stopped and progress.request_id == self._request_id:
            self.card.show_status('正在修正概率格式。' if progress.stage == 'repairing' else
                                  '正在判断这个小问题。', busy=True)

    def _finished(self, request_id, result):
        """先核准所有者再修改状态，取消或关闭后迟到结果不影响新任务。"""
        if self._stopped or request_id != self._request_id:
            return
        self._request_id = None
        if not isinstance(result, OracleResult) or result.request_id != request_id:
            self.card.show_status('模型结果无效，请重新判断。')
        else:
            self.card.show_result(result)
            self.agent.companion.set_agent_feedback('happy', '星星的小答案送到了。', duration=5)
        if self.agent.companion.view.isVisible() and not self._dismissed:
            self.agent._place(self.card)
            self.card.show()

    def _failed(self, request_id, error):
        """仅当前任务可结束自己的展示，后台错误保持既有脱敏提示。"""
        if self._stopped or request_id != self._request_id:
            return
        self._request_id = None
        self.card.show_status(str(error))
        self.agent.companion.set_agent_feedback('pout', '这次没听清星星的回答。', duration=5)

    def cancel(self):
        """作废本次结果并请求所有者取消，真正网络结束前不提前释放共享准入。"""
        if self._request_id is not None:
            self.service.cancel(self._request_id)
        self._request_id = None
        self.card.show_status('已经取消。正在结束在途请求。')
        self.agent.companion.set_agent_feedback()

    def _card_hidden(self):
        """记录所有原生关闭路径的显示决定，不取消仍在执行的网络任务。"""
        self._dismissed = True

    def hide(self):
        """跟随桌宠隐藏浮层，禁止完成后自动重弹。"""
        self._dismissed = True
        self.input.hide()
        self.card.hide()

    def place_visible(self):
        """宿主移动和尺寸变化后重定位当前可见的占卜浮层。"""
        for widget in (self.input, self.card):
            if widget.isVisible():
                self.agent._place(widget)

    def shutdown(self):
        """退出时作废任务、取消所有者并销毁独立浮层。"""
        if self._stopped:
            return
        self._stopped = True
        self.cancel()
        self.hide()
        self.input.deleteLater()
        self.card.deleteLater()
