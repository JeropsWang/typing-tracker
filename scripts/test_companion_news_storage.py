"""来信真实 SQLite 事务回归；使用内存／临时库和固定时钟，无网络或用户数据。"""
from dataclasses import replace
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.storage.db import init_schema, connect_db
from app.storage.session import DataSession
from app.modules.profile.api import SettingsService
from app.modules.companion.api import AgentReport, SearchSource, AgentConfig, NewsConfig, configuration_fingerprint
from app.modules.companion.news_service import CompanionNewsService
from app.workflows.companion_news import CompanionNewsWorkflow

STAMP = '2026-10-20T01:00:00+00:00'


class NewsStorageTests(unittest.TestCase):
    """防止重复调用、旧尝试覆盖、通知提前和删除后再次消费自动名额。"""
    def setUp(self):
        """装配同一连接上的真实工作单元及模块服务，固定当地日为十月二十日。"""
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        self.repo = DataSession(self.conn)
        self.addCleanup(self.conn.close)
        self.events = []
        self.repo.uow.events.subscribe(self.events.append)
        self.service = CompanionNewsService(self.repo.companion, self.repo.uow, run_id='run-current')
        self.now = datetime(2026, 10, 20, 9, 30)
        self.workflow = CompanionNewsWorkflow(self.repo, SettingsService(self.repo),
                                               run_id='run-current', local_now=lambda: self.now)
        self.settings = dict(companion_agent_enabled='1', companion_enabled='1',
                             **NewsConfig(enabled=True, interests=('人工智能',)).settings_values())
        self.repo.set_settings(self.settings)
        self.events.clear()

    def claim(self, *, task_id='news:2026-10-20', retry=False, day='2026-10-20'):
        """通过事务服务申请固定自动任务，显式重试仍沿用原任务 ID。"""
        return self.service.claim(task_id, 'auto', 'a' * 64, day, '09:00', now_utc=STAMP, retry=retry)

    def report(self):
        """构造可持久化的有界报告，不含凭据或工具会话。"""
        return AgentReport('net-1', '今日来信', '动态见 [1]',
                           (SearchSource('资料', 'https://example.org/news', '摘要'),), STAMP)

    def fingerprint(self):
        """从已提交配置捕获单次版本，后台用独立读取再次核准。"""
        return configuration_fingerprint(AgentConfig.from_settings(self.repo),
                                         NewsConfig.from_values(self.repo.settings()), True)

    def test_duplicate_claim_and_notice_are_once_after_commit(self):
        """同日只领取一次，保存报告后通知受理也只能提交一次。"""
        claim = self.claim()
        self.assertIsNotNone(claim)
        self.assertIsNone(self.claim())
        self.assertEqual(self.service.complete(claim, self.report(), now_utc=STAMP).state, 'completed')
        self.assertTrue(self.service.accept_notice(claim.task_id, now_utc=STAMP))
        self.assertFalse(self.service.accept_notice(claim.task_id, now_utc=STAMP))
        self.assertTrue(self.events)
        self.assertTrue(all(item.topic == 'commit' for item in self.events))

    def test_failed_or_cancelled_task_does_not_retry_without_explicit_action(self):
        """上游失败保留终态，定时器重复检查不能再次发起；明确重试才增加 attempt。"""
        first = self.claim()
        self.assertTrue(self.service.fail(first, 'network', now_utc=STAMP))
        self.assertIsNone(self.claim())
        second = self.claim(retry=True)
        self.assertEqual(second.attempt, 2)
        self.assertFalse(self.service.fail(first, 'cancelled', now_utc=STAMP))
        with self.assertRaises(ValueError):
            self.service.complete(first, self.report(), now_utc=STAMP)
        self.assertEqual(self.service.complete(second, self.report(), now_utc=STAMP).attempt, 2)

    def test_unstarted_busy_race_releases_same_id_without_accepting_old_result(self):
        """仅已知未启动的竞争可退还 waiting；重领凭据使旧完成回调失效。"""
        first = self.claim()
        self.assertTrue(self.service.release_unstarted(first))
        second = self.claim()
        self.assertEqual(second.task_id, first.task_id)
        self.assertEqual(second.attempt, 2)
        with self.assertRaises(ValueError):
            self.service.complete(first, self.report(), now_utc=STAMP)

    def test_delete_report_keeps_daily_dedup_and_hides_content(self):
        """删除清除报告正文但保留去重墓碑，同日不能补发被删除的自动来信。"""
        claim = self.claim()
        self.service.complete(claim, self.report(), now_utc=STAMP)
        self.assertTrue(self.service.forget(claim.task_id, operation_id='forget-1', now_utc=STAMP))
        self.assertTrue(self.service.forget(claim.task_id, operation_id='forget-1', now_utc=STAMP))
        row = self.conn.execute('SELECT report_json,deleted_at FROM companion_news_tasks').fetchone()
        self.assertEqual(row['report_json'], '')
        self.assertTrue(row['deleted_at'])
        self.assertIsNone(self.claim(retry=True))
        self.assertFalse(self.service.accept_notice(claim.task_id, now_utc=STAMP))

    def test_save_failure_preserves_same_attempt_for_retry(self):
        """事务失败不发布完成，去除故障后使用同报告和同 attempt 成功保存。"""
        claim = self.claim()
        self.conn.execute("CREATE TRIGGER fail_news BEFORE UPDATE OF report_json ON companion_news_tasks BEGIN SELECT RAISE(FAIL,'disk full fixture'); END")
        self.conn.commit()
        before = len(self.events)
        with self.assertRaises(sqlite3.DatabaseError):
            self.service.complete(claim, self.report(), now_utc=STAMP)
        self.assertEqual(len(self.events), before)
        self.assertFalse(self.service.accept_notice(claim.task_id, now_utc=STAMP))
        self.conn.execute('DROP TRIGGER fail_news')
        self.conn.commit()
        completed = self.service.complete(claim, self.report(), now_utc=STAMP)
        self.assertEqual(completed.attempt, 1)
        self.assertEqual(self.service.complete(claim, self.report(), now_utc=STAMP), completed)

    def test_recover_marks_old_running_interrupted_without_retry(self):
        """重启只转换旧运行记录，保留报告并禁止自动重试付费请求。"""
        claim = self.claim()
        restarted = CompanionNewsService(self.repo.companion, self.repo.uow, run_id='run-new')
        restarted.recover(now_utc=STAMP)
        self.assertEqual(self.conn.execute('SELECT state FROM companion_news_tasks').fetchone()[0], 'interrupted')
        self.assertIsNone(restarted.claim(claim.task_id, 'auto', 'a' * 64, '2026-10-20', '09:00', now_utc=STAMP))

    def test_workflow_rechecks_due_window_and_configuration_in_transaction(self):
        """展示快照不是资格依据，设置停用或越过宽限时事务拒绝自动领取。"""
        fingerprint = self.fingerprint()
        self.repo.set_setting('companion_enabled', '0')
        self.assertIsNone(self.workflow.claim('news:2026-10-20', 'auto', fingerprint,
                                             '2026-10-20', '09:00', now_utc=STAMP))
        self.repo.set_setting('companion_enabled', '1')
        self.now = datetime(2026, 10, 20, 11, 1)
        self.assertIsNone(self.workflow.claim('news:2026-10-20', 'auto', fingerprint,
                                             '2026-10-20', '09:00', now_utc=STAMP))

    def test_config_change_between_claim_and_complete_cancels_old_auto(self):
        """旧兴趣任务的迟到报告不能在新配置下保存为待推送来信。"""
        claim = self.workflow.claim('news:2026-10-20', 'auto', self.fingerprint(),
                                     '2026-10-20', '09:00', now_utc=STAMP)
        self.repo.set_setting('companion_news_interests', '["游戏"]')
        task = self.workflow.complete(claim, self.report(), now_utc=STAMP)
        self.assertEqual(task.state, 'cancelled')
        self.assertIsNone(task.report)

    def test_settings_save_versions_are_committed_and_retry_idempotent(self):
        """设置和更新时间同事务提交，保存重试不额外增长记忆版本。"""
        self.workflow.save_settings(NewsConfig(interests=('游戏',)).settings_values(),
                                    operation_id='settings-1', now_utc=STAMP)
        self.assertEqual(self.repo.get_setting('companion_news_revision'), '1')
        self.workflow.save_settings(NewsConfig(interests=('游戏',)).settings_values(),
                                    operation_id='settings-1', now_utc=STAMP)
        self.assertEqual(self.repo.get_setting('companion_news_revision'), '1')
        self.assertEqual(self.repo.get_setting('companion_news_updated_at'), STAMP)

    def test_prune_preserves_today_and_running(self):
        """只删除可清理历史，旧在途和今天的自动去重记录必须保留。"""
        old = self.claim(task_id='news:2026-09-01', day='2026-09-01')
        self.service.complete(old, self.report(), now_utc=STAMP)
        self.claim(task_id='news:2026-09-02', day='2026-09-02')
        today = self.claim()
        self.service.complete(today, self.report(), now_utc=STAMP)
        for index in range(105):
            task_id = 'manual:' + format(index, '032x')
            claim = self.service.claim(task_id, 'manual', 'a' * 64, '2026-10-19', '09:00', now_utc=STAMP)
            self.service.fail(claim, 'network', now_utc=STAMP)
        self.service.prune(local_day='2026-10-20', now_utc=STAMP)
        self.assertIsNone(self.repo.companion.get_task('news:2026-09-01'))
        self.assertIsNotNone(self.repo.companion.get_task('news:2026-09-02'))
        self.assertIsNotNone(self.repo.companion.get_task('news:2026-10-20'))
        count = self.conn.execute("SELECT COUNT(*) FROM companion_news_tasks WHERE state!='running'").fetchone()[0]
        self.assertLessEqual(count, 100)

    def test_corrupt_report_cannot_be_accepted_as_notice(self):
        """数据库中损坏的报告只标读取错误，不能显示成已核实的来信。"""
        claim = self.claim()
        self.service.complete(claim, self.report(), now_utc=STAMP)
        self.conn.execute("UPDATE companion_news_tasks SET report_json='broken'")
        self.conn.commit()
        task = self.service.task(claim.task_id)
        self.assertIsNone(task.report)
        self.assertEqual(task.error_code, 'invalid_report')
        self.assertFalse(self.service.accept_notice(claim.task_id, now_utc=STAMP))

    def test_failed_forget_rolls_back_content_and_operation(self):
        """删除提交失败时原报告仍在，稳定删除 ID 可在故障修复后重试。"""
        claim = self.claim()
        self.service.complete(claim, self.report(), now_utc=STAMP)
        self.conn.execute("CREATE TRIGGER fail_forget BEFORE UPDATE OF deleted_at ON companion_news_tasks BEGIN SELECT RAISE(FAIL,'test'); END")
        self.conn.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.service.forget(claim.task_id, operation_id='forget-retry', now_utc=STAMP)
        self.assertEqual(self.service.task(claim.task_id).report, self.report())
        self.conn.execute('DROP TRIGGER fail_forget')
        self.conn.commit()
        self.assertTrue(self.service.forget(claim.task_id, operation_id='forget-retry', now_utc=STAMP))


