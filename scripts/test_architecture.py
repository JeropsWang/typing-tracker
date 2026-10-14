"""Transactional failures, recovery, worker ownership and cache/admission contracts."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.storage.db import connect_db, init_schema
from app.storage.session import DataSession
from app.modules.tracking.api import TrackingService
from app.modules.growth.api import CheckinService, RewardService, AchievementService
from app.modules.practice.api import ChallengeService
from app.english.service import EnglishService
from app.workflows.checkpoint import CheckpointWriter
from app.workflows.material import save_passage
from app.bootstrap.application import DesktopApplication
from app.bootstrap.read_models import ReadModels
from app.integrations.ai.api import AIService, GenerationGate, AIBusyError

BALANCE=json.loads((ROOT/'config/balance.json').read_text(encoding='utf8'))

class Clock:
    """可控墙上/单调时钟夹具，用于日切、排期和持续时间边界。"""
    def __init__(self):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        self.value=datetime(2026,10,13,12,0)
    def now(self):
        """返回可控墙上时间，供应用日/日切边界验证。"""
        return self.value
    def monotonic(self):
        """返回可控单调秒数，供持续计时与取消边界验证。"""
        return 1.0

class TransactionTests(unittest.TestCase):
    """事务、恢复、缓存及线程边界的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        self.conn=sqlite3.connect(':memory:')
        self.conn.row_factory=sqlite3.Row
        self.addCleanup(self.conn.close)
        init_schema(self.conn)
        self.repo=DataSession(self.conn)
        self.clock=Clock()
        self.engine=TrackingService(self.repo,self.repo.get_setting,BALANCE,clock=self.clock)
    def type(self,count):
        """注入测试输入数值来推进计数版本，不记录真实键盘输入。"""
        for _ in range(count): self.engine.handle_char('letter')
    def test_checkpoint_failure_rolls_back_stats_rewards_and_progress(self):
        """验证检查点失败共同回滚统计、奖励和结算高水位。"""
        self.type(1000)
        with patch.object(self.repo,'upsert_minutes',side_effect=sqlite3.OperationalError('disk full')):
            with self.assertRaises(sqlite3.Error): self.engine.flush()
        self.assertIsNone(self.repo.get_daily('2026-10-13'))
        self.assertEqual(self.repo.get_exp(),0)
        self.assertEqual(self.repo.get_lifetime()['total_active_minutes'],0)
        self.assertIsNotNone(self.engine.prepare_checkpoint())
        self.engine.flush()
        self.engine.flush()
        self.assertEqual(self.repo.get_exp(),5)
        self.assertEqual(self.repo.get_lifetime()['total_active_minutes'],1)
    def test_commit_without_acknowledgment_replays_without_duplicate_rewards(self):
        """验证提交已成功但内存未确认时，重放不会重复发奖。"""
        self.type(1000)
        checkpoint=self.engine.prepare_checkpoint()
        writer=CheckpointWriter(self.repo,BALANCE)
        writer.save(checkpoint)
        writer.save(checkpoint)
        self.assertEqual(self.repo.get_exp(),5)
        self.engine.flush()
        self.assertEqual(self.repo.get_exp(),5)
    def test_input_after_capture_remains_dirty_after_ack(self):
        """验证检查点捕获后新输入在旧版本确认后仍为脏数据。"""
        self.type(10)
        checkpoint=self.engine.prepare_checkpoint()
        self.type(5)
        CheckpointWriter(self.repo,BALANCE).save(checkpoint)
        self.engine.acknowledge(checkpoint)
        self.assertIsNotNone(self.engine.prepare_checkpoint())
        self.engine.flush()
        self.assertEqual(self.repo.get_daily('2026-10-13')['typed_chars'],15)
        self.assertEqual(self.repo.get_lifetime()['total_active_minutes'],1)
    def test_input_event_rolls_day_without_polling(self):
        """验证输入事件自身处理日切，不依赖 UI 轮询。"""
        self.clock.value=datetime(2026,10,13,3,59,59)
        self.type(3)
        self.clock.value=datetime(2026,10,13,4,0)
        self.type(2)
        self.engine.flush()
        self.assertEqual(self.repo.get_daily('2026-10-12')['typed_chars'],3)
        self.assertEqual(self.repo.get_daily('2026-10-13')['typed_chars'],2)
    def test_failed_old_day_survives_rollover_and_retry(self):
        """验证旧日保存失败跨日后仍保留并能提交重试。"""
        self.clock.value=datetime(2026,10,13,3,59,59)
        self.type(1000)
        with patch.object(self.repo,'upsert_minutes',side_effect=sqlite3.OperationalError('busy')):
            with self.assertRaises(sqlite3.Error): self.engine.flush()
        self.clock.value=datetime(2026,10,13,4,0)
        self.type(1000)
        self.engine.flush()
        self.assertEqual(self.repo.get_exp(),10)
        self.assertEqual(self.repo.get_lifetime()['total_typed'],2000)
        self.assertEqual(len(self.conn.execute('SELECT * FROM growth_daily').fetchall()),2)
    def test_idle_flush_executes_no_sql(self):
        """验证无新统计版本时保存检查不执行 SQL。"""
        self.type(1); self.engine.flush()
        statements=[]; self.conn.set_trace_callback(statements.append)
        for _ in range(4): self.engine.flush()
        self.assertEqual(statements,[])
    def test_snapshots_are_immutable_and_detached(self):
        """验证统计快照不可变且与内部可变数据脱离。"""
        self.type(2)
        snap=self.engine.immutable_snapshot()
        self.type(1)
        self.assertEqual(snap.typed,2)
        self.assertIsInstance(snap.minutes_series,tuple)
        with self.assertRaises(AttributeError): snap.typed=50
    def test_quantity_consumption_spends_one_unit(self):
        """验证多数量库存每次只消费一份。"""
        self.repo.add_reward('ai_pass',3,'test')
        self.assertTrue(self.repo.use_reward('ai_pass'))
        self.assertEqual(self.repo.count_ai_passes(),2)
    def test_makeup_requires_card_and_rolls_back_on_reward_failure(self):
        """验证补签需要库存且奖励失败共同回滚卡片消费。"""
        service=CheckinService(self.repo,BALANCE,clock=self.clock)
        self.assertIsNone(service.apply_makeup_card('2026-10-12','2026-10-13'))
        self.assertFalse(self.repo.has_checkin('2026-10-12'))
        self.repo.add_reward('makeup_card',1,'test')
        with patch.object(self.repo,'add_exp',side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.Error): service.apply_makeup_card('2026-10-12','2026-10-13')
        self.assertFalse(self.repo.has_checkin('2026-10-12'))
        self.assertEqual(RewardService(self.repo,BALANCE).count('makeup_card'),1)
    def test_boost_failure_returns_consumed_card(self):
        """验证加成事务失败回滚已经消费的卡片。"""
        self.repo.add_reward('exp_boost',1,'test')
        with patch.object(self.repo,'set_setting',side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.Error): RewardService(self.repo,BALANCE).use_exp_boost()
        self.assertEqual(RewardService(self.repo,BALANCE).count('exp_boost'),1)
    def test_claim_failure_does_not_lose_or_duplicate_rewards(self):
        """验证成就领取失败不丢失也不重复发奖。"""
        self.repo.unlock_achievement('test','2026-10-13')
        service=AchievementService(self.repo,BALANCE,{'chars':[dict(code='test',rewards=[dict(kind='exp',qty=10)])]})
        with patch.object(self.repo,'set_claimed',side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.Error): service.claim('test')
        self.assertEqual(self.repo.get_exp(),0)
        self.assertEqual(self.repo.get_achievement('test')['claimed'],0)
        service.claim('test')
        service.claim('test')
        self.assertEqual(self.repo.get_exp(),10)
    def test_practice_completion_is_atomic_and_idempotent(self):
        """验证训练纪录与奖励原子提交，重复完成幂等。"""
        service=ChallengeService(self.repo,clock=self.clock)
        result=dict(typed_chars=20,errors=0,tw=20,accuracy=1,base=10,score_points=10000,elapsed_seconds=10)
        with patch.object(self.repo,'add_exp',side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.Error): service.record('test',result,BALANCE,operation_id='run1')
        self.assertEqual(self.repo.get_recent_challenges(),[])
        one=service.record('test',result,BALANCE,operation_id='run1')
        two=service.record('test',result,BALANCE,operation_id='run1')
        self.assertEqual(one,two)
        self.assertEqual(len(self.repo.get_recent_challenges()),1)
        self.assertEqual(self.repo.get_exp(),10)
    def test_passage_failure_keeps_ticket_and_retry_saves_once(self):
        """验证材料保存失败回滚券消费，原 ID 重试仅保存一次。"""
        self.repo.add_reward('ai_pass',1,'test')
        with patch.object(self.repo,'add_ai_text',side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.Error): save_passage(self.repo,BALANCE,'cn','test','正文',operation_id='ai1')
        self.assertEqual(self.repo.count_ai_passes(),1)
        one=save_passage(self.repo,BALANCE,'cn','test','正文',operation_id='ai1')
        two=save_passage(self.repo,BALANCE,'cn','test','正文',operation_id='ai1')
        self.assertEqual(one,two)
        self.assertEqual(self.repo.count_ai_passes(),0)
        self.assertEqual(len(self.repo.list_ai_texts()),1)
    def test_english_failure_keeps_ticket(self):
        """验证英语材料事务失败不丢训练券。"""
        self.repo.add_reward('ai_pass',1,'test')
        service=EnglishService(self.repo)
        word=service.catalog.load('cet4')[0].word
        sentences=[dict(text=f'I really like {word} today.',translation='我今天喜欢这个词。')]
        with patch.object(service.storage,'save_sentences',side_effect=sqlite3.OperationalError('full')):
            with self.assertRaises(sqlite3.Error): service.save_generated('cet4','test',[word],sentences,BALANCE,operation_id='en1')
        self.assertEqual(self.repo.count_ai_passes(),1)
        service.save_generated('cet4','test',[word],sentences,BALANCE,operation_id='en1')
        service.save_generated('cet4','test',[word],sentences,BALANCE,operation_id='en1')
        self.assertEqual(self.repo.count_ai_passes(),0)
        self.assertEqual(len(service.sentence_history('cet4')),1)
    def test_notifications_only_follow_successful_outer_commit(self):
        """验证业务通知只在最外层事务成功提交后发布。"""
        events=[]; self.repo.uow.events.subscribe(events.append)
        with self.assertRaises(RuntimeError):
            with self.repo.transaction():
                self.repo.add_exp(3)
                raise RuntimeError('rollback')
        self.assertEqual(events,[])
        with self.repo.transaction():
            self.repo.add_exp(3)
            self.assertEqual(events,[])
        self.assertEqual(len(events),1)
    def test_subscriber_failure_does_not_undo_commit(self):
        """验证订阅回调失败不撤销已提交业务事务。"""
        def bad(_):
            """在当前步骤故意注入失败，用于断言回滚/失败保留。"""
            raise ValueError('subscriber')
        self.repo.uow.events.subscribe(bad)
        with self.assertLogs(level='ERROR'): self.repo.add_exp(3)
        self.assertEqual(self.repo.get_exp(),3)

