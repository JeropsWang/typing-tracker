"""Qt 主线程来信 Presenter：有界唤醒、异步领取／保存、所有者取消与提交后通知。"""
from datetime import datetime, timezone
import uuid

from PySide6.QtCore import QObject, Signal, Qt, QTimer, QEvent

from ...modules.companion.api import (AgentConfig, AgentBusyError, NewsConfig, NewsRequest,
                                      configuration_fingerprint, due_plan, is_quiet, encode_report,
                                      agent_failure_code, failure_message, news_status, retryable_news_task)
from ..tasks import TaskBridge


class CompanionNewsController(QObject):
    """协调独立数据库与网络能力，不持有 DataSession，不在 Qt 等待未完成 Future。"""
    changed = Signal()
    progress_arrived = Signal(object)
    event_arrived = Signal(object)

    def __init__(self, companion, agent_controller, commands, queries, *, now_local=None, now_utc=None):
        """复用现有网络服务与卡片，建立三十秒唤醒及只在工作时运行的视觉计时器。"""
        super().__init__(companion)
        self.companion, self.agent, self.commands, self.queries = companion, agent_controller, commands, queries
        self.service = agent_controller.service
        self.now_local = now_local or datetime.now
        self.now_utc = now_utc or (lambda: datetime.now(timezone.utc).isoformat(timespec='seconds'))
        self.tasks = TaskBridge(self)
        self.status = ''
        self.pending_report = None
        self.saving = False
        self._pending_failure = None
        self._claim = None
        self._claim_pending = False
        self._transition = False
        self._notice_pending = False
        self._failure_notice = None
        self._network_id = None
        self._active_kind = None
        self._fingerprint = None
        self._invalidated = False
        self._paused = False
        self._stopped = False
        self._visual_index = 0
        self._maintenance_day = self.now_local().date().isoformat()
        self.progress_arrived.connect(self._progress, Qt.QueuedConnection)
        self.event_arrived.connect(self._event, Qt.QueuedConnection)
        application = getattr(queries, 'application', None)
        self._unsubscribe = application.events.subscribe(self.event_arrived.emit) if application is not None else None
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        self._visual = QTimer(self)
        self._visual.setInterval(6000)
        self._visual.timeout.connect(self._thinking)
        companion.view.installEventFilter(self)
        self.sync_settings()

    def eventFilter(self, watched, event):
        """隐藏只停视觉提示；重新显示且任务仍有效时恢复，排期唤醒始终独立。"""
        if watched is self.companion.view:
            if event.type() in (QEvent.Hide, QEvent.Close):
                self._visual.stop()
            elif event.type() == QEvent.Show and self._network_id and not self._paused and not self._stopped:
                self._visual.start()
        return False

    @property
    def busy(self):
        """结果保存失败也保留当前任务占位，防止一次点击意外产生第二次网络费用。"""
        return bool(self._claim_pending or self._transition or self._network_id or self.saving
                    or self.pending_report is not None or self._pending_failure is not None)

    def _capture(self):
        """从同一设置字典捕获模型与来信配置，数据库领取时仍会独立重新核准。"""
        values = self.queries.settings()
        agent, news = AgentConfig.from_settings(values), NewsConfig.from_values(values)
        enabled = values.get('companion_enabled', '1') != '0'
        return agent, news, enabled, configuration_fingerprint(agent, news, enabled)

    def sync_settings(self):
        """已提交配置变化使在途自动任务失效；只取消自己持有的网络请求。"""
        if self._stopped:
            return
        try:
            agent, news, enabled, current = self._capture()
            if not self.busy:
                self.status = news_status(self.queries.news_snapshot(), self.now_local(),
                                          agent_enabled=agent.enabled, companion_enabled=enabled).current
        except (TypeError, ValueError):
            current = 'invalid'
            self.status = '来信配置需要重新保存。'
        if self._fingerprint is not None and current != self._fingerprint and self._active_kind == 'auto':
            self._invalidated = True
            if self._network_id:
                self.service.cancel(self._network_id)
            if self.pending_report is not None and not self.saving:
                self.pending_report = None
                self._persist_failure('configuration_changed')
        self._fingerprint = current
        self.changed.emit()

    def _event(self, event):
        """工作线程事件通过排队信号到达 Qt 后刷新状态，不在订阅线程访问 QWidget。"""
        if self._stopped:
            return
        if event.topic == 'profile':
            self.sync_settings()
        if event.topic in ('profile', 'companion'):
            sync_memory = getattr(self.agent, 'sync_news_memory', None)
            if sync_memory is not None:
                sync_memory()
            self.changed.emit()

    def tick(self):
        """合并唤醒；无有效到期项时仅读快照，不排 SQL、不启动网络。"""
        if self._stopped or self._paused:
            return
        self.sync_settings()
        day = self.now_local().date().isoformat()
        if day != self._maintenance_day:
            # 启动已清理；自然日变化只提交一次有界维护，不把三十秒唤醒变成数据库轮询。
            self._maintenance_day = day
            self.tasks.resolve(self.commands.prune(local_day=day, now_utc=self.now_utc()),
                               lambda _: None, self._maintenance_failed)
        self._maybe_notice()
        self._maybe_failure_notice()
        if self.busy or self.service.busy:
            return
        try:
            agent, news, enabled, fingerprint = self._capture()
            plan = due_plan(news, self.now_local()) if agent.enabled and enabled else None
        except (TypeError, ValueError):
            return
        if plan is None:
            return
        existing = next((item for item in self.queries.news_snapshot().tasks if item.task_id == plan.task_id), None)
        if existing is not None and existing.state != 'waiting':
            return
        self._begin(plan.task_id, 'auto', plan.planned_date, plan.planned_time, agent, news, fingerprint)

    def run_now(self):
        """用户明确开始一封独立手动来信，连点不会另建任务；不消费当日自动名额。"""
        if self._stopped or self._paused or self.busy or self.service.busy:
            return False
        try:
            agent, news, _, fingerprint = self._capture()
            if not agent.enabled or not news.interests:
                raise ValueError('请先开启智能体并保存至少一个兴趣。')
        except (TypeError, ValueError) as error:
            self.status = str(error)
            self.changed.emit()
            return False
        now = self.now_local()
        self._begin('manual:' + uuid.uuid4().hex, 'manual', now.date().isoformat(), now.strftime('%H:%M'),
                     agent, news, fingerprint)
        return True

    def retry(self, task_id):
        """只在用户明确选择失败记录时沿用任务 ID，待保存报告优先走数据库重试。"""
        if self.pending_report is not None or self._pending_failure is not None:
            return self.retry_save()
        if self._stopped or self._paused or self.busy or self.service.busy:
            return False
        item = next((item for item in self.queries.news_snapshot().tasks if item.task_id == task_id), None)
        if item is None or not retryable_news_task(item, self.now_local()):
            return False
        try:
            agent, news, _, fingerprint = self._capture()
        except (TypeError, ValueError):
            return False
        self._begin(item.task_id, item.kind, item.planned_date, item.planned_time, agent, news, fingerprint, retry=True)
        return True

    def _begin(self, task_id, kind, day, at, agent, news, fingerprint, *, retry=False):
        """先提交领取，再在 Qt 回调中取得网络准入；领取尚未结束时其他唤醒被合并。"""
        self._claim_pending = True
        self._active_kind = kind
        self._invalidated = False
        self._fingerprint = fingerprint
        self.status = '正在确认这封来信的安排…'
        future = self.commands.claim(task_id, kind, fingerprint, day, at, now_utc=self.now_utc(), retry=retry)
        self.tasks.resolve(future, lambda claim: self._claimed(claim, agent, news), self._claim_failed)
        self.changed.emit()

    def _claim_failed(self, error):
        """领取事务失败不启动模型，释放本地占位，后续到期检查仍可安全重试领取。"""
        self._claim_pending = False
        self._active_kind = None
        self.status = '来信安排未保存，暂未请求模型。'
        self.changed.emit()

    def _claimed(self, claim, agent, news):
        """只有仍匹配的已提交 claim 才启动网络，准入竞争退还同一未启动任务。"""
        self._claim_pending = False
        if claim is None:
            self._active_kind = None
            return
        self._claim = claim
        self.sync_settings()
        if self._stopped or self._paused or self._invalidated:
            self._persist_failure('cancelled')
            return
        try:
            self._network_id, future = self.service.news(agent, NewsRequest(news.interests, claim.planned_date),
                                                         self.progress_arrived.emit)
        except AgentBusyError:
            self._transition = True
            self.tasks.resolve(self.commands.release_unstarted(claim), self._released, self._release_failed)
            return
        except Exception as error:
            self._persist_failure(agent_failure_code(error))
            return
        owner = self._network_id
        self.status = '她正在寻找与你兴趣有关的新动态…'
        if self.companion.view.isVisible():
            self._visual.start()
        self._thinking()
        self.tasks.resolve(future, lambda report: self._network_done(owner, report),
                           lambda error: self._network_failed(owner, error))
        self.changed.emit()

    def _released(self, value):
        """未启动退让提交成功，保留数据库 waiting 供下一次窗口内检查。"""
        self._transition = False
        self._claim = None
        self._active_kind = None
        self.status = '正在处理另一项搜索，稍后再安排来信。'
        self.changed.emit()

    def _release_failed(self, error):
        """退让状态保存失败时不请求网络，保留同一凭据供明确的存储重试。"""
        self._transition = False
        self._pending_failure = 'cancelled'
        self.status = '未开始网络，任务状态保存失败，请重试保存。'
        self.changed.emit()

    def _progress(self, progress):
        """只接受当前来信所有者的可见阶段，后台整理不覆盖搜索卡或自动抢焦点。"""
        if not self._stopped and not self._paused and not self._invalidated and progress.request_id == self._network_id:
            if progress.stage != 'streaming':
                self.status = progress.text
                self._thinking()
                self.changed.emit()

    def _thinking(self):
        """仅可见且空闲时给桌宠轻量思考回应；隐藏时不保留视觉轮询。"""
        if self._stopped or self._paused or not self._network_id:
            self._visual.stop()
            return
        if not self.companion.view.isVisible() or self.companion._practicing() or self.agent._busy:
            if not self.companion.view.isVisible():
                self._visual.stop()
            return
        lines = ('我在认真找线索，给你攒一封小小来信。', '小脑袋转呀转，正在核对新鲜事。')
        self.companion.set_agent_feedback('focused', lines[self._visual_index % 2])
        self._visual_index += 1

    def _network_done(self, owner, report):
        """网络结束后保留不可变报告，仅提交数据库；保存失败不会再次调用图。"""
        if owner != self._network_id or self._stopped:
            return
        self._network_id = None
        self._visual.stop()
        try:
            encode_report(report)
        except (TypeError, ValueError, AttributeError):
            # 上游不遵守格式属于确定失败，不能伪装为可重试的数据库故障永久占用准入。
            self._persist_failure('invalid_report')
            return
        self.pending_report = report
        if self._invalidated:
            self.pending_report = None
            self._persist_failure('configuration_changed')
        else:
            self.retry_save()

    def _network_failed(self, owner, error):
        """网络失败或取消进入一次终态保存，不自动重新请求上游。"""
        if owner != self._network_id or self._stopped:
            return
        self._network_id = None
        self._visual.stop()
        self._persist_failure('cancelled' if self._invalidated or self._paused else agent_failure_code(error))

    def retry_save(self):
        """重试已生成报告或失败状态的数据库提交，保持原 claim／attempt 不变。"""
        if self._stopped or self._paused or self.saving or self._claim is None:
            return False
        if self.pending_report is not None:
            self.saving = True
            self.status = '来信已经写好，正在保存…'
            self.tasks.resolve(self.commands.complete(self._claim, self.pending_report, now_utc=self.now_utc()),
                               self._saved, self._save_failed)
            self.changed.emit()
            return True
        if self._pending_failure is not None:
            self._persist_failure(self._pending_failure)
            return True
        return False

    def _saved(self, task):
        """提交成功才清内存结果并申请通知；旧配置被取消时只保留终态，不发完成反馈。"""
        self.saving = False
        self.pending_report = None
        manual = self._active_kind == 'manual'
        self._claim = None
        self._active_kind = None
        self.status = '来信已保存，可以到记忆页查看。' if task and task.report else '这封旧配置来信已取消。'
        if not self.agent._busy:
            self.companion.set_agent_feedback()
        self.changed.emit()
        if task and task.report and not self._invalidated:
            self._maybe_notice(allow_quiet=manual)

    def _save_failed(self, error):
        """保存失败保留报告或失败状态及 claim；明确重试只写数据库，不误报已有正文。"""
        self.saving = False
        self.status = ('来信状态保存失败，请重试保存，不会重新请求模型。' if self._pending_failure is not None
                       else '来信保存失败，内容还在；请重试保存，不会重新请求模型。')
        self.changed.emit()

    def _persist_failure(self, code):
        """异步保存固定失败类别，异常原文不进入持久化；失败后保留数据库重试入口。"""
        if self._claim is None or self._stopped:
            return
        self._pending_failure = code
        self.saving = True
        self.tasks.resolve(self.commands.fail(self._claim, code, now_utc=self.now_utc()),
                           self._failed_saved, self._save_failed)

    def _failed_saved(self, value):
        """终态提交后解除占位但不再运行图，用户可以明确选择重试。"""
        claim = self._claim
        self.saving = False
        self._pending_failure = None
        self._claim = None
        self._active_kind = None
        self.status = '这封来信未完成，已保留状态；可以在来信页明确重试。'
        task = next((item for item in self.queries.news_snapshot().tasks
                     if claim and item.task_id == claim.task_id and item.attempt == claim.attempt), None)
        if value and task and task.state == 'failed':
            # 仅排入本次确已提交的失败；重启恢复状态，不补弹历史失败。
            self._failure_notice = task
            self.status = failure_message(task.error_code)
        if not self.agent._busy:
            self.companion.set_agent_feedback()
        self._maybe_failure_notice()
        self.changed.emit()

    def _maybe_failure_notice(self):
        """空闲可见且不在安静时段时，消费最新失败气泡一次，不覆盖报告卡片。"""
        task = self._failure_notice
        if task is None or not self._eligible_notice(allow_quiet=task.kind == 'manual'):
            return
        try:
            if is_quiet(self._capture()[1], self.now_local()):
                return
        except (TypeError, ValueError):
            return
        current = next((item for item in self.queries.news_snapshot().tasks if item.task_id == task.task_id), None)
        if (current is None or current.deleted_at or current.attempt != task.attempt or current.state != 'failed'
                or (task.kind == 'auto' and task.config_fingerprint != self._fingerprint)):
            self._failure_notice = None
            return
        self._failure_notice = None
        self.companion.set_agent_feedback('pout', '来信暂时没写成。' + failure_message(task.error_code), duration=5)

    def _eligible_notice(self, *, allow_quiet=False):
        """检查实际可见性、练习、阅读占用与安静区间，不预先受理隐藏通知。"""
        if (self._stopped or self._paused or not self.companion.view.isVisible()
                or self.companion._practicing() or not self.agent.can_show_news()):
            return False
        try:
            agent, news, enabled, _ = self._capture()
        except (TypeError, ValueError):
            return False
        return allow_quiet or (agent.enabled and news.enabled and enabled and not is_quiet(news, self.now_local()))

    def _maybe_notice(self, *, allow_quiet=False):
        """只考虑最新已保存一封，旧积压不排队弹出；先提交受理再显示卡片。"""
        if self._notice_pending or not self._eligible_notice(allow_quiet=allow_quiet):
            return
        reports = self.queries.news_snapshot().reports
        if not reports or reports[0].notified_at:
            return
        task = reports[0]
        if task.kind == 'auto' and task.config_fingerprint != self._fingerprint:
            return
        self._notice_pending = True
        self.tasks.resolve(self.commands.accept_notice(task.task_id, now_utc=self.now_utc()),
                           lambda accepted: self._notice_accepted(task, accepted, allow_quiet), self._notice_failed)

    def _notice_accepted(self, task, accepted, allow_quiet):
        """受理提交后再核对 UI 资格，至多显示一次；错过绘制仍可在历史中阅读。"""
        self._notice_pending = False
        current = self.queries.news_snapshot()
        visible_task = next((item for item in current.reports if item.task_id == task.task_id), None)
        if (accepted and visible_task is not None and self._eligible_notice(allow_quiet=allow_quiet)
                and (task.kind != 'auto' or task.config_fingerprint == self._capture()[3])):
            self.agent.show_news_task(task)
        self.changed.emit()

    def _notice_failed(self, error):
        """通知事务失败不展示卡片，后续检查可重试受理而不是重新生成报告。"""
        self._notice_pending = False
        self.status = '来信已保存，通知状态暂未保存，可从记忆页阅读。'
        self.changed.emit()

    def _maintenance_failed(self, error):
        """历史清理失败不重跑网络，下次完成或下一自然日仍会安全重试清理。"""
        self.status = '历史清理暂未完成，已保存来信仍可阅读。'
        self.changed.emit()

    def pause(self):
        """更新退出准备暂停唤醒和视觉；取消自己的在途网络，保留已生成未保存报告。"""
        self._paused = True
        self._timer.stop()
        self._visual.stop()
        if self._network_id:
            self._invalidated = True
            self.service.cancel(self._network_id)

    def discard_for_update(self):
        """仅在更新确认明确放弃后丢弃未提交内容，已受理保存不由此回滚。"""
        self.pause()
        self.pending_report = None
        self._invalidated = True
        if self._claim is not None and not self.saving and self._network_id is None:
            self._persist_failure('cancelled')

    def resume(self):
        """更新准备失败后恢复排期，不自动重跑网络或丢弃待保存结果。"""
        if not self._stopped:
            self._paused = False
            self._timer.start()
            self.sync_settings()

    def shutdown(self):
        """真实退出停止结果接收和计时器，取消所属请求，不关闭其他任务的服务。"""
        if self._stopped:
            return
        self.pause()
        self._stopped = True
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
