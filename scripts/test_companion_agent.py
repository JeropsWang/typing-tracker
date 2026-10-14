"""Real LangGraph execution, bounded transports and cancellation; no paid requests."""
from concurrent.futures import Future
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.modules.companion.api import AgentConfig, SearchSource, validate_topic, AgentTurn, AgentToolCall
from app.integrations.companion_agent.search import WebSearch, AgentError, AgentCancelled, endpoint_url, MAX_RESPONSE
from app.integrations.companion_agent.model import CompanionModel
from app.integrations.companion_agent.stream import VisibleText, read_model_text
from app.integrations.companion_agent.graph import run_search
from app.integrations.companion_agent.service import CompanionAgentService

SOURCE = SearchSource('公开资料', 'https://example.org/source', '这是一条可引用的公开摘录。')
CONFIG = AgentConfig(enabled=True, provider='local', model='qwen3:1.7b', search_provider='tavily', search_key='search-secret')


class Response(io.BytesIO):
    """内存 HTTP 响应夹具，模拟 JSON/SSE 及流式读取行为。"""
    def __init__(self, value, *, stream=False):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        super().__init__(value if isinstance(value, bytes) else json.dumps(value).encode('utf-8'))
        self.headers = {'Content-Type': 'text/event-stream' if stream else 'application/json'}


def events(*choices, done=True):
    """生成确定性 SSE 事件字节，可省略结束以测试中断响应。"""
    result = b''.join(('data: ' + json.dumps({'choices': [c]}, ensure_ascii=False) + '\n\n').encode('utf-8') for c in choices)
    return result + (b'data: [DONE]\n\n' if done else b'')


class FakeModel:
    """确定性模型夹具，模拟配置/轮次/答案而不调用真实上游。"""
    def __init__(self, _=None):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        pass
    def validate(self):
        """提供本例配置校验替身，可按用例成功或拒绝，不访问真实服务。"""
        pass
    def turn(self, messages, tools, cancel, on_text=lambda _: None):
        """返回预定原生模型轮次，验证工具行动/观察续接，不调用真实模型。"""
        if messages[-1]['role'] != 'tool':
            return AgentTurn(tool_calls=(AgentToolCall('search-1', 'web_search', '{"query":"话题"}'),))
        return self.answer()

    def answer(self):
        """返回预设可见模型答案，供成功或异常替换场景使用。"""
        return AgentTurn('整理后的回答 [1]')