class FileRecoveryTests(unittest.TestCase):
    """事务、恢复、缓存及线程边界的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        (ROOT/'.local').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'app.db'
    def test_migration_keeps_legacy_reward_high_water_and_creates_backup(self):
        """验证迁移保留旧奖励结算高水位并创建原库备份。"""
        conn=connect_db(self.path)
        conn.executescript((ROOT/'app/storage/schema.sql').read_text(encoding='utf8'))
        conn.execute("INSERT INTO daily_stats(date,typed_chars,valid_chars,total_tw) VALUES('2026-10-13',1000,1000,1000)")
        conn.executemany('INSERT INTO settings VALUES(?,?)',[('typing_exp_date','2026-10-13'),('typing_exp_blocks','2'),('typing_exp_today','10')])
        conn.execute('UPDATE lifetime SET total_typed=1000,total_tw=1000,total_exp=10')
        conn.commit(); init_schema(conn)
        self.assertTrue(list(self.path.parent.glob('migration-backups/*.db')))
        repo=DataSession(conn); engine=TrackingService(repo,repo.get_setting,BALANCE,clock=Clock())
        for _ in range(1000): engine.handle_char('letter')
        engine.flush()
        self.assertEqual(repo.get_exp(),10)
        conn.close()
    def test_failed_migration_is_atomic_and_keeps_original_database(self):
        """验证数据库迁移失败完整回滚并保留原库。"""
        conn=connect_db(self.path)
        conn.execute('CREATE TABLE original(value TEXT)');conn.execute("INSERT INTO original VALUES('keep')");conn.commit()
        def fail(c,s):
            """抛出本例预设失败，验证服务不会错误提交或提前庆祝。"""
            c.execute('CREATE TABLE partial(value TEXT)')
            raise RuntimeError('migration failure')
        with patch('app.storage.db._execute_schema',side_effect=fail):
            with self.assertRaises(RuntimeError): init_schema(conn)
        self.assertEqual(conn.execute('SELECT * FROM original').fetchone()[0],'keep')
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='partial'").fetchone())
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],0)
        conn.close()
    def test_killed_process_recovers_complete_committed_state(self):
        """用隔离进程验证异常终止后恢复最后完整提交状态。"""
        for commit in (False,True):
            path=self.path.parent/f'crash-{commit}.db'
            code="from app.storage.db import connect_db,init_schema; import os; c=connect_db(%r); init_schema(c); c.execute('BEGIN IMMEDIATE'); c.execute('UPDATE lifetime SET total_typed=1000,total_exp=5'); c.execute(\"INSERT INTO daily_stats(date,typed_chars,valid_chars) VALUES('2026-10-13',1000,1000)\"); %s; os._exit(0)"%(str(path),'c.commit()' if commit else 'None')
            result=subprocess.run([sys.executable,'-B','-c',code],cwd=ROOT,timeout=15)
            self.assertEqual(result.returncode,0)
            conn=connect_db(path)
            row=conn.execute('SELECT total_typed,total_exp FROM lifetime').fetchone()
            self.assertEqual(tuple(row),(1000,5) if commit else (0,0))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM daily_stats').fetchone()[0],int(commit))
            conn.close()
    def test_operation_replay_survives_connection_reopen(self):
        """验证数据库重新打开后稳定操作 ID 仍返回原结果。"""
        conn=connect_db(self.path);init_schema(conn);repo=DataSession(conn)
        repo.add_reward('ai_pass',1,'test')
        save_passage(repo,BALANCE,'cn','test','正文',operation_id='request')
        conn.close()
        conn=connect_db(self.path);repo=DataSession(conn)
        save_passage(repo,BALANCE,'cn','test','正文',operation_id='request')
        self.assertEqual(len(repo.list_ai_texts()),1)
        self.assertEqual(repo.count_ai_passes(),0)
        conn.close()

class AdmissionCacheTests(unittest.TestCase):
    """事务、恢复、缓存及线程边界的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def test_cancellation_does_not_release_a_running_request(self):
        """验证取消结果不提前释放仍在传输的生成准入。"""
        gate=GenerationGate();lease=gate.acquire('first')
        lease.result_finished()
        with self.assertRaises(AIBusyError): gate.acquire('second')
        lease.network_finished()
        second=gate.acquire('second');second.network_finished()
        self.assertTrue(gate.busy)
        second.result_finished();self.assertFalse(gate.busy)
    def test_configuration_snapshots_share_generation_gate(self):
        """验证模型配置快照共享同一个生成准入门。"""
        ai=AIService(config=dict(backend='off'))
        self.assertIs(ai.generation_gate,ai.snapshot().generation_gate)
    def test_cached_rows_are_detached_and_change_versions_invalidate_reports(self):
        """验证查询返回副本且数据版本变化会失效报表缓存。"""
        models=ReadModels()
        row=dict(date='2026-10-13',typed_chars=2,deleted_chars=0,valid_chars=2,total_tw=2,active_minutes=1)
        models.replace({'daily_stats':[row]})
        summary=models.get_summary('2026-01-01','2026-12-31');summary['tw']=999
        self.assertEqual(models.get_summary('2026-01-01','2026-12-31')['tw'],2)
        models.replace({'daily_stats':[dict(row,total_tw=3)]})
        self.assertEqual(models.get_summary('2026-01-01','2026-12-31')['tw'],3)

