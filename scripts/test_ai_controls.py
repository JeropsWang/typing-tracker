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
    def __init__(self):
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
            def do_POST(self):
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
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}/v1'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def routed(self):
        urlopen = urllib.request.urlopen

        def send(request, timeout):
            forwarded = urllib.request.Request(self.base + '/chat/completions', data=request.data,
                                               headers=request.headers, method=request.method)
            return urlopen(forwarded, timeout=timeout)

        return patch('app.services.ai_service.urllib.request.urlopen', side_effect=send)


class AIControlTests(DatabaseCase):
    def setUp(self):
        super().setUp()
        self.provider = FakeProvider()
        self.addCleanup(self.provider.close)

    def service(self, base, model, thinking='0', protocol='auto', backend='openai'):
        return AIService(config=dict(backend=backend, base_url=base, api_key='test-key',
                                     model=model, thinking=thinking, thinking_protocol=protocol))

    def test_deepseek_can_enable_thinking_instead_of_always_disabling_it(self):
        self.provider.required = {'thinking': {'type': 'enabled'}, 'max_tokens': 8192}
        with self.provider.routed():
            ok, text = self.service('https://api.deepseek.com/v1', 'deepseek-v4-flash', '1').generate('星空')
        self.assertTrue(ok, text)

    def test_qwen_defaults_to_non_thinking_and_can_enable_it(self):
        with self.provider.routed():
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    self.provider.required = {'enable_thinking': enabled}
                    ok, text = self.service('https://dashscope.aliyuncs.com/compatible-mode/v1',
                                            'qwen-plus', '1' if enabled else '0').generate('星空')
                    self.assertTrue(ok, text)

    def test_openai_uses_supported_reasoning_and_completion_budget_parameters(self):
        self.provider.forbidden = ('max_tokens', 'temperature')
        with self.provider.routed():
            for enabled in (False, True):
                self.provider.required = {'reasoning_effort': 'high' if enabled else 'none',
                                          'max_completion_tokens': 8192 if enabled else 600}
                ok, text = self.service('https://api.openai.com/v1', 'gpt-5.2',
                                        '1' if enabled else '0').generate('星空')
                self.assertTrue(ok, text)

    def test_ollama_requests_none_or_high_using_compatible_effort(self):
        with self.provider.routed():
            for enabled in (False, True):
                self.provider.required = {'reasoning_effort': 'high' if enabled else 'none'}
                ok, text = self.service(self.provider.base, 'qwen3:8b', '1' if enabled else '0',
                                        backend='ollama').generate('星空')
                self.assertTrue(ok, text)

    def test_openai_56_family_supports_disabling_thinking(self):
        self.provider.required = {'reasoning_effort': 'none', 'max_completion_tokens': 600}
        self.provider.forbidden = ('max_tokens', 'temperature')
        with self.provider.routed():
            ok, text = self.service('https://api.openai.com/v1', 'gpt-5.6-sol').generate('星空')
        self.assertTrue(ok, text)

    def test_openai_model_through_manual_proxy_keeps_compatible_budget(self):
        self.provider.required = {'reasoning_effort': 'none', 'max_completion_tokens': 600}
        self.provider.forbidden = ('max_tokens', 'temperature')
        ok, text = self.service(self.provider.base, 'gpt-5.2', protocol='reasoning_effort').generate('星空')
        self.assertTrue(ok, text)

    def test_custom_compatible_endpoint_can_select_a_protocol(self):
        for protocol, key, value in [('thinking', 'thinking', {'type': 'disabled'}),
                                      ('enable_thinking', 'enable_thinking', False),
                                      ('reasoning_effort', 'reasoning_effort', 'none')]:
            with self.subTest(protocol=protocol):
                self.provider.required = {key: value}
                ok, text = self.service(self.provider.base, 'custom-model', protocol=protocol).generate('星空')
                self.assertTrue(ok, text)

    def test_qwen_thinking_requests_stream_with_usage_for_stream_only_models(self):
        self.provider.required = {'enable_thinking': True, 'stream': True,
                                  'stream_options': {'include_usage': True}}
        with self.provider.routed():
            ok, text = self.service('https://dashscope.aliyuncs.com/compatible-mode/v1',
                                    'qwen3-32b', '1').generate('星空')
        self.assertTrue(ok, text)

    def stream_reply(self, finish='stop'):
        return [dict(choices=[dict(index=0, delta=dict(reasoning_content='private'), finish_reason=None)]),
                dict(choices=[dict(index=0, delta=dict(content='星空'), finish_reason=None)]),
                dict(choices=[dict(index=0, delta=dict(content='练习'), finish_reason=finish)]),
                dict(choices=[], usage=self.provider.reply['usage']), '[DONE]']

    def test_stream_combines_only_final_text_and_preserves_usage_chunk(self):
        self.provider.stream_events = self.stream_reply()
        service = self.service(self.provider.base, 'qwen3-32b', '1', 'enable_thinking')
        ok, text = service.generate('星空')
        self.assertTrue(ok, text)
        self.assertEqual(text, '星空练习')
        self.assertEqual(service.last_usage.total_tokens, 100)

    def test_truncated_stream_preserves_usage_but_does_not_save_partial_text(self):
        self.provider.stream_events = self.stream_reply(finish='length')
        service = self.service(self.provider.base, 'qwen3-32b', '1', 'enable_thinking')
        ok, error = service.generate('星空')
        self.assertFalse(ok)
        self.assertIn('上限', error)
        self.assertEqual(service.last_usage.total_tokens, 100)

    def test_stream_without_finish_reason_is_rejected_even_with_usage(self):
        self.provider.stream_events = self.stream_reply(finish=None)
        service = self.service(self.provider.base, 'qwen3-32b', '1', 'enable_thinking')
        ok, error = service.generate('星空')
        self.assertFalse(ok)
        self.assertIn('提前结束', error)
        self.assertEqual(service.last_usage.total_tokens, 100)

    def test_thinking_only_model_is_rejected_before_a_paid_request_when_disabled(self):
        with self.provider.routed():
            ok, error = self.service('https://api.openai.com/v1', 'o3').generate('星空')
        self.assertFalse(ok)
        self.assertIn('无法关闭', error)
        self.assertEqual(self.provider.bodies, [])

    def test_unknown_protocol_does_not_pretend_to_enable_thinking(self):
        ok, error = self.service(self.provider.base, 'custom-model', '1').generate('星空')
        self.assertFalse(ok)
        self.assertIn('协议', error)
        self.assertEqual(self.provider.bodies, [])

    def test_snapshot_keeps_draft_thinking_settings_away_from_worker_database(self):
        self.repo.set_settings(dict(ai_backend='openai', ai_base_url=self.provider.base,
                                    ai_model='custom-model', ai_thinking='1', ai_thinking_protocol='thinking'))
        service = AIService(self.repo).snapshot()
        self.repo.set_setting('ai_thinking', '0')
        self.provider.required = {'thinking': {'type': 'enabled'}}
        self.assertTrue(service.generate('星空')[0])

    def test_usage_preserves_reported_total_without_double_counting_reasoning(self):
        service = self.service(self.provider.base, 'custom-model')
        self.assertTrue(service.generate('星空')[0])
        usage = getattr(service, 'last_usage', None)
        self.assertIsNotNone(usage)
        self.assertEqual((usage.input_tokens, usage.output_tokens, usage.reasoning_tokens, usage.total_tokens),
                         (20, 80, 60, 100))

    def test_truncated_failure_keeps_usage_even_without_final_text(self):
        self.provider.reply['choices'][0] = {'finish_reason': 'length',
                                             'message': {'content': '', 'reasoning_content': 'private'}}
        service = self.service(self.provider.base, 'custom-model')
        self.assertFalse(service.generate('星空')[0])
        usage = getattr(service, 'last_usage', None)
        self.assertIsNotNone(usage)
        self.assertEqual(usage.total_tokens, 100)

    def test_http_failure_preserves_usage_when_the_error_body_reports_it(self):
        self.provider.status = 429
        service = self.service(self.provider.base, 'custom-model')
        self.assertFalse(service.generate('星空')[0])
        usage = service.last_usage
        self.assertIsNotNone(usage)
        self.assertEqual(usage.total_tokens, 100)

    def test_missing_usage_does_not_reuse_previous_request_counts(self):
        service = self.service(self.provider.base, 'custom-model')
        self.assertTrue(service.generate('星空')[0])
        self.provider.reply.pop('usage')
        self.assertTrue(service.generate('星空')[0])
        self.assertIsNone(service.last_usage)

    def test_usage_absent_fields_and_invalid_counts_remain_unknown(self):
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
