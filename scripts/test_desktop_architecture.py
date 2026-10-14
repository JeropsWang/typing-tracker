"""Real desktop worker + Qt: saves are acknowledged before UI state advances."""
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from PySide6.QtCore import QCoreApplication, QEvent
from test_ui_workflow import APP, BALANCE, pump_until
from app.bootstrap.application import DesktopApplication
from app.bootstrap.features import DesktopQueries
from app.integrations.ai.api import AIService
from app.theme.theme_manager import ThemeManager
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui.presenters import PracticeState

ROOT=Path(__file__).resolve().parents[1]

class DesktopWorkflowTests(unittest.TestCase):
    """真实 ApplicationWorker 和 Qt 异步提交的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        (ROOT/'.local').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local')
        self.application=DesktopApplication(self.temp.name,BALANCE,{})
        self.queries=DesktopQueries(self.application)
        self.application.set_settings(dict(ai_backend='openai',ai_base_url='http://unused',ai_model='test')).result(5)
        self.theme=ThemeManager(APP,Path(self.temp.name),self.queries.get_setting,self.queries.set_setting)
        self.theme.apply(self.theme.current_id(),persist=False)
        self.window=MainWindow(self.application.counter,self.queries,BALANCE,
            checkin=self.application.checkin,rewards=self.application.rewards,
            achievements=self.application.achievements,challenge=self.application.practice,
            ai_service=AIService(self.queries),theme_manager=self.theme,
            data_dir=Path(self.temp.name),application=self.application)
        self.theme.register_window(self.window)
        self.window.show();APP.processEvents()
    def tearDown(self):
        """关闭本用例持有的对象并清理临时资源，下一例从独立状态开始。"""
        self.window._challenge_page._cancel_generation()
        self.window._english_page._cancel_request()
        self.window._companion.shutdown()
        self.application.close()
        self.window.hide();self.window.deleteLater()
        APP.processEvents();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
        self.temp.cleanup()
    def grant_pass(self):
        """通过隔离应用线程添加测试训练券，不修改真实用户库存。"""
        self.application.worker.submit(lambda context:context['repo'].add_reward('ai_pass',1,'test')).result(5)
        APP.processEvents()
    def test_practice_result_is_committed_before_completion_and_reaction(self):
        """验证成绩提交在完成展示和桌宠反应之前。"""
        page=self.window._challenge_page
        self.window._tabs.setCurrentWidget(page)
        page._start();page._finish(page._current_text(),page._current_text())
        self.assertTrue(pump_until(lambda:page._presenter.state==PracticeState.COMPLETED))
        self.assertEqual(len(self.application.models.get_recent_challenges()),1)
        self.assertEqual(self.window._companion.runtime.sample().state,'proud')
    def test_english_attempt_is_confirmed_after_async_save(self):
        """验证英语题目只在异步写入成功后确认。"""
        page=self.window._english_page
        self.window._tabs.setCurrentWidget(page)
        page._start_spelling()
        session=page.service.session
        page.spelling.answer.setText(session.current.word)
        page._submit_spelling()
        self.assertTrue(pump_until(lambda:session.result is not None))
        self.assertEqual(page.service.summary(page.library.deck)['attempts'],1)
        self.assertTrue(session.result['independent'])

    def test_english_schedule_failure_retries_same_attempt_before_correction(self):
        """验证排期写入失败沿用作答 ID 重试，成功前不进入纠正。"""
        page = self.window._english_page
        self.window._tabs.setCurrentWidget(page)
        page._start_spelling()
        session = page.service.session
        self.application.worker.submit(lambda context: context['repo']._conn.execute(
            "CREATE TRIGGER reject_review BEFORE INSERT ON english_review_schedule BEGIN SELECT RAISE(FAIL,'test'); END;"
        )).result(5)
        page.spelling.answer.setText('incorrect')
        page._submit_spelling()
        prepared = dict(session._prepared)
        self.assertFalse(page.library.deck_combo.isEnabled())
        self.assertTrue(pump_until(lambda: not page._spelling_saving))
        self.assertIsNone(session.result)
        self.assertFalse(session.correcting)
        self.assertEqual(page.service.summary(page.library.deck)['attempts'], 0)
        self.assertEqual(page.service.review_plan(page.library.deck)['due_count'], 0)
        self.application.worker.submit(lambda context: context['repo']._conn.execute('DROP TRIGGER reject_review')).result(5)
        page._submit_spelling()
        self.assertTrue(pump_until(lambda: session.result is not None))
        self.assertEqual(session.result, prepared)
        self.assertTrue(session.correcting)
        self.assertEqual(page.service.summary(page.library.deck)['attempts'], 1)
        self.assertEqual(page.service.review_plan(page.library.deck)['due_count'], 1)
        page.spelling.answer.setText(session.current.word)
        page._correct()
        self.assertEqual(page.service.summary(page.library.deck)['attempts'], 1)
    def test_settings_commit_updates_cached_profile(self):
        """验证设置提交成功后更新只读资料模型。"""
        dialog=SettingsDialog(self.queries,BALANCE,theme_manager=self.theme,data_dir=self.temp.name)
        dialog._nick_edit.setText('异步保存')
        dialog.accept()
        self.assertTrue(pump_until(lambda:dialog._closed))
        self.assertEqual(self.queries.get_setting('nickname'),'异步保存')
        dialog.deleteLater()

    def test_companion_agent_config_failure_preserves_draft_then_retries(self):
        """验证智能体设置写入失败保留草稿，随后可以原值重试。"""
        from app.ui.companion.agent_settings import AgentSettingsDialog
        dialog = AgentSettingsDialog(self.queries)
        self.addCleanup(dialog.deleteLater)
        dialog.enabled.setChecked(True)
        dialog.api_key.setText('isolated-test-key')
        self.application.worker.submit(lambda context:context['repo']._conn.execute(
            "CREATE TRIGGER reject_agent_config BEFORE INSERT ON settings WHEN NEW.key='companion_agent_enabled' BEGIN SELECT RAISE(ABORT,'test failure'); END"
        )).result(5)
        dialog.save_config()
        self.assertTrue(pump_until(lambda:not dialog.saving))
        self.assertIn('失败', dialog.feedback.text())
        self.assertIsNone(self.queries.get_setting('companion_agent_api_key'))
        self.assertEqual(dialog.api_key.text(), 'isolated-test-key')
        self.application.worker.submit(lambda context:context['repo']._conn.execute('DROP TRIGGER reject_agent_config')).result(5)
        dialog.save_config()
        self.assertTrue(pump_until(lambda:dialog.result() == 1))
        self.assertEqual(self.queries.get_setting('companion_agent_api_key'), 'isolated-test-key')
        self.assertEqual(self.queries.get_setting('companion_agent_enabled'), '1')

    def test_companion_network_runs_off_qt_thread_and_delivers_report(self):
        """验证模型/搜索执行在 Qt 线程外，报告排队回主线程。"""
        from app.integrations.companion_agent import CompanionAgentService
        from app.modules.companion.api import SearchSource, AgentTurn, AgentToolCall
        main_thread = threading.get_ident()
        calls = []
        class Search:
            """本用例搜索替身，记录查询并按设定返回来源或失败。"""
            def __init__(self, _):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                pass
            def validate(self):
                """提供本例配置校验替身，可按用例成功或拒绝，不访问真实服务。"""
                pass
            def search(self, topic, cancel):
                """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
                calls.append(threading.get_ident())
                return (SearchSource('资料', 'https://example.org', '公开摘录'),)
        class Model:
            """本用例模型能力替身，响应或失败由当前测试控制。"""
            def __init__(self, _):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                pass
            def validate(self):
                """提供本例配置校验替身，可按用例成功或拒绝，不访问真实服务。"""
                pass
            def turn(self, messages, tools, cancel, on_text=lambda _: None):
                """返回预定原生模型轮次，验证工具行动/观察续接，不调用真实模型。"""
                calls.append(threading.get_ident())
                if messages[-1]['role'] != 'tool':
                    return AgentTurn(tool_calls=(AgentToolCall('search-1', 'web_search', '{"query":"公开话题"}'),))
                on_text('流式整理正文')
                return AgentTurn('整理完成 [1]')
        agent = self.window._companion.agent
        agent.service.close()
        agent.service = CompanionAgentService(model_factory=Model, search_factory=Search)
        self.application.set_settings({'companion_agent_enabled':'1'}).result(5)
        agent.search('公开话题')
        self.assertTrue(pump_until(lambda:agent.report is not None, timeout=10))
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(value != main_thread for value in calls))
        self.assertEqual(agent.card.body.toPlainText().splitlines()[0], '整理完成 [1]')

    def test_companion_connection_test_does_not_save_draft(self):
        """验证桌宠连接检查不把未保存配置写入数据库。"""
        from app.integrations.companion_agent.setup import AgentSetupService
        from app.ui.companion.agent_settings import AgentSettingsDialog
        threads = []
        class Model:
            """本用例模型能力替身，响应或失败由当前测试控制。"""
            def __init__(self, config):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                self.config = config
            def test_connection(self, cancel):
                """提供本用例草稿连接检查的模拟能力，按测试安排返回结果或失败。"""
                threads.append(threading.get_ident()); return 'OK'
        setup = AgentSetupService(model_factory=Model)
        self.addCleanup(setup.close)
        before = self.queries.settings()
        dialog = AgentSettingsDialog(self.queries, setup=setup)
        self.addCleanup(dialog.deleteLater)
        dialog.provider.setCurrentIndex(dialog.provider.findData('local'))
        dialog.model.setText('draft-model')
        dialog.test_model()
        self.assertTrue(pump_until(lambda:dialog._job is None))
        self.assertIn('连接成功', dialog.model_status.text())
        self.assertNotEqual(threads[0], threading.get_ident())
        self.assertEqual(self.queries.settings(), before)
    def test_cancelled_passage_holds_gate_until_network_ends(self):
        """验证已取消范文任务在网络结束前仍占共享准入。"""
        self.grant_pass()
        started=threading.Event();release=threading.Event()
        def generate(*_):
            """按当前用例模拟生成成功/失败，便于检查保存而不产生模型费用。"""
            started.set();release.wait(5)
            return True,'不会保存的正文'
        page=self.window._challenge_page
        self.window._tabs.setCurrentWidget(page);page._topic_edit.setText('test')
        with patch.object(AIService,'generate',side_effect=generate):
            page._ai_generate();self.assertTrue(started.wait(2))
            self.window._tabs.setCurrentWidget(self.window._english_page)
            english=self.window._english_page
            english._generate()
            self.assertIn('已有 AI',english.sentences.status.text())
            release.set()
            self.assertTrue(pump_until(lambda:page._gen_thread is None))
        self.assertEqual(self.queries.list_ai_texts(),[])
        self.assertEqual(self.queries.count_ai_passes(),1)
    def test_failed_material_save_retries_without_second_model_call(self):
        """验证材料保存重试复用已生成正文，不再次调用模型。"""
        self.grant_pass()
        self.application.worker.submit(lambda context:context['repo']._conn.execute(
            "CREATE TRIGGER fail_material BEFORE INSERT ON ai_texts BEGIN SELECT RAISE(ABORT,'disk full'); END")).result(5)
        page=self.window._challenge_page
        self.window._tabs.setCurrentWidget(page);page._topic_edit.setText('test')
        with patch.object(AIService,'generate',return_value=(True,'有效的测试正文')) as generate:
            page._ai_generate()
            self.assertTrue(pump_until(lambda:page._pending_material is not None and not page._material_saving))
            self.assertEqual(self.queries.count_ai_passes(),1)
            self.application.worker.submit(lambda context:context['repo']._conn.execute('DROP TRIGGER fail_material')).result(5)
            page._ai_generate()
            self.assertTrue(pump_until(lambda:len(self.queries.list_ai_texts())==1))
            APP.processEvents()
            self.assertEqual(generate.call_count,1)
        self.assertEqual(self.queries.count_ai_passes(),0)
    def test_refreshes_use_no_sql_and_save_failure_is_visible(self):
        """验证 UI 刷新只读模型且实际保存失败可见。"""
        traces=[]
        self.application.worker.submit(lambda context:context['repo']._conn.set_trace_callback(traces.append)).result(5)
        for _ in range(5):
            self.window.refresh();self.window._companion._tick()
        self.assertEqual(traces,[])
        self.application.counter.handle_char('letter')
        def fail(context):
            """抛出本例预设失败，验证服务不会错误提交或提前庆祝。"""
            context['repo']._conn.execute("CREATE TRIGGER fail_stats BEFORE INSERT ON daily_stats BEGIN SELECT RAISE(ABORT,'full'); END")
        self.application.worker.submit(fail).result(5)
        future=self.application.flush()
        with self.assertRaises(Exception):future.result(5)
        self.assertTrue(pump_until(lambda:self.window._dashboard._save_status.text()=='保存失败'))
        self.application.worker.submit(lambda context:context['repo']._conn.execute('DROP TRIGGER fail_stats')).result(5)
        self.application.flush().result(5)
        self.assertTrue(pump_until(lambda:self.window._dashboard._save_status.text().startswith('已保存')))

if __name__=='__main__':unittest.main()