class WorkerTests(unittest.TestCase):
    """事务、恢复、缓存及线程边界的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        (ROOT/'.local').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.local');self.addCleanup(self.temp.cleanup)
        self.app=DesktopApplication(self.temp.name,BALANCE,{})
        self.addCleanup(self.app.close)
    def test_sqlite_connection_and_commands_are_owned_by_one_worker(self):
        """验证连接创建、命令执行和关闭均归同一应用线程。"""
        ids=[]
        self.app.worker.submit(lambda context:context['repo']._conn.set_trace_callback(lambda _:ids.append(threading.get_ident()))).result(5)
        self.app.set_setting('nickname','new').result(5)
        self.app.counter.handle_ime('你好');self.app.flush().result(5)
        self.assertTrue(ids)
        self.assertNotIn(threading.get_ident(),ids)
        self.assertEqual(len(set(ids)),1)
        before=len(ids)
        for _ in range(10): self.app.models.get_setting('nickname');self.app.models.get_exp()
        self.assertEqual(len(ids),before)
    def test_pending_command_is_async_and_failed_command_does_not_wedge_queue(self):
        """验证写命令异步返回，单项失败不堵塞工作队列。"""
        entered=threading.Event();release=threading.Event()
        def hold(_):
            """用同步事件保留在途任务，让用例检查取消期间准入仍被占用。"""
            entered.set();release.wait(5)
        self.app.worker.submit(hold);self.assertTrue(entered.wait(5))
        future=self.app.set_setting('nickname','after')
        self.assertFalse(future.done());self.assertIsNone(self.app.models.get_setting('nickname'))
        release.set();future.result(5)
        self.assertEqual(self.app.models.get_setting('nickname'),'after')
        future=self.app.worker.submit(lambda _:1/0)
        with self.assertRaises(ZeroDivisionError):future.result(5)
        self.app.set_setting('nickname','still running').result(5)
        self.assertEqual(self.app.models.get_setting('nickname'),'still running')

if __name__=='__main__':unittest.main()
