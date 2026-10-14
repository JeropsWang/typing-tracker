"""统计重启与 AI 工作线程回归：使用隔离数据库和本地 HTTP 服务。

运行：python -B -m unittest discover -s scripts -p test_regressions.py -v
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.engine import StatsEngine
from app.services.ai_service import AIService
from app.storage.db import init_schema
from app.storage.session import DataSession as Repository

BALANCE = json.loads((ROOT / 'config' / 'balance.json').read_text(encoding='utf-8'))


class DatabaseCase(unittest.TestCase):
    """独立真实 SQLite 连接，避免成就等测试的造数污染当日统计。"""

    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        init_schema(self.conn)
        self.repo = Repository(self.conn)
        self.repo.set_setting('day_start_hour', '4')


class StatsRestartTests(DatabaseCase):
    """固定事件时间，验证重启、同分钟续写、千字进度与日切边界。"""

    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        super().setUp()
        self.now = datetime(2026, 10, 7, 12, 0)
        case = self

        class Clock(datetime):
            """可控墙上/单调时钟夹具，用于日切、排期和持续时间边界。"""
            @classmethod
            def now(cls):
                """返回可控墙上时间，供应用日/日切边界验证。"""
                return case.now

        clock = patch('app.core.engine.datetime', Clock)
        clock.start()
        self.addCleanup(clock.stop)

    def engine(self):
        """用隔离数据库和可控时钟装配统计引擎，供恢复用例复用。"""
        return StatsEngine(self.repo, self.repo.get_setting, BALANCE)

    def type_chars(self, engine, count):
        """注入指定数量的测试字符，验证统计恢复和经验结算。"""
        for _ in range(count):
            engine.handle_char('letter')

    def test_restart_preserves_daily_and_minute_counters(self):
        """验证重启恢复当日与分钟统计基线。"""
        engine = self.engine()
        self.type_chars(engine, 12)
        engine.handle_ime('你好')
        engine.handle_delete()
        engine.flush()

        restarted = self.engine()
        self.assertEqual(restarted.snapshot()['typed'], 14)
        self.assertEqual(restarted.snapshot()['deleted'], 1)
        self.assertEqual(restarted.snapshot()['tw'], 16)
        self.assertEqual(restarted.minute_series(), [('12:00', 16)])
        restarted.flush()
        daily = self.repo.get_daily('2026-10-07')
        self.assertEqual(daily['valid_chars'], 13)
        self.assertEqual(daily['accuracy'], 13 / 14)
        self.assertEqual(daily['avg_tw'], 16)
        self.assertEqual(self.repo.get_lifetime()['total_active_minutes'], 1)

    def test_restart_appends_to_existing_minute_without_double_counting(self):
        """验证重启同一分钟续写原行，不重复增加活跃分钟。"""
        engine = self.engine()
        self.type_chars(engine, 1000)
        engine.flush()
        restarted = self.engine()
        self.type_chars(restarted, 1)
        restarted.flush()
        restarted.flush()
        daily = self.repo.get_daily('2026-10-07')
        self.assertEqual(daily['typed_chars'], 1001)
        self.assertEqual(restarted.minute_series(), [('12:00', 1001)])
        self.assertEqual(self.repo.get_lifetime()['total_typed'], 1001)
        self.assertEqual(self.repo.get_lifetime()['total_active_minutes'], 1)
        self.assertEqual(self.repo.get_exp(), 5)

    def test_restart_counts_a_new_minute_once(self):
        """验证重启进入新分钟只增加一次活跃计数。"""
        engine = self.engine()
        self.type_chars(engine, 12)
        engine.flush()
        self.now = datetime(2026, 10, 7, 12, 1)
        restarted = self.engine()
        self.type_chars(restarted, 3)
        restarted.flush()
        restarted.flush()
        self.assertEqual(self.repo.get_daily('2026-10-07')['active_minutes'], 2)
        self.assertEqual(self.repo.get_daily('2026-10-07')['avg_tw'], 7.5)
        self.assertEqual(restarted.minute_series(), [('12:00', 12), ('12:01', 3)])
        self.assertEqual(self.repo.get_lifetime()['total_active_minutes'], 2)

    def test_restart_retains_partial_thousand_progress(self):
        """验证重启保留未满千字的结算进度。"""
        engine = self.engine()
        self.type_chars(engine, 900)
        engine.flush()
        restarted = self.engine()
        self.type_chars(restarted, 100)
        restarted.flush()
        self.assertEqual(self.repo.get_daily('2026-10-07')['typed_chars'], 1000)
        self.assertEqual(self.repo.get_exp(), 5)

    def test_restart_does_not_reward_retyped_previously_settled_blocks(self):
        """验证重启后重输入已结算千字块不会重复发奖。"""
        engine = self.engine()
        self.type_chars(engine, 2000)
        engine.flush()
        for _ in range(1000):
            engine.handle_delete()
        engine.flush()
        restarted = self.engine()
        self.type_chars(restarted, 1000)
        restarted.flush()
        self.assertEqual(self.repo.get_exp(), 10)
        self.type_chars(restarted, 1000)
        restarted.flush()
        self.assertEqual(self.repo.get_exp(), 15)

    def test_legacy_upgrade_persists_restored_progress_before_deletion(self):
        """验证旧库恢复进度先持久化，再允许删除更新。"""
        engine = self.engine()
        self.type_chars(engine, 2000)
        engine.flush()
        # 模拟旧库：已有统计和当日经验，但尚无新增的千字高水位设置。
        self.conn.execute('DELETE FROM settings WHERE key=?', ('typing_exp_blocks',))
        self.conn.commit()
        upgraded = self.engine()
        for _ in range(1000):
            upgraded.handle_delete()
        upgraded.flush()
        restarted = self.engine()
        self.type_chars(restarted, 1000)
        restarted.flush()
        self.assertEqual(self.repo.get_exp(), 10)
        self.assertEqual(self.repo.get_daily('2026-10-07')['valid_chars'], 2000)

    def test_restart_honors_persisted_daily_exp_cap(self):
        """验证重启继续遵守已持久化当日经验上限。"""
        engine = self.engine()
        self.type_chars(engine, 60000)
        engine.flush()
        self.assertEqual(self.repo.get_exp(), 300)
        restarted = self.engine()
        self.type_chars(restarted, 1000)
        restarted.flush()
        self.assertEqual(self.repo.get_exp(), 300)
        self.assertEqual(self.repo.get_daily('2026-10-07')['valid_chars'], 61000)

    def test_application_day_changes_at_four_not_midnight(self):
        """验证默认应用日在凌晨四点切换，午夜不提前重置。"""
        self.now = datetime(2026, 10, 8, 3, 59)
        engine = self.engine()
        self.type_chars(engine, 900)
        engine.flush()
        restarted = self.engine()
        self.assertEqual(restarted.snapshot()['typed'], 900)

        self.now = datetime(2026, 10, 8, 4, 0)
        self.assertTrue(restarted.check_rollover())
        self.assertEqual(restarted.snapshot()['typed'], 0)
        self.type_chars(restarted, 1000)
        restarted.flush()
        self.assertEqual(self.repo.get_daily('2026-10-07')['typed_chars'], 900)
        self.assertEqual(self.repo.get_daily('2026-10-08')['typed_chars'], 1000)
        self.assertEqual(self.repo.get_exp(), 5)


class AIWorkerTests(DatabaseCase):
    """网络请求走真实 localhost HTTP；工作线程无法访问主线程连接。"""

    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        super().setUp()
        case = self
        self.requests = []
        self.http_status = 200

        class Handler(BaseHTTPRequestHandler):
            """本机测试 HTTP 处理器，返回预定模型结果，不转发真实模型请求。"""
            def do_POST(self):
                """处理本机测试 HTTP 请求并返回预定模型响应，记录参数供用例断言。"""
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                case.requests.append((self.path, body))
                self.send_response(case.http_status)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({
                    'choices': [{'message': {'content': '练习文本'}}],
                }).encode('utf-8'))

            def log_message(self, *args):
                """屏蔽测试 HTTP 访问日志，避免请求内容或模拟凭据进入输出。"""
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cleanup_server():
            """停止并关闭本机 HTTP 测试服务，释放监听端口。"""
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(cleanup_server)
        self.repo.set_setting('ai_backend', 'openai')
        self.repo.set_setting('ai_base_url', f'http://127.0.0.1:{server.server_port}/v1')
        self.repo.set_setting('ai_model', 'original-model')

    def run_in_worker(self, service):
        """在独立线程执行测试动作，断言配置快照不访问创建线程数据库。"""
        results = []
        errors = []

        def run():
            """执行当前用例后台步骤并捕获约定结果，配合同步事件检查线程边界。"""
            try:
                results.append(service.generate('练习', 'cn', 100))
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive(), 'AI 工作线程未及时结束')
        self.assertEqual(errors, [], 'AI 工作线程访问了主线程 SQLite 连接')
        return results[0]

    def test_worker_uses_snapshot_and_returns_generated_text(self):
        # 与 _GenThread 构造路径一致：主线程捕获配置后交给工作线程。
        """验证网络线程只使用捕获配置并回传生成正文。"""
        service = AIService(self.repo).snapshot()
        self.assertEqual(self.run_in_worker(service), (True, '练习文本'))
        self.assertEqual(self.requests[0][0], '/v1/chat/completions')
        self.assertIn('练习', self.requests[0][1]['messages'][0]['content'])

    def test_snapshot_is_stable_while_next_request_uses_updated_settings(self):
        """验证在途配置快照稳定，下一请求采用新提交设置。"""
        service = AIService(self.repo)
        snapshot = service.snapshot()
        self.repo.set_setting('ai_model', 'updated-model')
        self.assertEqual(self.run_in_worker(snapshot), (True, '练习文本'))
        self.assertEqual(self.run_in_worker(service.snapshot()), (True, '练习文本'))
        self.assertEqual([body['model'] for _, body in self.requests],
                         ['original-model', 'updated-model'])

    def test_worker_reports_http_errors_without_database_access(self):
        """验证模型后台错误回传不访问数据库连接。"""
        self.http_status = 503
        ok, error = self.run_in_worker(AIService(self.repo).snapshot())
        self.assertFalse(ok)
        self.assertIn('503', error)


if __name__ == '__main__':
    unittest.main()
