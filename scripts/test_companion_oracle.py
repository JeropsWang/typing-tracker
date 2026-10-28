"""占卜严格协议、真实模型适配及共享服务准入回归；只用模拟传输。"""
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.modules.companion.api import AgentConfig, OracleResult, parse_oracle, validate_question
from app.integrations.companion_agent.model import CompanionModel
from app.integrations.companion_agent.service import CompanionAgentService
from app.integrations.companion_agent.search import AgentError, AgentCancelled
from test_companion_agent import Response


class OracleTests(unittest.TestCase):
    """拒绝伪概率和无限请求，验证占卜不需要搜索能力。"""
    def test_strict_probabilities_and_question_boundaries(self):
        """缺字段、非整数、重复键、外层文字和错误总和不能成为成功结果。"""
        result = parse_oracle('{"yes":80,"uncertain":10,"no":10}', 'r', '会下雨吗')
        self.assertEqual((result.yes, result.uncertain, result.no, result.verdict), (80, 10, 10, '是'))
        self.assertEqual(parse_oracle('{"yes":50,"uncertain":0,"no":50}', 'r', '问题').verdict, '不确定')
        invalid = ['{}', '{"yes":true,"uncertain":0,"no":99}',
            '{"yes":80.0,"uncertain":10,"no":10}', '{"yes":90,"uncertain":10,"no":10}',
            '{"yes":80,"uncertain":10,"no":10,"x":0}',
            '{"yes":70,"yes":80,"uncertain":10,"no":10}',
            '```json\n{"yes":80,"uncertain":10,"no":10}\n```',
            '{"yes":-1,"uncertain":1,"no":100}', '{"yes":NaN,"uncertain":0,"no":100}']
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_oracle(raw, 'r', '问题')
        self.assertEqual(validate_question('  问题  '), '问题')
        for question in ['', ' ', '问' * 51]:
            with self.assertRaises(ValueError): validate_question(question)

    def make_model(self, replies, provider='local'):
        """提供受控 HTTP 队列，记录真实适配器组装的请求。"""
        self.payloads = []
        def opener(request, timeout):
            """返回一项模拟响应或 HTTP 失败，不访问真实模型。"""
            self.payloads.append(json.loads(request.data))
            item = replies.pop(0)
            if isinstance(item, Exception): raise item
            return Response(dict(choices=[dict(message=dict(content=item), finish_reason='stop')]))
        return CompanionModel(AgentConfig(enabled=True, provider=provider, model='qwen3:1.7b',
            api_key='fixture', search_provider='invalid'), opener=opener)

    def test_success_is_one_short_structured_request_without_tools(self):
        """正常只请求一次，模型正文只有三项概率，且不附搜索工具或画像。"""
        model = self.make_model(['{"yes":80,"uncertain":10,"no":10}'])
        result = model.judge('r', '会顺利吗', threading.Event(), lambda _: None)
        self.assertEqual(result.yes, 80)
        self.assertEqual(len(self.payloads), 1)
        self.assertNotIn('tools', self.payloads[0])
        self.assertIn('response_format', self.payloads[0])
        self.assertLessEqual(self.payloads[0]['max_tokens'], 256)

    def test_invalid_format_repairs_once_and_then_fails(self):
        """即使连续无效也只请求两次，不把不合法候选交给 UI。"""
        model = self.make_model(['not json', '{}'])
        with self.assertRaises(AgentError): model.judge('r', '问题', threading.Event(), lambda _: None)
        self.assertEqual(len(self.payloads), 2)
        model = self.make_model(['{}', '{"yes":0,"uncertain":100,"no":0}'])
        self.assertEqual(model.judge('r', '问题', threading.Event(), lambda _: None).uncertain, 100)

    def test_explicit_format_rejection_downgrades_with_same_budget(self):
        """只有明确不支持 response_format 的400错误允许去除参数重试。"""
        error = HTTPError('https://example.test', 400, 'bad request', {},
                          io.BytesIO(b'{"error":{"param":"response_format","code":"unsupported_parameter"}}'))
        model = self.make_model([error, '{"yes":0,"uncertain":100,"no":0}'])
        self.assertEqual(model.judge('r', '问题', threading.Event(), lambda _: None).uncertain, 100)
        self.assertNotIn('response_format', self.payloads[1])

    def test_network_auth_and_rate_errors_never_retry(self):
        """真实传输分类保留，避免格式兼容逻辑重复计费。"""
        for error in [TimeoutError(), HTTPError('https://example.test', 401, 'no', {}, io.BytesIO()),
                      HTTPError('https://example.test', 429, 'limit', {}, io.BytesIO())]:
            model = self.make_model([error])
            with self.assertRaises(AgentError): model.judge('r', '问题', threading.Event(), lambda _: None)
            self.assertEqual(len(self.payloads), 1)

    def test_service_skips_search_and_cancel_keeps_gate_until_finished(self):
        """占卜不构造搜索器，取消后真实请求结束前搜索和占卜均不得进入。"""
        entered, release = threading.Event(), threading.Event()
        class Model:
            """可控阻塞网络能力，保留正式服务线程及准入逻辑。"""
            def __init__(self, config):
                """接收本次不可变配置快照。"""
            def validate(self):
                """模拟合法模型配置。"""
            def judge(self, request_id, question, cancel, progress):
                """在取消后仍保持在途，直到测试释放传输。"""
                entered.set()
                release.wait(5)
                return OracleResult(request_id, question, 80, 10, 10)
        def forbidden_search(config):
            """占卜若访问搜索能力，本例立即失败。"""
            raise AssertionError('oracle must not construct search')
        service = CompanionAgentService(model_factory=Model, search_factory=forbidden_search)
        self.addCleanup(service.close)
        self.addCleanup(release.set)
        config = AgentConfig(enabled=True, provider='local')
        request_id, future = service.judge(config, '问题', lambda _: None)
        self.assertTrue(entered.wait(2))
        self.assertFalse(service.cancel('not-owner'))
        self.assertTrue(service.cancel(request_id))
        with self.assertRaises(AgentError): service.judge(config, '问题', lambda _: None)
        self.assertTrue(service.busy)
        release.set()
        with self.assertRaises(AgentCancelled): future.result(5)
        self.assertFalse(service.busy)


if __name__ == '__main__':
    unittest.main()
