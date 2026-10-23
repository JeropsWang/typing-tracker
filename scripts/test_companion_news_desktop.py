"""真实 ApplicationWorker 与 Qt 来信协调回归；隔离数据库、确定模型，无外网请求。"""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import threading
import unittest

from PySide6.QtCore import QObject, QCoreApplication, QEvent
from PySide6.QtWidgets import QWidget
from test_ui_workflow import APP, BALANCE, pump_until
from test_companion_agent import FakeModel, FakeSearch, SOURCE
from app.bootstrap.application import DesktopApplication
from app.bootstrap.features import DesktopQueries
from app.modules.companion.api import NewsConfig, AgentConfig, configuration_fingerprint, AgentBusyError
from app.integrations.companion_agent.service import CompanionAgentService
from app.ui.companion.news_controller import CompanionNewsController

STAMP = '2026-10-20T01:30:00+00:00'


class PetHost(QObject):
    """最小真实 Qt 宿主，只提供现有桌宠可见性与反馈边界，不模拟排期或事务。"""
    def __init__(self, queries):
        """持有独立可见控件和只读查询，记录完成卡片出现时的提交状态。"""
        super().__init__()
        self.presenter = queries
        self.view = QWidget()
        self.view.show()
        self.practicing = False
        self.feedback = []

    def _practicing(self):
        """返回本例显式练习开关，不读取统计或输入正文。"""
        return self.practicing

    def set_agent_feedback(self, *args, **kwargs):
        """记录视觉请求，线程与提交顺序由协调器测试验证。"""
        self.feedback.append((threading.get_ident(), args))


class AgentHost:
    """复用真实网络服务，仅记录现有卡片边界被调用时的数据库脱离快照。"""
    def __init__(self, pet, service):
        """保留当前搜索卡占用与已展示任务 ID，不持有 SQLite。"""
        self.service, self.pet = service, pet
        self._busy = False
        self.occupied = False
        self.shown = []

    def can_show_news(self):
        """只有没有搜索／阅读卡片时才接受自动来信卡片。"""
        return not self._busy and not self.occupied

    def show_news_task(self, task):
        """检查模型中的通知标志已提交后记录卡片展示，不请求网络。"""
        saved = next(item for item in self.pet.presenter.news_snapshot().tasks if item.task_id == task.task_id)
        self.shown.append((task.task_id, bool(saved.notified_at), threading.get_ident()))
        self.occupied = True


