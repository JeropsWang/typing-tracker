"""思考开关与用量：本地 HTTP 验证请求协议及真实响应解析。"""
import json
import sqlite3
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from test_regressions import DatabaseCase
from app.services.ai_service import AIService


class FakeProvider:
    """按请求路由的本机模型服务夹具，用于验证实际传输参数。"""
    def __init__(self):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        self.bodies = []
        self.required = {}
        self.forbidden = ()
        self.status = 200
        self.stream_events = None
        self.reply = {'choices': [{'finish_reason': 'stop', 'message': {'content': '练习文本'}}],
                      'usage': {'prompt_tokens': 20, 'completion_tokens': 80, 'total_tokens': 100,
                                'completion_tokens_details': {'reasoning_tokens': 60}}}
        owner = self

        class Handler(BaseHTTPRequestHandler):
            """本机测试 HTTP 处理器，返回预定模型结果，不转发真实模型请求。"""
            def do_POST(self):
                """处理本机测试 HTTP 请求并返回预定模型响应，记录参数供用例断言。"""
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.bodies.append(body)
                if (any(body.get(k) != v for k, v in owner.required.items())
                        or any(k in body for k in owner.forbidden)):
                    self.send_error(400, 'Incompatible reasoning configuration')
                    return
                self.send_response(owner.status)
                self.send_header('Content-Type', 'text/event-stream' if owner.stream_events is not None else 'application/json')
                self.end_headers()
                if owner.stream_events is None:
                    self.wfile.write(json.dumps(owner.reply).encode())
                else:
                    for event in owner.stream_events:
                        value = event if isinstance(event, str) else json.dumps(event, ensure_ascii=False)
                        self.wfile.write(('data: ' + value + '\n\n').encode('utf-8'))

            def log_message(self, *args):
                """屏蔽测试 HTTP 访问日志，避免请求内容或模拟凭据进入输出。"""
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        """结束本例模拟服务生命周期，供清理/退出行为验证。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def routed(self):
        """创建按用例路由的模拟 HTTP 服务，用请求断言验证模型协议而非调用付费上游。"""
        urlopen = urllib.request.urlopen

        def send(request, timeout):
            """按本例设定发送 HTTP JSON/SSE 响应，供真实传输读取器验证。"""
            forwarded = urllib.request.Request(self.base + '/chat/completions', data=request.data,
                                               headers=request.headers, method=request.method)
            return urlopen(forwarded, timeout=timeout)

        return patch('app.services.ai_service.urllib.request.urlopen', side_effect=send)


class AIControlTests(DatabaseCase):
    """模型思考草稿与连接检查的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        super().setUp()
        self.provider = FakeProvider()
        self.addCleanup(self.provider.close)

    def service(self, base, model, thinking='0', protocol='auto', backend='openai'):
        """使用本例隔离配置/模拟传输构造待测服务，避免读取用户模型设置。"""
        return AIService(config=dict(backend=backend, base_url=base, api_key='test-key',
                                     model=model, thinking=thinking, thinking_protocol=protocol))

    def test_deepseek_can_enable_thinking_instead_of_always_disabling_it(self):
        """用模拟协议验证 DeepSeek 可开启思考，而非固定发送关闭参数。"""
        self.provider.required = {'thinking': {'type': 'enabled'}, 'max_tokens': 8192}
        with self.provider.routed():
            ok, text = self.service('https://api.deepseek.com/v1', 'deepseek-v4-flash', '1').generate('星空')
        self.assertTrue(ok, text)

    def test_qwen_defaults_to_non_thinking_and_can_enable_it(self):
        """用模拟请求验证本地模型默认非思考并支持显式开启。"""
        with self.provider.routed():
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    self.provider.required = {'enable_thinking': enabled}
                    ok, text = self.service('https://dashscope.aliyuncs.com/compatible-mode/v1',
                                            'qwen-plus', '1' if enabled else '0').generate('星空')
                    self.assertTrue(ok, text)

    def test_openai_uses_supported_reasoning_and_completion_budget_parameters(self):
        """验证模型思考及 completion 预算字段按能力选择。"""
        self.provider.forbidden = ('max_tokens', 'temperature')
        with self.provider.routed():
            for enabled in (False, True):
                self.provider.required = {'reasoning_effort': 'high' if enabled else 'none',
                                          'max_completion_tokens': 8192 if enabled else 600}
                ok, text = self.service('https://api.openai.com/v1', 'gpt-5.2',
                                        '1' if enabled else '0').generate('星空')
                self.assertTrue(ok, text)

    def test_ollama_requests_none_or_high_using_compatible_effort(self):
        """用模拟传输验证本地思考开关对应兼容 effort 参数。"""
        with self.provider.routed():
            for enabled in (False, True):
                self.provider.required = {'reasoning_effort': 'high' if enabled else 'none'}
                ok, text = self.service(self.provider.base, 'qwen3:8b', '1' if enabled else '0',
                                        backend='ollama').generate('星空')
                self.assertTrue(ok, text)

    def test_openai_56_family_supports_disabling_thinking(self):
        """用模拟协议验证当前识别的模型家族可关闭思考。"""
        self.provider.required = {'reasoning_effort': 'none', 'max_completion_tokens': 600}
        self.provider.forbidden = ('max_tokens', 'temperature')
        with self.provider.routed():
            ok, text = self.service('https://api.openai.com/v1', 'gpt-5.6-sol').generate('星空')
        self.assertTrue(ok, text)

    def test_openai_model_through_manual_proxy_keeps_compatible_budget(self):
        """验证手动代理协议保留对应模型的兼容预算字段。"""
        self.provider.required = {'reasoning_effort': 'none', 'max_completion_tokens': 600}
        self.provider.forbidden = ('max_tokens', 'temperature')
        ok, text = self.service(self.provider.base, 'gpt-5.2', protocol='reasoning_effort').generate('星空')
        self.assertTrue(ok, text)

    def test_custom_compatible_endpoint_can_select_a_protocol(self):
        """验证自定义兼容端点可显式选择思考协议。"""
        for protocol, key, value in [('thinking', 'thinking', {'type': 'disabled'}),
                                      ('enable_thinking', 'enable_thinking', False),
                                      ('reasoning_effort', 'reasoning_effort', 'none')]:
            with self.subTest(protocol=protocol):
                self.provider.required = {key: value}
                ok, text = self.service(self.provider.base, 'custom-model', protocol=protocol).generate('星空')
                self.assertTrue(ok, text)

    def test_qwen_thinking_requests_stream_with_usage_for_stream_only_models(self):
        """验证需要流式的思考协议同时请求用量字段。"""
        self.provider.required = {'enable_thinking': True, 'stream': True,
                                  'stream_options': {'include_usage': True}}
        with self.provider.routed():
            ok, text = self.service('https://dashscope.aliyuncs.com/compatible-mode/v1',
                                    'qwen3-32b', '1').generate('星空')
        self.assertTrue(ok, text)

    def stream_reply(self, finish='stop'):
        """构造本例含结束标记的 SSE 响应，控制正文/推理/用量片段。"""
        return [dict(choices=[dict(index=0, delta=dict(reasoning_content='private'), finish_reason=None)]),
                dict(choices=[dict(index=0, delta=dict(content='星空'), finish_reason=None)]),
                dict(choices=[dict(index=0, delta=dict(content='练习'), finish_reason=finish)]),
                dict(choices=[], usage=self.provider.reply['usage']), '[DONE]']

    def test_stream_combines_only_final_text_and_preserves_usage_chunk(self):
        """验证流式只拼可见正文并保留独立用量分片。"""
        self.provider.stream_events = self.stream_reply()
        service = self.service(self.provider.base, 'qwen3-32b', '1', 'enable_thinking')
        ok, text = service.generate('星空')
        self.assertTrue(ok, text)
        self.assertEqual(text, '星空练习')
        self.assertEqual(service.last_usage.total_tokens, 100)

    def test_truncated_stream_preserves_usage_but_does_not_save_partial_text(self):
        """验证截断流式保留用量但不保存半段训练正文。"""
        self.provider.stream_events = self.stream_reply(finish='length')
        service = self.service(self.provider.base, 'qwen3-32b', '1', 'enable_thinking')
        ok, error = service.generate('星空')
        self.assertFalse(ok)
        self.assertIn('上限', error)
        self.assertEqual(service.last_usage.total_tokens, 100)

    def test_stream_without_finish_reason_is_rejected_even_with_usage(self):
        """验证已返回用量但缺完成原因时仍拒绝半段正文。"""
        self.provider.stream_events = self.stream_reply(finish=None)
        service = self.service(self.provider.base, 'qwen3-32b', '1', 'enable_thinking')
        ok, error = service.generate('星空')
        self.assertFalse(ok)
        self.assertIn('提前结束', error)
        self.assertEqual(service.last_usage.total_tokens, 100)

    def test_thinking_only_model_is_rejected_before_a_paid_request_when_disabled(self):
        """用模拟传输验证仅思考模型在禁用模式下于发送前被拒绝。"""
        with self.provider.routed():
            ok, error = self.service('https://api.openai.com/v1', 'o3').generate('星空')
        self.assertFalse(ok)
        self.assertIn('无法关闭', error)
        self.assertEqual(self.provider.bodies, [])

    def test_unknown_protocol_does_not_pretend_to_enable_thinking(self):
        """验证未知协议明确拒绝思考要求，不虚构已开启。"""
        ok, error = self.service(self.provider.base, 'custom-model', '1').generate('星空')
        self.assertFalse(ok)
        self.assertIn('协议', error)
        self.assertEqual(self.provider.bodies, [])

    def test_snapshot_keeps_draft_thinking_settings_away_from_worker_database(self):
        """验证模型后台仅用思考配置快照，不持有 UI 草稿或数据库。"""
        self.repo.set_settings(dict(ai_backend='openai', ai_base_url=self.provider.base,
                                    ai_model='custom-model', ai_thinking='1', ai_thinking_protocol='thinking'))
        service = AIService(self.repo).snapshot()
        self.repo.set_setting('ai_thinking', '0')
        self.provider.required = {'thinking': {'type': 'enabled'}}
        self.assertTrue(service.generate('星空')[0])

    def test_usage_preserves_reported_total_without_double_counting_reasoning(self):
        """验证用量采用接口总数，不将已包含的推理重复相加。"""
        service = self.service(self.provider.base, 'custom-model')
        self.assertTrue(service.generate('星空')[0])
        usage = getattr(service, 'last_usage', None)
        self.assertIsNotNone(usage)
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.reasoning_tokens, usage.total_tokens),
                         (20, 80, 60, 100))

    def test_truncated_failure_keeps_usage_even_without_final_text(self):
        """验证截断无正文时仍保留本次实际 token 用量。"""
        self.provider.reply['choices'][0] = {'finish_reason': 'length',
                                             'message': {'content': '', 'reasoning_content': 'private'}}
        service = self.service(self.provider.base, 'custom-model')
        self.assertFalse(service.generate('星空')[0])
        usage = getattr(service, 'last_usage', None)
        self.assertIsNotNone(usage)
        self.assertEqual(usage.total_tokens, 100)

    def test_http_failure_preserves_usage_when_the_error_body_reports_it(self):
        """用模拟 HTTP 错误验证上游提供的用量仍可保留。"""
        self.provider.status = 429
        service = self.service(self.provider.base, 'custom-model')
        self.assertFalse(service.generate('星空')[0])
        usage = service.last_usage
        self.assertIsNotNone(usage)
        self.assertEqual(usage.total_tokens, 100)

    def test_missing_usage_does_not_reuse_previous_request_counts(self):
        """验证缺失用量时不沿用上一请求 token。"""
        service = self.service(self.provider.base, 'custom-model')
        self.assertTrue(service.generate('星空')[0])
        self.provider.reply.pop('usage')
        self.assertTrue(service.generate('星空')[0])
        self.assertIsNone(service.last_usage)

    def test_usage_absent_fields_and_invalid_counts_remain_unknown(self):
        """验证缺失或非法 token 字段保持未知而不填零。"""
        self.provider.reply['usage'] = {'prompt_tokens': 0, 'completion_tokens': -1,
                                        'total_tokens': True}
        service = self.service(self.provider.base, 'custom-model')
        self.assertTrue(service.generate('星空')[0])
        usage = getattr(service, 'last_usage', None)
        self.assertIsNotNone(usage)
        self.assertEqual(usage.input_tokens, 0)
        self.assertIsNone(usage.output_tokens)
        self.assertIsNone(usage.reasoning_tokens)
        self.assertIsNone(usage.total_tokens)


if __name__ == '__main__':
    unittest.main()
