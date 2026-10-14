"""Actual graph and protocol boundaries; deterministic providers, no external I/O."""
from dataclasses import replace
import json
import threading
import unittest
from urllib.request import Request

from test_companion_agent import Response, events, CONFIG, SOURCE
from app.modules.companion.api import AgentTurn, AgentToolCall, AgentRunLimits, SearchSource
from app.integrations.companion_agent.graph import run_search, RunSignal
from app.integrations.companion_agent.mcp_tools import SearchMcpServer, McpToolClient, PROTOCOL_VERSION
from app.integrations.companion_agent.model import CompanionModel
from app.integrations.companion_agent.stream import read_model_turn
from app.integrations.companion_agent.search import AgentError, AgentCancelled


def action(identifier, name='web_search', **arguments):
    """构造带稳定 ID 和 JSON 参数的工具行动轮次。"""
    return AgentTurn(tool_calls=(AgentToolCall(identifier, name, json.dumps(arguments, ensure_ascii=False)),))


class SequenceModel:
    """按预定顺序返回模型轮次并记录上下文，验证真正行动循环。"""
    def __init__(self, *turns):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        self.turns, self.requests = list(turns), []

    def turn(self, messages, tools, cancel, on_text=lambda _: None):
        """返回预定原生模型轮次，验证工具行动/观察续接，不调用真实模型。"""
        self.requests.append(json.loads(json.dumps(messages)))
        if not self.turns:
            raise AssertionError('Unexpected model round')
        return self.turns.pop(0)