class NewsDesktopTests(unittest.TestCase):
    """防止重复网络、先展示后保存、旧结果回传和恢复重放。"""
    def setUp(self):
        """每例使用独立文件库、真实工作线程及可注入当地和 UTC 时钟。"""
        root = Path(__file__).resolve().parents[1] / '.local'
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.local_now = datetime(2026, 10, 20, 9, 30)
        self.application = DesktopApplication(self.temp.name, BALANCE, {},
                                              news_local_now=lambda: self.local_now,
                                              news_utc_now=lambda: STAMP)
        self.queries = DesktopQueries(self.application)
        self.model_calls = []
        calls = self.model_calls
        class CountedModel(FakeModel):
            """记录实际首次图轮次，工具与模型循环仍由真实 LangGraph 执行。"""
            def turn(self, messages, tools, cancel, on_text=lambda _: None):
                """只在 user 数据首轮计为一次任务，不把工具续接算作再次请求任务。"""
                if messages[-1]['role'] == 'user':
                    calls.append(1)
                return super().turn(messages, tools, cancel, on_text)
        self.service = CompanionAgentService(model_factory=CountedModel, search_factory=FakeSearch)
        self.pet = PetHost(self.queries)
        self.agent = AgentHost(self.pet, self.service)
        self.controller = CompanionNewsController(self.pet, self.agent, self.application.news_commands,
                                                   self.queries, now_local=lambda: self.local_now,
                                                   now_utc=lambda: STAMP)

    def tearDown(self):
        """先作废网络接收与定时器，再关闭工作线程和 Qt 宿主，最后删除隔离数据。"""
        self.controller.shutdown()
        self.service.close()
        self.application.close()
        self.pet.view.hide()
        self.pet.view.deleteLater()
        self.pet.deleteLater()
        APP.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temp.cleanup()

    def enable(self):
        """通过真实异步设置用例开启明确兴趣，不直接操作 UI 草稿。"""
        values = dict(companion_agent_enabled='1', companion_agent_provider='local',
                      **NewsConfig(enabled=True, interests=('人工智能',)).settings_values())
        self.application.news_commands.save_settings(values, operation_id='enable', now_utc=STAMP).result(5)
        self.controller.sync_settings()
        APP.processEvents()

    def wait_report(self):
        """处理真实 Qt 队列直至报告已提交且协调器处理完完成回调。"""
        return pump_until(lambda: bool(self.queries.news_snapshot().reports) and not self.controller.saving, timeout=10)

    def test_no_due_tick_performs_no_sql_or_network(self):
        """默认关闭的五十次唤醒不向工作线程排数据库写入或启动模型。"""
        sql = []
        self.application.worker.submit(lambda context: context['repo']._conn.set_trace_callback(sql.append)).result(5)
        for _ in range(50):
            self.controller.tick()
        APP.processEvents()
        self.assertEqual(sql, [])
        self.assertEqual(self.model_calls, [])

    def test_fifty_ticks_claim_one_daily_job(self):
        """并发唤醒合并为一次领取及一次图执行，后续当日唤醒继续去重。"""
        self.enable()
        for _ in range(50):
            self.controller.tick()
        self.assertTrue(self.wait_report())
        for _ in range(10):
            self.controller.tick()
        APP.processEvents()
        self.assertEqual(len(self.model_calls), 1)
        self.assertEqual(len(self.queries.news_snapshot().reports), 1)

    def test_committed_models_precede_ui_notice(self):
        """通知在已提交读模型和 Qt 主线程之后出现，数据库线程不操作控件。"""
        self.enable()
        self.controller.tick()
        self.assertTrue(pump_until(lambda: bool(self.agent.shown), timeout=10))
        self.assertTrue(self.agent.shown[0][1])
        self.assertEqual(self.agent.shown[0][2], threading.get_ident())
        self.assertTrue(all(item[0] == threading.get_ident() for item in self.pet.feedback))

    def fail_saving(self):
        """只阻断报告完成更新，保持原 claim 可由相同报告重试保存。"""
        self.application.worker.submit(lambda context: context['repo']._conn.execute(
            "CREATE TRIGGER block_news BEFORE UPDATE OF report_json ON companion_news_tasks WHEN NEW.state='completed' BEGIN SELECT RAISE(FAIL,'isolated save failure'); END")).result(5)

    def test_pending_save_retry_does_not_call_model_again(self):
        """报告保存失败保持内存结果，重试只提交数据库命令，不重跑付费网络。"""
        self.enable()
        self.fail_saving()
        self.controller.tick()
        self.assertTrue(pump_until(lambda: self.controller.pending_report is not None and not self.controller.saving, timeout=10))
        self.assertFalse(self.queries.news_snapshot().reports)
        self.assertFalse(self.agent.shown)
        self.application.worker.submit(lambda context: context['repo']._conn.execute('DROP TRIGGER block_news')).result(5)
        self.controller.retry_save()
        self.assertTrue(self.wait_report())
        self.assertEqual(len(self.model_calls), 1)

    def test_config_change_discards_late_auto_result(self):
        """配置更改使旧来信失效，并在底层 I/O 结束前继续占用共享准入。"""
        self.enable()
        entered, release = threading.Event(), threading.Event()
        class BlockingSearch(FakeSearch):
            """使用事件保留在途工具，观察取消后的真实准入。"""
            def search(self, topic, cancel):
                """暂不响应取消，直到测试释放后由图检查点拒绝结果。"""
                entered.set()
                release.wait(5)
                return (SOURCE,)
        self.service.search_factory = BlockingSearch
        self.addCleanup(release.set)
        self.controller.tick()
        self.assertTrue(pump_until(entered.is_set, timeout=10))
        self.application.news_commands.save_settings(NewsConfig(enabled=True, interests=('游戏',)).settings_values(),
                                                     operation_id='new-interests', now_utc=STAMP).result(5)
        self.controller.sync_settings()
        self.assertTrue(self.service.busy)
        release.set()
        self.assertTrue(pump_until(lambda: self.queries.news_snapshot().tasks[0].state == 'cancelled', timeout=10))
        self.assertFalse(self.queries.news_snapshot().reports)
        self.assertFalse(self.agent.shown)

    def test_busy_race_releases_unstarted_same_id(self):
        """领取提交前后出现搜索竞争时还原 waiting，待空闲再用同一个每日 ID。"""
        self.enable()
        original = self.service.news
        first = [True]
        def race(*args, **kwargs):
            """仅模拟原子领取后的准入竞争，不替代后续图和存储。"""
            if first[0]:
                first[0] = False
                raise AgentBusyError('竞争')
            return original(*args, **kwargs)
        self.service.news = race
        self.controller.tick()
        self.assertTrue(pump_until(lambda: bool(self.queries.news_snapshot().tasks) and self.queries.news_snapshot().tasks[0].state == 'waiting', timeout=10))
        self.assertEqual(self.model_calls, [])
        self.controller.tick()
        self.assertTrue(self.wait_report())
        self.assertEqual(self.queries.news_snapshot().reports[0].task_id, 'news:2026-10-20')
        self.assertEqual(len(self.model_calls), 1)

    def test_update_pause_resume_preserves_pending_save(self):
        """更新准备与恢复不丢已生成未保存报告，也不再次请求模型。"""
        self.enable()
        self.fail_saving()
        self.controller.run_now()
        self.assertTrue(pump_until(lambda: self.controller.pending_report is not None and not self.controller.saving, timeout=10))
        self.controller.pause()
        self.application.prepare_update_exit().result(5)
        self.application.cancel_update_exit()
        self.controller.resume()
        self.assertIsNotNone(self.controller.pending_report)
        self.application.worker.submit(lambda context: context['repo']._conn.execute('DROP TRIGGER block_news')).result(5)
        self.controller.retry_save()
        self.assertTrue(self.wait_report())
        self.assertEqual(len(self.model_calls), 1)

    def test_restart_marks_running_interrupted_without_network(self):
        """新进程启动只恢复任务终态，不因到期而自动重放上次在途请求。"""
        self.enable()
        values = self.queries.settings()
        fingerprint = configuration_fingerprint(AgentConfig.from_settings(self.queries), NewsConfig.from_values(values), True)
        self.application.news_commands.claim('news:2026-10-20', 'auto', fingerprint,
                                             '2026-10-20', '09:00', now_utc=STAMP).result(5)
        self.controller.shutdown()
        self.application.close()
        self.application = DesktopApplication(self.temp.name, BALANCE, {}, news_local_now=lambda: self.local_now,
                                              news_utc_now=lambda: STAMP)
        self.assertEqual(self.application.models.news_snapshot().tasks[0].state, 'interrupted')
        self.assertEqual(self.model_calls, [])

    def test_hidden_pet_stops_visual_timer_without_stopping_schedule(self):
        """隐藏只停止视觉节拍，后台排期继续运行，不在隐藏桌宠上浪费动效轮询。"""
        self.enable()
        self.controller._network_id = 'visual-owner'
        self.controller._visual.start()
        self.pet.view.hide()
        APP.processEvents()
        self.assertFalse(self.controller._visual.isActive())
        self.assertTrue(self.controller._timer.isActive())

    def test_completion_prunes_history_without_restarting_app(self):
        """长期驻留每次完成也执行保留策略，不等重启才限制百封历史。"""
        import uuid
        from app.modules.companion.api import AgentReport
        self.enable()
        fingerprint = self.controller._capture()[3]
        def seed(context):
            """在隔离工作线程批量准备一百条旧终态，不调用模型或触碰用户数据。"""
            workflow = context['news']
            with context['repo'].transaction():
                for _ in range(100):
                    claim = workflow.service.claim('manual:' + uuid.uuid4().hex, 'manual', fingerprint,
                        '2026-10-20', '09:00', now_utc='2026-10-20T01:00:00+00:00')
                    report = AgentReport('old', '旧报告', '旧内容 [1]', (SOURCE,), '2026-10-20T01:00:00+00:00')
                    workflow.service.complete(claim, report, now_utc='2026-10-20T01:00:00+00:00')
        self.application.worker.submit(seed).result(5)
        self.assertTrue(self.controller.run_now())
        self.assertTrue(pump_until(lambda: len(self.model_calls) == 1 and not self.controller.busy))
        self.assertTrue(pump_until(lambda: len(self.queries.news_snapshot().tasks) <= 100))

    def test_terminal_save_failure_has_ui_retry(self):
        """终态写失败也能从配置页明确重试保存，解除忙碌而不请求模型。"""
        from app.ui.companion.agent_settings import AgentSettingsDialog
        self.enable()
        fingerprint = self.controller._capture()[3]
        self.controller._claim = self.application.news_commands.claim('news:2026-10-20', 'auto', fingerprint,
            '2026-10-20', '09:00', now_utc=STAMP).result(5)
        self.application.worker.submit(lambda context: context['repo']._conn.execute(
            "CREATE TRIGGER reject_terminal BEFORE UPDATE OF state ON companion_news_tasks "
            "WHEN NEW.state='failed' BEGIN SELECT RAISE(FAIL,'test'); END")).result(5)
        self.controller._persist_failure('network')
        self.assertTrue(pump_until(lambda: not self.controller.saving))
        dialog = AgentSettingsDialog(self.queries, news=self.controller)
        self.addCleanup(dialog.deleteLater)
        dialog._refresh_news()
        self.assertTrue(dialog.news_panel.retry_button.isEnabled())
        self.application.worker.submit(lambda context: context['repo']._conn.execute('DROP TRIGGER reject_terminal')).result(5)
        dialog.news_panel._retry()
        self.assertTrue(pump_until(lambda: not self.controller.busy))
        self.assertEqual(len(self.model_calls), 0)

    def test_invalid_report_becomes_terminal_instead_of_save_loop(self):
        """模型超限正文是确定校验失败，应保存 invalid_report，不锁死在付费重试前。"""
        from app.modules.companion.api import AgentTurn
        class OversizeModel(FakeModel):
            """返回有引用但超过持久化上限的模型夹具，不访问真实端点。"""
            def answer(self):
                """模拟不遵守正文限额的上游，验证接收边界会拒绝。"""
                return AgentTurn('长' * 12001 + ' [1]')
        self.enable()
        self.service.close()
        self.service = CompanionAgentService(model_factory=OversizeModel, search_factory=FakeSearch)
        self.agent.service = self.controller.service = self.service
        self.assertTrue(self.controller.run_now())
        self.assertTrue(pump_until(lambda: bool(self.queries.news_snapshot().tasks) and not self.controller.busy))
        task = self.queries.news_snapshot().tasks[0]
        self.assertEqual(task.error_code, 'invalid_report')
        self.assertIsNone(self.controller.pending_report)
        self.assertEqual(task.state, 'failed')


if __name__ == '__main__':
    unittest.main()
