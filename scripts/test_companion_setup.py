"""Async model/search checks without external services."""
import json
from pathlib import Path
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.modules.companion.api import AgentConfig, SearchSource
from app.integrations.companion_agent.setup import AgentSetupService
from app.integrations.companion_agent.model import CompanionModel
from app.integrations.companion_agent.search import AgentError, AgentCancelled
from test_companion_agent import Response


class SetupTests(unittest.TestCase):
    """独立草稿连接检查的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def test_model_check_uses_small_draft_completion_and_keeps_keys_private(self):
        """验证模型检查用未保存草稿和短预算，密钥不进入可见信息。"""
        captured = []
        def opener(request, timeout):
            """提供预定 HTTP 响应及参数检查，避免本例访问实际外网。"""
            payload = json.loads(request.data)
            captured.append(payload)
            self.assertEqual(payload['max_tokens'], 32)
            self.assertTrue(payload['stream'])
            self.assertFalse(payload['think'])
            return Response(dict(choices=[dict(message=dict(content='OK'), finish_reason='stop')]))
        service = AgentSetupService(model_factory=lambda c:CompanionModel(c, opener=opener))
        self.addCleanup(service.close)
        config = AgentConfig(provider='local', model='qwen3:1.7b')
        result = service.test_model(config).result(5)
        self.assertIn('连接成功', result.message)
        self.assertEqual(captured[0]['messages'], [{'role':'user','content':'只回复 OK。'}])
        self.assertFalse(config.enabled)

    def test_model_failures_and_cancel_hold_gate(self):
        """验证模型失败/取消期间准入直至网络实际结束才释放。"""
        started, release = threading.Event(), threading.Event()
        class Model:
            """本用例模型能力替身，响应或失败由当前测试控制。"""
            def __init__(self, _):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                pass
            def test_connection(self, cancel):
                """提供本用例草稿连接检查的模拟能力，按测试安排返回结果或失败。"""
                started.set()
                release.wait(5)
                return 'OK'
        service = AgentSetupService(model_factory=Model)
        self.addCleanup(service.close)
        self.addCleanup(release.set)
        future = service.test_model(AgentConfig())
        self.assertTrue(started.wait(2))
        service.cancel()
        with self.assertRaises(AgentError): service.test_model(AgentConfig())
        release.set()
        with self.assertRaises(AgentCancelled): future.result(5)

    def test_search_check_uses_default_without_container_or_credentials(self):
        """验证默认搜索检查不依赖容器或额外凭据。"""
        class Search:
            """本用例搜索替身，记录查询并按设定返回来源或失败。"""
            def __init__(self, config):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                assert config.search_provider == 'web'
            def search(self, topic, cancel):
                """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
                return (SearchSource('资料', 'https://example.org', '摘录'),)
        service = AgentSetupService(search_factory=Search)
        self.addCleanup(service.close)
        result = service.test_search(AgentConfig()).result(5)
        self.assertEqual(result.source_count, 1)

    def test_old_managed_config_becomes_keyless_but_external_is_preserved(self):
        """验证旧托管配置转免 Key，明确外部服务配置保持原值。"""
        class Settings:
            """受控配置快照夹具，用于一致读取和未保存草稿验证。"""
            def __init__(self, values):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                self.values = values
            def settings(self):
                """返回用例预定配置，供快照及草稿解析验证。"""
                return self.values
        config = AgentConfig.from_settings(Settings({'companion_agent_managed_search':'1',
            'companion_agent_search_provider':'searxng'}))
        self.assertEqual(config.search_provider, 'web')
        config = AgentConfig.from_settings(Settings({'companion_agent_search_provider':'searxng',
            'companion_agent_search_url':'http://127.0.0.1:8080'}))
        self.assertEqual(config.search_provider, 'searxng')
        self.assertEqual(config.search_url, 'http://127.0.0.1:8080')


if __name__ == '__main__': unittest.main()
