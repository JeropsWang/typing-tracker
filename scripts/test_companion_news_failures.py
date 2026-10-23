"""来信故障分类、状态恢复和提醒回归；隔离 Qt/SQLite 与传输，不请求真实模型。"""
from dataclasses import replace
from datetime import timedelta
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from test_companion_agent import CONFIG, FakeModel, FakeSearch, Response
import test_companion_news_desktop as desktop
from test_ui_workflow import APP, pump_until
from app.integrations.companion_agent.model import CompanionModel
from app.integrations.companion_agent.search import AgentError, WebSearch
from app.integrations.companion_agent.service import CompanionAgentService
from app.modules.companion.api import NewsRequest, news_status, AgentRunLimits, AgentTurn, AgentToolCall
from app.ui.companion.news_settings import NewsSettingsPanel


class FailureTransportTests(unittest.TestCase):
    """验证类型化错误越过模型、搜索和真实图边界后仍能定位失败阶段。"""

    def test_legacy_error_keeps_text_and_has_safe_defaults(self):
        """旧构造方式和异常文字兼容，未分类错误具有明确的未知类别。"""
        error = AgentError('已有提示')
        self.assertEqual(str(error), '已有提示')
        self.assertEqual(getattr(error, 'stage', None), 'agent')
        self.assertEqual(getattr(error, 'code', None), 'unknown')

    def test_model_authentication_is_identified_without_response_body(self):
        """HTTP 拒绝访问归于模型鉴权，不把响应正文或 URL 保存到错误对象。"""
        def opener(request, timeout):
            """模拟模型端点的拒绝访问，不使用真实凭据。"""
            raise HTTPError('https://fixture.invalid/private', 401, 'SECRET-RESPONSE', {}, None)
        model = CompanionModel(CONFIG, opener=opener)
        with self.assertRaises(AgentError) as caught:
            model.turn([dict(role='user', content='测试')], [], threading.Event())
        self.assertEqual(getattr(caught.exception, 'stage', None), 'model')
        self.assertEqual(getattr(caught.exception, 'code', None), 'auth')
        self.assertNotIn('SECRET', str(caught.exception))

    def test_search_connection_is_identified(self):
        """搜索连接失败保持自己的阶段，不被来信统称为模型出错。"""
        def opener(request, timeout):
            """仅模拟搜索的连接错误。"""
            raise URLError('SECRET-UPSTREAM')
        search = WebSearch(replace(CONFIG, search_provider='searxng', search_url='http://127.0.0.1:8080'), opener=opener)
        with self.assertRaises(AgentError) as caught:
            search.search('公开资料', threading.Event())
        self.assertEqual(getattr(caught.exception, 'stage', None), 'search')
        self.assertEqual(getattr(caught.exception, 'code', None), 'connection')
        self.assertNotIn('SECRET', str(caught.exception))

    def test_public_search_fallback_keeps_transport_failure_category(self):
        """所有 RSS 备用入口连接失败时保留连接类别，不能声称只是没有资料。"""
        def opener(request, timeout):
            """两个备用搜索端点都在本地夹具中失败。"""
            raise URLError('fixture unavailable')
        search = WebSearch(replace(CONFIG, search_provider='web-lite'), opener=opener)
        with self.assertRaises(AgentError) as caught:
            search.search('公开资料', threading.Event())
        self.assertEqual(getattr(caught.exception, 'code', None), 'connection')

    def test_local_model_has_bounded_cold_start_budget_without_changing_remote(self):
        """本机模型允许较慢冷启动，远端仍沿用25秒传输超时，不做全局放宽。"""
        observed = []
        def opener(request, timeout):
            """记录实际传输预算并立即返回有效回复，不进行真实等待。"""
            observed.append(timeout)
            return Response(dict(choices=[dict(finish_reason='stop', message=dict(content='OK'))]))
        CompanionModel(CONFIG, opener=opener).test_connection(threading.Event())
        remote = replace(CONFIG, provider='deepseek', base_url='https://api.deepseek.com/v1',
                         model='deepseek-chat', api_key='fixture-key')
        CompanionModel(remote, opener=opener).test_connection(threading.Event())
        self.assertEqual(observed, [120, 25])

    def test_rate_limit_timeout_protocol_and_unknown_are_safe(self):
        """不同传输失败有稳定类别；未知异常经服务脱敏，不能回显私密正文。"""
        for failure, expected in [(HTTPError('https://fixture.invalid', 429, '', {}, None), 'rate_limit'),
                                  (TimeoutError(), 'timeout'), (ValueError('SECRET'), 'protocol')]:
            with self.subTest(expected=expected):
                def opener(request, timeout):
                    """提供本次故障，不发生真实 HTTP 请求。"""
                    raise failure
                with self.assertRaises(AgentError) as caught:
                    CompanionModel(CONFIG, opener=opener).turn([], [], threading.Event())
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(caught.exception.stage, 'model')
                self.assertNotIn('SECRET', str(caught.exception))
        class UnknownModel(FakeModel):
            """模拟来自未识别适配器的内部异常。"""
            def turn(self, *args, **kwargs):
                """抛出带敏感哨兵的异常，确认服务端固定脱敏。"""
                raise RuntimeError('SECRET-URL-KEY-BODY')
        service = CompanionAgentService(model_factory=UnknownModel, search_factory=FakeSearch)
        self.addCleanup(service.close)
        _, future = service.news(CONFIG, NewsRequest(('公开资料',), '2026-10-23'), lambda _: None)
        with self.assertRaises(AgentError) as caught:
            future.result(15)
        self.assertEqual(caught.exception.code, 'unknown')
        self.assertNotIn('SECRET', str(caught.exception))

    def test_mcp_observation_preserves_search_failure_for_terminal_news(self):
        """工具先把错误反馈给模型，最终无来源失败仍保留搜索连接类别。"""
        class FailedSearch(FakeSearch):
            """模拟失败的搜索适配器，不接触网络。"""
            def search(self, topic, cancel):
                """附上阶段属性，验证现有图是否会丢失它们。"""
                error = AgentError('受控搜索暂时不可用')
                error.stage, error.code = 'search', 'connection'
                raise error
        service = CompanionAgentService(model_factory=FakeModel, search_factory=FailedSearch)
        self.addCleanup(service.close)
        _, future = service.news(CONFIG, NewsRequest(('公开资料',), '2026-10-23'), lambda _: None)
        with self.assertRaises(AgentError) as caught:
            future.result(15)
        self.assertEqual(getattr(caught.exception, 'stage', None), 'search')
        self.assertEqual(getattr(caught.exception, 'code', None), 'connection')

    def test_tool_deadline_keeps_timeout_instead_of_no_sources(self):
        """工具在返回时越过截止时间，终态应保持超时而不是无来源。"""
        from app.integrations.companion_agent.graph import run_news
        clock = {'now': 0.0}
        class SlowSearch(FakeSearch):
            """以确定时钟模拟搜索期间耗尽本次总预算。"""
            def search(self, topic, cancel):
                """让图的下一取消检查精确命中截止，不真的睡眠。"""
                clock['now'] = 2.0
                return ()
        with patch('app.integrations.companion_agent.graph.time', SimpleNamespace(monotonic=lambda: clock['now'])):
            with self.assertRaises(AgentError) as caught:
                run_news('timeout', NewsRequest(('资料',), '2026-10-23'), FakeModel(), SlowSearch(),
                         threading.Event(), lambda _: None, limits=AgentRunLimits(seconds=1))
        self.assertEqual(caught.exception.code, 'timeout')

    def test_search_budget_does_not_overwrite_real_auth_failure(self):
        """模型耗尽搜索次数时保留最后真实上游鉴权原因，而非预算观察的未知错误。"""
        from app.integrations.companion_agent.graph import run_news
        class RepeatingModel(FakeModel):
            """不断改写查询，模拟模型观察错误后继续尝试至限额。"""
            def __init__(self):
                """每轮使用新的调用ID和查询，避免命中重复行动缓存。"""
                self.count = 0
            def turn(self, *args, **kwargs):
                """按独立轮次返回合法、不同的搜索工具请求。"""
                self.count += 1
                return AgentTurn(tool_calls=(AgentToolCall(str(self.count), 'web_search',
                    '{"query":"query ' + str(self.count) + '"}'),))
        class AuthSearch(FakeSearch):
            """上游搜索始终鉴权失败，不访问外网。"""
            def search(self, topic, cancel):
                """提供明确类型化的真实适配器故障。"""
                raise AgentError('fixture auth', stage='search', code='auth')
        with self.assertRaises(AgentError) as caught:
            run_news('budget', NewsRequest(('资料',), '2026-10-23'), RepeatingModel(), AuthSearch(),
                     threading.Event(), lambda _: None)
        self.assertEqual((caught.exception.stage, caught.exception.code), ('search', 'auth'))


