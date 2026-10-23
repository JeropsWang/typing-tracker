"""跨 profile 与 companion 的来信用例；事务内重新核准设置，网络由外部服务执行。"""
from ..modules.companion.api import (AgentConfig, NewsConfig, CompanionNewsService,
                                     configuration_fingerprint, due_plan)


class CompanionNewsWorkflow:
    """ApplicationWorker 内的配置／任务协调者，生产 UI 只能通过异步代理调用。"""
    def __init__(self, session, settings_service, *, run_id, local_now):
        """注入内部数据会话、既有设置提交能力和可替换的当地时钟。"""
        self.session, self.settings_service, self.local_now = session, settings_service, local_now
        self.service = CompanionNewsService(session.companion, session.uow, run_id=run_id)

    def __getattr__(self, name):
        """仅转发不涉及配置资格的明确事务命令，不开放内部仓储或连接。"""
        if name in {'release_unstarted', 'fail', 'accept_notice', 'forget', 'recover', 'prune'}:
            return getattr(self.service, name)
        raise AttributeError(name)

    def _configuration(self):
        """在所属事务线程捕获整批当前配置与非凭据指纹，不使用展示缓存授权。"""
        values = self.session.settings()
        news = NewsConfig.from_values(values)
        agent = AgentConfig.from_settings(self.session)
        enabled = values.get('companion_enabled', '1') != '0'
        return agent, news, enabled, configuration_fingerprint(agent, news, enabled)

    def claim(self, task_id, kind, config_fingerprint, planned_date, planned_time, *, now_utc, retry=False):
        """当前设置与日期合格才提交领取，显式手动任务不受安静区间或自动开关限制。"""
        with self.session.transaction():
            agent, news, enabled, current = self._configuration()
            if current != config_fingerprint or not agent.enabled or not news.interests:
                return None
            if kind == 'auto':
                if not enabled or not news.enabled:
                    return None
                if retry:
                    # 明确重试允许越过两小时窗口，但仍只能重试当日已存在的自动任务。
                    if planned_date != self.local_now().date().isoformat() or self.service.task(task_id) is None:
                        return None
                else:
                    plan = due_plan(news, self.local_now())
                    if plan is None or (task_id, planned_date, planned_time) != (plan.task_id, plan.planned_date, plan.planned_time):
                        return None
            return self.service.claim(task_id, kind, current, planned_date, planned_time,
                                       now_utc=now_utc, retry=retry)

    def complete(self, claim, report, *, now_utc):
        """旧自动配置结果标为取消；已完成历史保留，不将迟到数据升级为当前记忆。"""
        with self.session.transaction():
            if claim.kind == 'auto':
                try:
                    agent, news, enabled, current = self._configuration()
                    valid = agent.enabled and news.enabled and enabled and current == claim.config_fingerprint
                except ValueError:
                    valid = False
                if not valid:
                    self.fail(claim, 'configuration_changed', now_utc=now_utc)
                    return self.service.task(claim.task_id)
            task = self.service.complete(claim, report, now_utc=now_utc)
            self.service.prune(local_day=self.local_now().date().isoformat(), now_utc=now_utc,
                               keep_task_id=claim.task_id)
            return task

    def fail(self, claim, error_code, *, now_utc):
        """终态与历史保留一起提交，长期驻留不依赖重启才执行百条／三十日策略。"""
        with self.session.transaction():
            changed = self.service.fail(claim, error_code, now_utc=now_utc)
            self.service.prune(local_day=self.local_now().date().isoformat(), now_utc=now_utc,
                               keep_task_id=claim.task_id)
            return changed

    def save_settings(self, values, *, operation_id, now_utc):
        """原子保存智能体／兴趣草稿及记忆版本，操作结果仅含版本元信息，不含 Key。"""
        values = dict(values)
        if any(not key.startswith(('companion_news_', 'companion_agent_')) for key in values):
            raise ValueError('此入口仅保存桌宠智能体与来信配置。')
        for key in ('companion_news_revision', 'companion_news_updated_at'):
            values.pop(key, None)
        from ..modules.companion.api import validate_news_utc
        validate_news_utc(now_utc)
        def action():
            """幂等事务中规范兴趣并提交设置，失败回滚更新时间与版本。"""
            merged = dict(self.session.settings(), **values)
            config = NewsConfig.from_values(merged)
            try:
                revision = max(0, int(self.session.get_setting('companion_news_revision', '0'))) + 1
            except (TypeError, ValueError):
                revision = 1
            values.update(config.settings_values(), companion_news_revision=str(revision),
                          companion_news_updated_at=now_utc)
            self.settings_service.save(values)
            self.session.uow.changed('companion')
            return dict(revision=revision, updated_at=now_utc)
        return self.session.operation('companion.settings', operation_id, action)