class Search:
    """本用例搜索替身，记录查询并按设定返回来源或失败。"""
    def __init__(self):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        self.queries = []
    def search(self, query, cancel):
        """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
        self.queries.append(query)
        return (SOURCE,)


class CompanionReActTests(unittest.TestCase):
    """实际 LangGraph/MCP 行动循环的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def run_agent(self, model, search=None, **options):
        """用确定性模型/搜索夹具执行实际图，返回报告供行动边界断言。"""
        return run_search('react-test', '用户原问题', model, search or Search(),
                          threading.Event(), lambda _: None, **options)

    def client(self, search=None, reader=None, limits=None):
        """装配本例进程内 MCP 工具服务与客户端，外部 I/O 用夹具替代。"""
        server = SearchMcpServer(search or Search(), threading.Event(), limits or AgentRunLimits(),
                                 lambda *_: None, reader=reader)
        return McpToolClient(server)

    def test_model_selects_queries_reads_and_supplements_with_stable_citations(self):
        """验证模型自主改词、选择原文和补搜，来源引用编号稳定。"""
        other = SearchSource('第二条', 'https://example.org/other', '补充资料')
        class Supplement(Search):
            """为补搜用例提供第二组来源的搜索夹具，检查稳定去重编号。"""
            def search(self, query, cancel):
                """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
                self.queries.append(query)
                return (SOURCE,) if len(self.queries) == 1 else (other, SOURCE)
        search, reads = Supplement(), []
        def reader(url, cancel):
            """返回预定原文或取消/失败，验证来源读取，不请求公开网站。"""
            reads.append(url); return '网页标注日期：2026-10-14\n核对后的原文节选'
        model = SequenceModel(action('a', query='由模型拆出的关键词'),
                              action('b', 'read_webpage', source_id=1),
                              action('c', query='进一步核对的关键词'), AgentTurn('综合结果 [1] [2]'))
        report = self.run_agent(model, search, reader=reader)
        self.assertEqual(search.queries, ['由模型拆出的关键词', '进一步核对的关键词'])
        self.assertEqual(reads, [SOURCE.url])
        self.assertEqual([s.url for s in report.sources], [SOURCE.url, other.url])
        self.assertIn('核对后的原文节选', report.sources[0].snippet)
        observation = json.loads(model.requests[-1][-1]['content'])['structuredContent']
        self.assertEqual([s['source_id'] for s in observation['sources']], [2, 1])
        self.assertIn('你是 Sariana', model.requests[0][0]['content'])
        self.assertEqual(report.warning, '')

    def test_failed_search_becomes_observation_and_model_can_recover(self):
        """验证搜索失败回到模型观察，下一轮可改写恢复。"""
        class Recover(Search):
            """首轮故意失败、后轮返回来源的搜索夹具，验证模型能修正行动。"""
            def search(self, query, cancel):
                """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
                self.queries.append(query)
                if len(self.queries) == 1: raise AgentError('没有相关来源')
                return (SOURCE,)
        search = Recover()
        model = SequenceModel(action('a', query='不相关词'), action('b', query='改写关键词'), AgentTurn('有证据了 [1]'))
        report = self.run_agent(model, search)
        self.assertTrue(json.loads(model.requests[1][-1]['content'])['isError'])
        self.assertEqual(len(search.queries), 2)
        self.assertEqual(report.summary, '有证据了 [1]')

    def test_schema_error_is_repairable_without_executing_io(self):
        """验证非法工具参数先反馈错误，模型修正后才执行 I/O。"""
        search = Search()
        model = SequenceModel(action('bad', query=123), action('good', query='有效查询'), AgentTurn('回答 [1]'))
        self.run_agent(model, search)
        self.assertEqual(search.queries, ['有效查询'])
        self.assertTrue(json.loads(model.requests[1][-1]['content'])['isError'])

    def test_mcp_lifecycle_and_protocol_errors(self):
        """验证进程内 MCP 初始化顺序、工具发现和协议错误码。"""
        server = SearchMcpServer(Search(), threading.Event(), AgentRunLimits(), lambda *_: None)
        def rpc(method, params={}):
            """向本机工具服务发送受控 JSON-RPC 请求，检查生命周期和协议错误。"""
            return server.dispatch(dict(jsonrpc='2.0', id=1, method=method, params=params))
        self.assertEqual(rpc('tools/list')['error']['code'], -32600)
        self.assertEqual(rpc('initialize', dict(protocolVersion='bad'))['error']['code'], -32602)
        result = rpc('initialize', dict(protocolVersion=PROTOCOL_VERSION))['result']
        self.assertEqual(result['capabilities'], {'tools': {}})
        server.dispatch(dict(jsonrpc='2.0', method='notifications/initialized'))
        self.assertEqual(len(rpc('tools/list')['result']['tools']), 2)
        self.assertEqual(rpc('unknown')['error']['code'], -32601)
        self.assertEqual(rpc('tools/call', dict(name=[]))['error']['code'], -32602)

    def test_only_registered_tools_and_existing_source_ids_are_executable(self):
        """验证只有白名单工具和已取得的来源编号可执行。"""
        reads = []
        client = self.client(reader=lambda url, _: reads.append(url) or '节选')
        for name, arguments in [('bash', '{}'), ('read_webpage', '{"url":"https://example.org"}'),
                                 ('read_webpage', '{"source_id":true}'), ('read_webpage', '{"source_id":8}'),
                                 ('web_search', '{"query":"ok","extra":1}'), ('web_search', 'not JSON')]:
            self.assertTrue(client.execute(AgentToolCall('id', name, arguments))['isError'])
        self.assertEqual(reads, [])
        self.assertEqual(client.server.search.queries, [])

    def test_failed_page_retains_snippet_and_reports_it_is_not_full_text(self):
        """验证原文读取失败保留摘录，并说明不能当作全文。"""
        client = self.client(reader=lambda *_: '')
        client.execute(AgentToolCall('a', 'web_search', '{"query":"有效查询"}'))
        result = client.execute(AgentToolCall('b', 'read_webpage', '{"source_id":1}'))
        self.assertTrue(result['isError'])
        self.assertIn('勿声称读过原文', result['content'][0]['text'])
        self.assertEqual(client.server.sources, [SOURCE])

    def test_repeated_actions_use_cached_observations(self):
        """验证完全重复行动复用观察，不再次请求网络。"""
        search = Search()
        model = SequenceModel(action('a', query='相同关键词'), action('b', query='相同关键词'), AgentTurn('回答 [1]'))
        self.run_agent(model, search)
        self.assertEqual(search.queries, ['相同关键词'])
        self.assertEqual(model.requests[1][-1]['content'], model.requests[2][-1]['content'])

    def test_no_search_evidence_cannot_be_presented_as_a_report(self):
        """验证无工具证据时不能把模型记忆显示为联网报告。"""
        model = SequenceModel(AgentTurn('我记得的最新消息'), AgentTurn('假装搜索成功了'))
        report = self.run_agent(model)
        self.assertEqual(report.sources, ())
        self.assertTrue(report.warning)
        self.assertNotIn('假装', report.summary)
        self.assertEqual(len(model.requests), 2)

    def test_invalid_citation_is_corrected_once_then_blocked_if_still_invalid(self):
        """验证错误来源编号仅修正一次，仍非法则拒绝报告。"""
        for corrected, succeeds in [('可核对的结论 [1]', True), ('伪造来源 [9]', False)]:
            model = SequenceModel(action('a', query='资料'), AgentTurn('结论 [9]'), AgentTurn(corrected))
            report = self.run_agent(model)
            self.assertEqual(not bool(report.warning), succeeds)
            self.assertNotIn('[9]', report.summary)
            self.assertEqual(report.sources, (SOURCE,))

    def test_turn_budget_stops_before_useless_additional_io(self):
        """验证无剩余判断轮次时停止无用的后续工具请求。"""
        search = Search()
        model = SequenceModel(action('a', query='第一轮'), action('b', query='不应执行'))
        report = self.run_agent(model, search, limits=replace(AgentRunLimits(), model_turns=2))
        self.assertEqual(search.queries, ['第一轮'])
        self.assertIn('上限', report.warning)

    def test_action_budget_also_counts_malformed_calls(self):
        """验证错误参数也消耗工具预算，不能借校验失败无限重试。"""
        search = Search()
        model = SequenceModel(AgentTurn(tool_calls=(AgentToolCall('a', 'bash', '{}'),
            AgentToolCall('b', 'web_search', '{"query":"不应执行"}'))))
        report = self.run_agent(model, search, limits=replace(AgentRunLimits(), tool_calls=1))
        self.assertEqual(search.queries, [])
        self.assertIn('工具调用上限', report.warning)

    def test_search_budget_returns_observation_without_second_engine_call(self):
        """验证搜索预算已耗尽时返回错误观察，不执行第二次上游查询。"""
        search = Search()
        model = SequenceModel(action('a', query='第一轮'), action('b', query='第二轮'), AgentTurn('已有证据 [1]'))
        self.run_agent(model, search, limits=replace(AgentRunLimits(), searches=1))
        self.assertEqual(search.queries, ['第一轮'])
        self.assertTrue(json.loads(model.requests[-1][-1]['content'])['isError'])

    def test_duplicate_call_identifier_stops_before_reexecution(self):
        """验证模型重复工具 ID 在重新执行前被阻止。"""
        search = Search()
        report = self.run_agent(SequenceModel(action('a', query='第一轮'), action('a', query='第二轮')), search)
        self.assertEqual(search.queries, ['第一轮'])
        self.assertIn('重复', report.warning)

    def test_cancel_during_page_read_stops_next_model_round(self):
        """验证原文读取期间取消阻止下一轮模型调用。"""
        cancel = threading.Event()
        def reader(*_):
            """返回预定原文或取消/失败，验证来源读取，不请求公开网站。"""
            cancel.set(); return '迟到的原文'
        model = SequenceModel(action('a', query='资料'), action('b', 'read_webpage', source_id=1))
        with self.assertRaises(AgentCancelled):
            run_search('cancel', '问题', model, Search(), cancel, lambda _: None, reader=reader)
        self.assertEqual(len(model.requests), 2)

    def test_context_budget_stops_before_model_request(self):
        """验证上下文超限时不继续发模型请求。"""
        model = SequenceModel()
        report = self.run_agent(model, limits=replace(AgentRunLimits(), context_chars=1))
        self.assertIn('上下文上限', report.warning)
        self.assertEqual(model.requests, [])

    def test_deadline_and_user_cancellation_are_distinct(self):
        """验证任务截止与用户取消具有不同错误语义。"""
        cancel = threading.Event()
        signal = RunSignal(cancel, -1)
        with self.assertRaisesRegex(AgentError, '用时太久'): signal.is_set()
        cancel.set()
        self.assertTrue(signal.is_set())

    def test_sse_native_tools_are_reassembled_and_reasoning_stays_private(self):
        """验证 SSE 工具参数分片正确合并，协议推理不进入可见结果。"""
        raw = events({'delta': {'reasoning_content':'private-replay-value'}},
            {'delta': {'tool_calls':[{'index':0,'id':'call-1','type':'function',
                                      'function':{'name':'web_search','arguments':'{"query":"'}}]}},
            {'delta': {'tool_calls':[{'index':0,'function':{'arguments':'中文"}'}}]}, 'finish_reason':'tool_calls'})
        pieces = []
        turn = read_model_turn(Request('http://127.0.0.1'), threading.Event(), pieces.append,
                               opener=lambda *_a, **_k: Response(raw, stream=True))
        self.assertEqual(json.loads(turn.tool_calls[0].arguments), {'query':'中文'})
        self.assertEqual(turn.reasoning, 'private-replay-value')
        self.assertNotIn('private-replay-value', repr(turn))
        self.assertEqual(pieces, [])
        replay = CompanionModel.assistant_message(turn)
        captured = []
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            captured.append(json.loads(request.data))
            return Response(dict(choices=[dict(message=dict(content='回答 [1]'), finish_reason='stop')]))
        config = replace(CONFIG, provider='deepseek', model='deepseek-chat', api_key='isolated-test-key')
        model = CompanionModel(config, opener=open_)
        client = self.client()
        result = client.execute(turn.tool_calls[0])
        model.turn([replay, dict(role='tool', tool_call_id='call-1', content=json.dumps(result))],
                   client.declarations(), threading.Event())
        self.assertEqual(captured[0]['messages'][0]['reasoning_content'], 'private-replay-value')
        self.assertEqual(captured[0]['tools'][0]['function']['parameters']['required'], ['query'])
        self.assertNotIn('search-secret', json.dumps(captured))

    def test_truncated_tool_call_and_incomplete_stream_never_execute(self):
        """验证截断工具行动或未完成流式响应不会执行工具 I/O。"""
        for finish in ('length', None):
            raw = events(dict(delta=dict(tool_calls=[dict(index=0, id='a', type='function',
                function=dict(name='web_search', arguments='{"query":"资料"}'))]), finish_reason=finish), done=False)
            search = Search()
            model = CompanionModel(CONFIG, opener=lambda *_a, **_k: Response(raw, stream=True))
            with self.assertRaises(AgentError): self.run_agent(model, search)
            self.assertEqual(search.queries, [])

    def test_native_provider_mcp_graph_and_streamed_report_work_together(self):
        """用模拟传输验证原生工具协议、MCP、实际图和正文进度完整协作。"""
        requests, progress = [], []
        def open_(request, timeout):
            """替代上游传输，按当前用例校验请求并返回预定响应或失败。"""
            payload = json.loads(request.data)
            requests.append(payload)
            if len(requests) == 1:
                self.assertEqual(payload['messages'][0]['role'], 'system')
                return Response(events(dict(delta=dict(tool_calls=[dict(index=0, id='native-1', type='function',
                    function=dict(name='web_search', arguments='{"query":"模型选择的关键词"}'))]),
                    finish_reason='tool_calls')), stream=True)
            self.assertEqual(payload['messages'][-2]['tool_calls'][0]['id'], 'native-1')
            observation = json.loads(payload['messages'][-1]['content'])
            self.assertEqual(observation['structuredContent']['sources'][0]['source_id'], 1)
            return Response(events(dict(delta=dict(reasoning_content='private-protocol')),
                dict(delta=dict(content='<think>hidden</think>真实资料')),
                dict(delta=dict(content='回答 [1]'), finish_reason='stop')), stream=True)
        search = Search()
        model = CompanionModel(CONFIG, opener=open_)
        report = run_search('native', '用户问题', model, search, threading.Event(), progress.append)
        self.assertEqual(search.queries, ['模型选择的关键词'])
        self.assertEqual(report.summary, '真实资料回答 [1]')
        self.assertEqual(report.sources, (SOURCE,))
        self.assertGreaterEqual(sum(p.stage == 'streaming' for p in progress), 2)
        self.assertFalse(any('hidden' in p.text or 'private-protocol' in p.text for p in progress))
        self.assertNotIn('private-protocol', repr(report))
        self.assertNotIn('search-secret', json.dumps(requests))


if __name__ == '__main__': unittest.main()