class FailureDesktopTests(unittest.TestCase):
    """通过正式数据库线程与 Qt 回调验证状态和提交后的失败提醒。"""

    def setUp(self):
        """复用隔离装配夹具，每例独立文件库，避免修改真实产品数据。"""
        self.f = desktop.NewsDesktopTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def fail_task(self, code='model.auth'):
        """在真实领取后提交指定失败，保持事务与展示快照的真实顺序。"""
        f = self.f
        f.enable()
        agent, news, _, fingerprint = f.controller._capture()
        claim = f.application.news_commands.claim('news:2026-10-20', 'auto', fingerprint,
            '2026-10-20', '09:00', now_utc='2026-10-20T01:30:00+00:00').result(5)
        f.controller._claim, f.controller._active_kind = claim, 'auto'
        f.controller._persist_failure(code)
        self.assertTrue(pump_until(lambda: not f.controller.busy, timeout=10))
        return f.queries.news_snapshot().tasks[0]

    def test_classification_is_committed_before_failure_feedback(self):
        """失败码提交后显示一次气泡，连续唤醒不再次生成或提醒。"""
        f = self.f
        task = self.fail_task()
        self.assertEqual(task.error_code, 'model.auth')
        warnings = [args for _, args in f.pet.feedback if args and args[0] == 'pout']
        self.assertEqual(len(warnings), 1)
        for _ in range(50):
            f.controller.tick()
        self.assertEqual(len([a for _, a in f.pet.feedback if a and a[0] == 'pout']), 1)
        self.assertFalse(f.queries.news_snapshot().reports)
        self.assertFalse(f.model_calls)

    def test_enabled_settings_never_claim_schedule_is_disabled(self):
        """开启后即使控制器尚未执行网络，配置页也展示真实排期。"""
        f = self.f
        f.enable()
        snapshot = f.queries.news_snapshot()
        panel = NewsSettingsPanel(snapshot.config, snapshot, now_local=lambda: f.local_now)
        self.addCleanup(panel.deleteLater)
        panel.set_snapshot(snapshot, status=f.controller.status)
        self.assertNotIn('尚未开启', panel.status.text())

    def test_settings_schedule_respects_disabled_agent(self):
        """正式配置页采用已保存智能体开关，不能一边暂停一边承诺下次时间。"""
        from app.ui.companion.agent_settings import AgentSettingsDialog
        f = self.f
        f.enable()
        f.application.news_commands.save_settings({'companion_agent_enabled': '0'}, operation_id='disable-agent',
            now_utc='2026-10-20T01:30:01+00:00').result(5)
        f.controller.sync_settings()
        dialog = AgentSettingsDialog(f.queries, news=f.controller)
        self.addCleanup(dialog.deleteLater)
        dialog._refresh_news()
        self.assertEqual(dialog.news_panel.schedule.text(), '排期暂停')

    def test_persisted_failure_and_expired_retry_survive_reload(self):
        """重新读取昨日失败，显示中文原因并引导新手动来信，不提供过期自动重试。"""
        f = self.f
        self.fail_task()
        f.local_now += timedelta(days=1)
        snapshot = f.queries.news_snapshot()
        panel = NewsSettingsPanel(snapshot.config, snapshot, now_local=lambda: f.local_now)
        self.addCleanup(panel.deleteLater)
        panel.set_snapshot(snapshot)
        self.assertFalse(panel.retry_button.isEnabled())
        self.assertIn('鉴权', panel.status.text())
        self.assertIn('现在', panel.status.text())

    def test_hidden_failure_waits_until_visible(self):
        """隐藏时不弹气泡，恢复后提醒一次，失败不进入报告历史。"""
        f = self.f
        f.pet.view.hide()
        self.fail_task('search.connection')
        self.assertFalse([a for _, a in f.pet.feedback if a and a[0] == 'pout'])
        f.pet.view.show()
        f.controller.tick()
        self.assertEqual(len([a for _, a in f.pet.feedback if a and a[0] == 'pout']), 1)

    def test_quiet_practice_and_reader_delay_the_same_failure(self):
        """安静／练习／阅读占用均延后同一失败，解除后只提醒一次。"""
        f = self.f
        f.pet.view.hide()
        self.fail_task('search.connection')
        f.local_now = f.local_now.replace(hour=22, minute=30)
        f.pet.view.show()
        f.controller.tick()
        f.local_now += timedelta(hours=10)
        f.pet.practicing = True
        f.controller.tick()
        f.pet.practicing = False
        f.agent.occupied = True
        f.controller.tick()
        self.assertFalse([a for _, a in f.pet.feedback if a and a[0] == 'pout'])
        f.agent.occupied = False
        f.controller.tick()
        f.controller.tick()
        self.assertEqual(len([a for _, a in f.pet.feedback if a and a[0] == 'pout']), 1)

    def test_cancelled_task_has_no_failure_bubble(self):
        """主动取消记录保留重试能力，不作为服务故障弹出。"""
        self.fail_task('cancelled')
        self.f.controller.tick()
        self.assertFalse([a for _, a in self.f.pet.feedback if a and a[0] == 'pout'])

    def test_untrusted_code_is_not_persisted(self):
        """白名单外的异常正文只能回退通用码，不能进入任务表。"""
        task = self.fail_task('SECRET-https://private.invalid/key')
        self.assertEqual(task.error_code, 'network')

    def test_deleted_automatic_task_keeps_next_schedule_on_tomorrow(self):
        """删除仍保留今日名额，展示也不能重新承诺今天会自动准备。"""
        f = self.f
        task = self.fail_task()
        f.application.news_commands.forget(task.task_id, operation_id='forget-test',
            now_utc='2026-10-20T01:30:01+00:00').result(5)
        view = news_status(f.queries.news_snapshot(), f.local_now)
        self.assertIn('10-21', view.schedule)

    def test_failed_state_save_has_no_premature_bubble_or_report_claim(self):
        """失败记录自身写入失败时，不声称已有报告，也不提前发失败通知。"""
        f = self.f
        f.application.worker.submit(lambda context: context['repo']._conn.execute(
            "CREATE TRIGGER reject_failure BEFORE UPDATE OF state ON companion_news_tasks "
            "WHEN NEW.state='failed' BEGIN SELECT RAISE(FAIL,'fixture'); END")).result(5)
        self.fail_task_without_waiting()
        self.assertTrue(pump_until(lambda: not f.controller.saving))
        self.assertIn('状态保存失败', f.controller.status)
        self.assertFalse([a for _, a in f.pet.feedback if a and a[0] == 'pout'])
        f.application.worker.submit(lambda context: context['repo']._conn.execute('DROP TRIGGER reject_failure')).result(5)
        self.assertTrue(f.controller.retry_save())
        self.assertTrue(pump_until(lambda: not f.controller.busy))
        self.assertEqual(len([a for _, a in f.pet.feedback if a and a[0] == 'pout']), 1)

    def fail_task_without_waiting(self):
        """为失败事务测试创建真实 claim，只启动终态保存而不等待 busy 清除。"""
        f = self.f
        f.enable()
        fingerprint = f.controller._capture()[3]
        claim = f.application.news_commands.claim('news:2026-10-20', 'auto', fingerprint,
            '2026-10-20', '09:00', now_utc='2026-10-20T01:30:00+00:00').result(5)
        f.controller._claim, f.controller._active_kind = claim, 'auto'
        f.controller._persist_failure('model.auth')


if __name__ == '__main__':
    unittest.main()