class NewsMigrationTests(unittest.TestCase):
    """在临时文件验证旧库在线备份和迁移失败回滚，不连接真实用户目录。"""
    def test_versions_zero_one_two_reach_three_without_losing_profile(self):
        """新库和真实形状的版本一／二样本均逐步迁移，既有资料不丢失。"""
        for version in (0, 1, 2):
            with self.subTest(version=version), closing(sqlite3.connect(':memory:')) as conn:
                conn.row_factory = sqlite3.Row
                if version:
                    init_schema(conn)
                    conn.execute("INSERT INTO settings(key,value) VALUES('nickname','保留资料')")
                    conn.execute('DROP TABLE companion_news_tasks')
                    if version == 1:
                        conn.execute('DROP TABLE english_review_schedule')
                    conn.execute(f'PRAGMA user_version={version}')
                    conn.commit()
                init_schema(conn)
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)
                self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='companion_news_tasks'").fetchone())
                if version:
                    self.assertEqual(conn.execute("SELECT value FROM settings WHERE key='nickname'").fetchone()[0], '保留资料')

    def test_v2_backup_and_migration_failure_roll_back(self):
        """版本二迁移到三前备份；DDL 中途失败不能留下半张业务表。"""
        root = Path(__file__).resolve().parents[1] / '.local'
        root.mkdir(exist_ok=True)
        # 连接先于临时目录关闭，Windows 才能清理 WAL 与数据库文件。
        with tempfile.TemporaryDirectory(dir=root) as folder, closing(connect_db(Path(folder) / 'app.db')) as conn:
            init_schema(conn)
            conn.execute('DROP TABLE companion_news_tasks')
            conn.execute('PRAGMA user_version=2')
            conn.commit()
            from app.modules.companion import repository
            actual = repository.migrate_news_schema
            def broken(connection):
                """在真实 DDL 后注入失败，验证外层迁移事务完整回滚。"""
                actual(connection)
                raise OSError('isolated migration failure')
            with patch.object(repository, 'migrate_news_schema', broken), self.assertRaises(OSError):
                init_schema(conn)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='companion_news_tasks'").fetchone())
            backups = list((Path(folder) / 'migration-backups').glob('*.db'))
            self.assertEqual(len(backups), 1)
            with closing(sqlite3.connect(backups[0])) as backup:
                self.assertEqual(backup.execute('PRAGMA user_version').fetchone()[0], 2)
            init_schema(conn)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 3)


if __name__ == '__main__':
    unittest.main()
