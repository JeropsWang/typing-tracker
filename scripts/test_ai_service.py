"""AI 正文生成兼容性：真实本地 HTTP，不使用用户 Key 或外部接口。"""
from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.ai_service import AIService


class AIResponseTests(unittest.TestCase):
    """模型协议及完整正文校验的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        self.reply = {'choices': [{'finish_reason': 'stop',
                                  'message': {'content': '星空之下，指尖轻舞。'}}]}
        self.deepseek = False
        case = self

        class Handler(BaseHTTPRequestHandler):
            """本机测试 HTTP 处理器，返回预定模型结果，不转发真实模型请求。"""
            def do_POST(self):
                """处理本机测试 HTTP 请求并返回预定模型响应，记录参数供用例断言。"""
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                reply = case.reply
                if case.deepseek:
                    if body.get('thinking') == {'type': 'disabled'}:
                        content = ('OK' if 'OK' in body['messages'][0]['content']
                                   else '星空之下，指尖轻舞。')
                        reply = {'choices': [{'finish_reason': 'stop',
                                              'message': {'content': content}}]}
                    else:
                        # 实际故障响应：思考用完输出预算，尚未生成正文。
                        reply = {'choices': [{'finish_reason': 'length',
                                              'message': {'content': '',
                                                          'reasoning_content': 'private reasoning'}}]}
                elif 'thinking' in body:
                    self.send_error(400, 'Unsupported parameter: thinking')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode())

            def log_message(self, *args):
                """屏蔽测试 HTTP 访问日志，避免请求内容或模拟凭据进入输出。"""
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            """停止本例本机 HTTP 夹具及线程，避免污染后续请求。"""
            self.server.shutdown()
            self.server.server_close()
            thread.join(timeout=5)

        self.addCleanup(cleanup)
        self.local = f'http://127.0.0.1:{self.server.server_port}/v1'

    def service(self, base=None, model='example-model'):
        """使用本例隔离配置/模拟传输构造待测服务，避免读取用户模型设置。"""
        return AIService(config={'backend': 'openai', 'base_url': base or self.local,
                                 'model': model, 'api_key': 'test-key'})

    def routed(self):
        # 只替换网络目的地，保留生产请求的参数生成与响应解析。
        """创建按用例路由的模拟 HTTP 服务，用请求断言验证模型协议而非调用付费上游。"""
        urlopen = urllib.request.urlopen

        def send(request, timeout):
            """按本例设定发送 HTTP JSON/SSE 响应，供真实传输读取器验证。"""
            forwarded = urllib.request.Request(self.local + '/chat/completions',
                                               data=request.data, headers=request.headers,
                                               method=request.method)
            return urlopen(forwarded, timeout=timeout)

        return patch('app.services.ai_service.urllib.request.urlopen', side_effect=send)

    def test_official_deepseek_generates_final_passage_with_small_budget(self):
        """用模拟 DeepSeek 协议验证短预算仍只接受完整范文。"""
        self.deepseek = True
        with self.routed():
            for model in ('deepseek-v4-flash', 'deepseek-flash', 'deepseek-v4-pro'):
                with self.subTest(model=model):
                    self.assertEqual(self.service('https://api.deepseek.com/v1', model)
                                     .generate('星空'), (True, '星空之下，指尖轻舞。'))

    def test_official_deepseek_connection_receives_a_final_reply(self):
        """用模拟官方端点协议验证短连接返回最终正文。"""
        self.deepseek = True
        with self.routed():
            ok, message = self.service('https://api.deepseek.com', 'deepseek-v4-flash').test_connection()
        self.assertTrue(ok, message)
        self.assertIn('OK', message)

    def test_english_chat_uses_the_same_deepseek_compatibility(self):
        """验证英语模型调用复用共享 DeepSeek 协议。"""
        self.deepseek = True
        with self.routed():
            reply = self.service('https://api.deepseek.com/v1', 'deepseek-v4-flash').chat(
                [{'role': 'user', 'content': '英文语句'}], max_tokens=700)
        self.assertEqual(reply, '星空之下，指尖轻舞。')

    def test_custom_endpoint_does_not_receive_deepseek_only_parameters(self):
        """验证未知兼容端点不会收到 DeepSeek 专属参数。"""
        self.assertEqual(self.service(model='deepseek-v4-flash').generate('星空'),
                         (True, '星空之下，指尖轻舞。'))
        with self.routed():
            for base in ('https://api.openai.com/v1', 'https://api.deepseek.com.example/v1'):
                with self.subTest(base=base):
                    self.assertEqual(self.service(base, 'deepseek-v4-flash').generate('星空'),
                                     (True, '星空之下，指尖轻舞。'))

    def test_reasoning_only_null_reply_reports_no_final_text(self):
        """验证仅推理且正文为空的响应被判为未提供最终文本。"""
        self.reply = {'choices': [{'finish_reason': 'stop',
                                  'message': {'content': None, 'reasoning_content': 'private reasoning'}}]}
        ok, error = self.service().generate('星空')
        self.assertFalse(ok)
        self.assertIn('思考', error)
        self.assertNotIn('private reasoning', error)

    def test_truncated_passage_is_not_accepted_as_complete(self):
        """验证截断范文不当作完整可保存材料。"""
        self.reply = {'choices': [{'finish_reason': 'length',
                                  'message': {'content': '未写完的半句', 'reasoning_content': 'private reasoning'}}]}
        ok, error = self.service().generate('星空')
        self.assertFalse(ok)
        self.assertIn('上限', error)
        self.assertNotIn('private reasoning', error)

    def test_empty_connection_reply_is_not_a_success(self):
        """验证无正文连接响应不能标为成功。"""
        self.reply = {'choices': [{'message': {'content': '  '}}]}
        ok, error = self.service().test_connection()
        self.assertFalse(ok)
        self.assertIn('正文', error)

    def test_malformed_response_reports_format_error(self):
        """验证非法模型响应返回格式错误而非假成功。"""
        for reply in ({'choices': []}, {'choices': [None]},
                      {'choices': [{'message': {'content': ['unexpected']}}]}):
            with self.subTest(reply=reply):
                self.reply = reply
                ok, error = self.service().generate('星空')
                self.assertFalse(ok)
                self.assertIn('格式', error)

    def test_regular_compatible_reply_still_generates_passage(self):
        """验证普通兼容模型仍能生成完整范文。"""
        self.assertEqual(self.service().generate('星空'), (True, '星空之下，指尖轻舞。'))


if __name__ == '__main__':
    unittest.main()