class FakeSearch:
    """固定公开来源的搜索夹具，不发起真实网络检索。"""
    def __init__(self, _=None):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        pass
    def validate(self):
        """提供本例配置校验替身，可按用例成功或拒绝，不访问真实服务。"""
        pass
    def search(self, topic, cancel):
        """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
        return (SOURCE,)


class CompanionAgentTests(unittest.TestCase):
    """桌宠传输、配置及搜索准入的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def test_public_search_never_sends_keys_and_encodes_query(self):
        """验证公开检索不发送密钥，查询文本正确编码。"""
        from urllib.parse import parse_qs, urlsplit
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            self.assertIsNone(request.get_header('Authorization'))
            self.assertIsNone(request.data)
            self.assertEqual(parse_qs(urlsplit(request.full_url).query)['q'], ['人工智能 & news'])
            return Response(b'<rss><channel><item><title>News</title><link>https://example.org</link><description>Evidence</description></item></channel></rss>')
        result = WebSearch(replace(CONFIG, search_provider='web-lite', api_key='private-model-key'), opener=open_).search('人工智能 & news', threading.Event())
        self.assertEqual(result[0].snippet, 'Evidence')

    def test_public_search_fallback_and_unavailable_error(self):
        """验证公开搜索备用入口和最终不可用提示。"""
        calls = []
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            calls.append(request.full_url)
            return Response(b'<html>captcha</html>' if len(calls) == 1 else
                b'<rss><channel><item><link>https://example.org</link></item></channel></rss>')
        result = WebSearch(AgentConfig(search_provider='web-lite'), opener=open_).search('topic', threading.Event())
        self.assertEqual(len(result), 1)
        self.assertEqual(len(calls), 2)
        with self.assertRaisesRegex(AgentError, '免 Key 搜索暂时不可用'):
            WebSearch(AgentConfig(search_provider='web-lite'), opener=lambda *_args, **_kw:Response(b'<html>captcha</html>')).search('topic', threading.Event())

    def test_public_parser_filters_sources_limits_and_rejects_entities(self):
        """验证 RSS 来源限额/格式过滤及 DTD/实体拒绝。"""
        from app.integrations.companion_agent.search import parse_public_results
        items = ''.join(f'<item><link>https://example.org/{i}</link><title>{"t"*250}</title><description>{"s"*2500}</description></item>' for i in range(10))
        raw = ('<rss><channel><item><link>javascript:alert(1)</link></item>' + items + '</channel></rss>').encode()
        sources = parse_public_results(raw)
        self.assertEqual(len(sources), 5)
        self.assertEqual(len(sources[0].title), 200)
        self.assertEqual(len(sources[0].snippet), 2000)
        for raw in (b'<!DOCTYPE rss><rss/>', b'<!ENTITY x "value"><rss/>',
                    '<!DOCTYPE rss><rss/>'.encode('utf-16'), b'x'*(MAX_RESPONSE+1)):
            with self.assertRaises(ValueError): parse_public_results(raw)

    def test_public_cancellation_never_attempts_fallback(self):
        """验证公开搜索取消后不继续备用入口请求。"""
        cancel, calls = threading.Event(), []
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            calls.append(request.full_url)
            cancel.set()
            return Response(b'<rss/>')
        with self.assertRaises(AgentCancelled):
            WebSearch(AgentConfig(search_provider='web-lite'), opener=open_).search('topic', cancel)
        self.assertEqual(len(calls), 1)

    def test_configuration_reads_one_committed_snapshot(self):
        """验证配置读取同一次已提交快照，避免服务与密钥版本混用。"""
        class Settings:
            """受控配置快照夹具，用于一致读取和未保存草稿验证。"""
            def __init__(self):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                self.reads = 0
            def settings(self):
                """返回用例预定配置，供快照及草稿解析验证。"""
                self.reads += 1
                return {'companion_agent_enabled':'1', 'companion_agent_provider':'local',
                        'companion_agent_model':'qwen3:1.7b'}
            def get_setting(self, *_):
                """提供逐键查询测试接口，可故意拒绝读取以验证整份快照一致性。"""
                raise AssertionError('Separate reads could mix commits')
        settings = Settings()
        config = AgentConfig.from_settings(settings)
        self.assertTrue(config.enabled)
        self.assertEqual(config.model, 'qwen3:1.7b')
        self.assertEqual(settings.reads, 1)

    def test_topic_limits_and_secret_repr(self):
        """验证主动话题长度限制及配置 repr 不泄漏密钥。"""
        self.assertEqual(validate_topic('  天文  '), '天文')
        for topic in ('   ', 'a' * 201):
            with self.assertRaises(ValueError): validate_topic(topic)
        self.assertNotIn('search-secret', repr(CONFIG))
        self.assertNotIn('model-secret', repr(replace(CONFIG, api_key='model-secret')))

    def test_model_provider_presets_and_key_validation(self):
        """验证模型服务预设及各后端密钥资格。"""
        for provider, host in [('openai', 'api.openai.com'), ('deepseek', 'api.deepseek.com'), ('local', '127.0.0.1')]:
            config = replace(CONFIG, provider=provider, model='', api_key='model-secret')
            self.assertIn(host, config.model_settings()['base_url'])
            CompanionModel(config).validate()
        with self.assertRaises(AgentError): CompanionModel(replace(CONFIG, provider='openai')).validate()

    def test_endpoints_reject_credentials_and_unencrypted_remote(self):
        """验证服务端点拒绝嵌入凭据及远程明文 HTTP。"""
        for url in ('http://example.org/v1', 'https://user:secret@example.org/v1', 'file:///secret', 'https://example.org?key=secret'):
            with self.assertRaises(AgentError): endpoint_url(url)
        self.assertEqual(endpoint_url('http://127.0.0.1:8080/'), 'http://127.0.0.1:8080')

    def test_tavily_payload_sources_sanitized_deduplicated_bounded(self):
        """验证 Tavily 请求参数及来源过滤、去重和限额。"""
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            self.assertEqual(request.full_url, 'https://api.tavily.com/search')
            payload = json.loads(request.data)
            self.assertEqual(payload['query'], '话题')
            self.assertEqual(payload['max_results'], 5)
            self.assertFalse(payload['include_answer'])
            return Response(dict(results=[dict(title='unsafe', url='javascript:alert(1)', content='x'),
                dict(title='标题', url=SOURCE.url, content='a'*4000),
                dict(title='重复', url=SOURCE.url, content='x')]))
        result = WebSearch(CONFIG, opener=open_).search('话题', threading.Event())
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0].snippet), 2000)

    def test_searx_json_query_has_no_tavily_key(self):
        """验证 SearXNG JSON 请求不发送 Tavily 密钥。"""
        config = replace(CONFIG, search_provider='searxng', search_url='http://127.0.0.1:8080')
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            self.assertIn('/search?q=', request.full_url)
            self.assertIn('format=json', request.full_url)
            self.assertNotIn('Authorization', request.headers)
            return Response(dict(results=[dict(title=SOURCE.title, url=SOURCE.url, content=SOURCE.snippet)]))
        self.assertEqual(WebSearch(config, opener=open_).search('中文话题', threading.Event()), (SOURCE,))

    def test_missing_results_limits_rate_limit_and_network_errors(self):
        """验证无来源、响应超限、限流及网络错误都明确失败。"""
        for response in (dict(results=[]), dict(results='bad'), b'x' * (MAX_RESPONSE + 1)):
            with self.assertRaises(AgentError):
                WebSearch(CONFIG, opener=lambda *a, **k: Response(response)).search('话题', threading.Event())
        for failure in (HTTPError('https://secret', 429, 'search-secret', {}, io.BytesIO(b'secret')), URLError('search-secret')):
            def open_(*_, **__):
                """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
                raise failure
            with self.assertRaises(AgentError) as error:
                WebSearch(CONFIG, opener=open_).search('话题', threading.Event())
            self.assertNotIn('search-secret', str(error.exception))

    def test_stream_filters_reasoning_and_split_tags(self):
        """验证流式过滤推理字段及跨分片思考标签。"""
        raw = events({'delta': {'reasoning_content': '绝对不展示的思考'}},
                     {'delta': {'content': '<thi'}}, {'delta': {'content': 'nk>隐私思考</th'}},
                     {'delta': {'content': 'ink>可见'}}, {'delta': {'content': '正文'}, 'finish_reason': 'stop'})
        pieces = []
        result = read_model_text(Request('http://127.0.0.1'), threading.Event(), pieces.append,
                                 opener=lambda *a, **k: Response(raw, stream=True))
        self.assertEqual(result, '可见正文')
        self.assertGreater(len(pieces), 1)
        self.assertFalse(any('思考' in s or '<thi' in s for s in pieces))

    def test_filter_handles_every_split_position(self):
        """验证思考标签在任意分片边界都不会泄漏推理。"""
        raw = '前文<think>不保留的思考</think>后文<analysis>推理</analysis>结束'
        for split in range(len(raw)+1):
            visible = VisibleText()
            text = visible.feed(raw[:split]) + visible.feed(raw[split:]) + visible.finish()
            self.assertEqual(text, '前文后文结束', split)

    def test_stream_interruption_length_and_reasoning_only_fail(self):
        """验证流式中断、长度截断和仅推理响应都拒绝成功。"""
        for raw in (events({'delta': {'content': '未完成'}}, done=False),
                    events({'delta': {'content': '截断'}, 'finish_reason': 'length'}),
                    events({'delta': {'reasoning_content': '思考'}, 'finish_reason': 'stop'})):
            with self.assertRaises(AgentError):
                read_model_text(Request('http://127.0.0.1'), threading.Event(), lambda _:None,
                                opener=lambda *a, **k: Response(raw, stream=True))

    def test_model_stream_payload_and_plain_json_fallback(self):
        """验证流式请求参数与普通 JSON 响应兼容。"""
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            payload = json.loads(request.data)
            self.assertTrue(payload['stream'])
            self.assertTrue(payload['think'])
            self.assertEqual(payload['reasoning_effort'], 'high')
            self.assertNotIn('search-secret', request.data.decode())
            return Response(dict(choices=[dict(message=dict(content='<think>hidden</think>正文'), finish_reason='stop')]))
        self.assertEqual(CompanionModel(CONFIG, opener=open_).summarize('话题', (SOURCE,), threading.Event()), '正文')

    def test_thinking_can_be_disabled_and_plain_models_still_work(self):
        """验证可关闭思考且普通模型正常兼容。"""
        captured = []
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            captured.append(json.loads(request.data))
            return Response(dict(choices=[dict(message=dict(content='正文'), finish_reason='stop')]))
        CompanionModel(replace(CONFIG, thinking=False), opener=open_).summarize('话题', (SOURCE,), threading.Event())
        self.assertFalse(captured[0]['think'])
        self.assertEqual(captured[0]['reasoning_effort'], 'none')
        self.assertEqual(captured[0]['max_tokens'], 1200)
        CompanionModel(replace(CONFIG, provider='openai', model='gpt-4o-mini', api_key='test-only-key'), opener=open_).summarize('话题', (SOURCE,), threading.Event())
        self.assertNotIn('reasoning_effort', captured[1])

    def test_actual_langgraph_flow_and_source_preservation(self):
        """验证真实 LangGraph 行动路径保留工具取得的来源和稳定请求 ID。"""
        progress = []
        report = run_search('stable-id', '话题', FakeModel(), FakeSearch(), threading.Event(), progress.append)
        self.assertEqual(report.sources, (SOURCE,))
        self.assertEqual(report.request_id, 'stable-id')
        self.assertEqual([p.stage for p in progress], ['summarizing', 'searching', 'summarizing', 'streaming'])

    def test_model_failure_preserves_search_with_warning(self):
        """验证模型失败仍保留真实搜索来源并显示警告。"""
        model = FakeModel()
        model.answer = lambda: (_ for _ in ()).throw(AgentError('额度不足'))
        report = run_search('id', '话题', model, FakeSearch(), threading.Event(), lambda _:None)
        self.assertEqual(report.sources, (SOURCE,))
        self.assertEqual(report.warning, '额度不足')
        self.assertNotIn('整理后的回答', report.summary)

    def test_cancelled_network_keeps_lease_until_return(self):
        """验证桌宠取消期间保留租约，直到后台实际返回。"""
        entered, release = threading.Event(), threading.Event()
        class Blocking(FakeSearch):
            """按同步事件阻塞的搜索夹具，验证取消后仍保留后台准入。"""
            def search(self, topic, cancel):
                """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
                entered.set()
                release.wait(5)
                return (SOURCE,)
        service = CompanionAgentService(model_factory=FakeModel, search_factory=Blocking)
        self.addCleanup(service.close)
        self.addCleanup(release.set)
        _, future = service.search(CONFIG, '话题', lambda _:None)
        self.assertTrue(entered.wait(5))
        service.cancel()
        with self.assertRaises(AgentError): service.search(CONFIG, '重复', lambda _:None)
        release.set()
        with self.assertRaises(AgentCancelled): future.result(5)
        service.close()
        with self.assertRaises(AgentError): service.search(CONFIG, '关闭后', lambda _:None)

    def test_disabled_run_does_not_start_network(self):
        """验证智能体未启用时不构造或启动网络请求。"""
        service = CompanionAgentService(model_factory=lambda _: self.fail('不应构造网络模型'))
        with self.assertRaises(AgentError): service.search(replace(CONFIG, enabled=False), '话题', lambda _:None)


if __name__ == '__main__': unittest.main()
