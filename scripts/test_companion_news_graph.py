"""真实 LangGraph 来信与准入回归；模型和搜索为确定夹具，不访问付费接口。"""
from dataclasses import replace
import json
import threading
import unittest

from test_companion_agent import FakeModel, FakeSearch, CONFIG, SOURCE
from app.modules.companion.api import NewsRequest, AgentBusyError, AgentTurn, SearchSource
from app.integrations.companion_agent.service import CompanionAgentService
from app.integrations.companion_agent.search import AgentCancelled, AgentError


class RecordingModel(FakeModel):
    """记录实际图传入的模型消息及工具声明，不在服务之外替代行动循环。"""
    def __init__(self):
        """建立本例消息台账，内部不接收真实用户配置。"""
        self.requests = []

    def turn(self, messages, tools, cancel, on_text=lambda _: None):
        """保留消息副本并沿用真实夹具的搜索行动与结果整理。"""
        self.requests.append((list(messages), tools))
        return super().turn(messages, tools, cancel, on_text)


class NewsGraphTests(unittest.TestCase):
    """防止来信绕过图执行、泄漏配置或与主动搜索并发占用上游。"""
    def request(self):
        """构造明确兴趣和固定当地日，不从统计或历史搜索推导画像。"""
        return NewsRequest(('人工智能', '游戏'), '2026-10-20')

    def test_news_mode_uses_date_interests_and_existing_tools(self):
        """真实图收到专用来信契约，仍只向模型开放两个白名单工具。"""
        model = RecordingModel()
        service = CompanionAgentService(model_factory=lambda _: model, search_factory=FakeSearch)
        self.addCleanup(service.close)
        _, future = service.news(CONFIG, self.request(), lambda _: None)
        report = future.result(10)
        messages, tools = model.requests[0]
        payload = json.loads(messages[-1]['content'])
        self.assertEqual(payload['task_type'], 'news')
        self.assertEqual(payload['local_date'], '2026-10-20')
        self.assertEqual(payload['interests'], ['人工智能', '游戏'])
        self.assertEqual({item['function']['name'] for item in tools}, {'web_search', 'read_webpage'})
        self.assertEqual(report.sources, (SOURCE,))
        self.assertIn('2026-10-20', report.topic)
        self.assertEqual(len(model.requests), 2)

    def test_search_and_news_share_admission_until_cancelled_io_ends(self):
        """取消来信不提前释放阻塞工具的准入，主动搜索必须等待网络真正结束。"""
        entered, release = threading.Event(), threading.Event()
        class BlockingSearch(FakeSearch):
            """只在受控事件释放后返回，不响应取消以模拟尚未结束的底层 I/O。"""
            def search(self, topic, cancel):
                """保留真实在途窗口供并发准入观察。"""
                entered.set()
                release.wait(5)
                return (SOURCE,)
        service = CompanionAgentService(model_factory=FakeModel, search_factory=BlockingSearch)
        self.addCleanup(service.close)
        self.addCleanup(release.set)
        request_id, future = service.news(CONFIG, self.request(), lambda _: None)
        self.assertTrue(entered.wait(10))
        self.assertTrue(service.cancel(request_id))
        self.assertTrue(service.busy)
        with self.assertRaises(AgentBusyError):
            service.search(CONFIG, '另一个话题', lambda _: None)
        with self.assertRaises(AgentError):
            service.news(CONFIG, self.request(), lambda _: None)
        release.set()
        with self.assertRaises(AgentCancelled):
            future.result(5)
        self.assertFalse(service.busy)

    def test_stale_owner_cannot_cancel_active_search(self):
        """旧来信请求 ID 无权取消当前主动搜索，成功结果仍能返回。"""
        entered, release = threading.Event(), threading.Event()
        class BlockingSearch(FakeSearch):
            """为错误所有者取消测试保留一个真实准入中的工具调用。"""
            def search(self, topic, cancel):
                """阻塞到显式释放，不读取外部数据。"""
                entered.set()
                release.wait(5)
                return (SOURCE,)
        service = CompanionAgentService(model_factory=FakeModel, search_factory=BlockingSearch)
        self.addCleanup(service.close)
        self.addCleanup(release.set)
        _, future = service.search(CONFIG, '主动搜索', lambda _: None)
        self.assertTrue(entered.wait(10))
        self.assertFalse(service.cancel('old-news-request'))
        self.assertTrue(service.busy)
        release.set()
        self.assertEqual(future.result(5).summary, '整理后的回答 [1]')

    def test_news_payload_never_contains_credentials_or_passive_profile(self):
        """模型消息只含角色、主动兴趣与工具证据，配置 Key 不进入提示词或报告。"""
        model = RecordingModel()
        service = CompanionAgentService(model_factory=lambda _: model, search_factory=FakeSearch)
        self.addCleanup(service.close)
        _, future = service.news(replace(CONFIG, api_key='PRIVATE-MODEL', search_key='PRIVATE-SEARCH'),
                                  self.request(), lambda _: None)
        report = future.result(10)
        text = json.dumps(model.requests, ensure_ascii=False) + repr(report)
        self.assertNotIn('PRIVATE-MODEL', text)
        self.assertNotIn('PRIVATE-SEARCH', text)
        self.assertEqual(set(json.loads(model.requests[0][0][-1]['content'])), {'task_type', 'local_date', 'interests'})

    def test_no_sources_cannot_become_a_successful_news_report(self):
        """来源为空时即使模型给出答案，也不能被记录为成功来信。"""
        class EmptySearch(FakeSearch):
            """始终无资料的工具夹具，验证真实图的证据不足路径。"""
            def search(self, topic, cancel):
                """返回空来源，不以模型常识补造新闻。"""
                return ()
        service = CompanionAgentService(model_factory=FakeModel, search_factory=EmptySearch)
        self.addCleanup(service.close)
        _, future = service.news(CONFIG, self.request(), lambda _: None)
        with self.assertRaises(AgentError):
            future.result(10)

    def test_missing_dates_are_not_labeled_today(self):
        """图保留来源的未注明日期状态，计划日／检索时间不覆盖网页资料。"""
        source = SearchSource('未注明日期的资料', 'https://example.org/undated', '未注明发布日期')
        class UndatedSearch(FakeSearch):
            """返回没有发布日期字段的真实形状来源。"""
            def search(self, topic, cancel):
                """提供未标日期的工具观察，由模型按来信日期规则判断。"""
                return (source,)
        class CautiousModel(RecordingModel):
            """返回明确标注日期未核实的可见正文，验证图不擅自改写成今日新闻。"""
            def answer(self):
                """提供谨慎回答，不将计划日当来源发布日期。"""
                return AgentTurn('资料日期未核实，暂不能确认是今日动态 [1]')
        model = CautiousModel()
        service = CompanionAgentService(model_factory=lambda _: model, search_factory=UndatedSearch)
        self.addCleanup(service.close)
        _, future = service.news(CONFIG, self.request(), lambda _: None)
        report = future.result(10)
        self.assertEqual(report.sources, (source,))
        self.assertIn('日期未核实', report.summary)
        self.assertEqual(json.loads(model.requests[0][0][-1]['content'])['local_date'], '2026-10-20')
        self.assertTrue(report.fetched_at.endswith('+00:00'))

    def test_real_sources_allow_partial_report_with_warning(self):
        """图在已有真实来源后失败时保留带警告报告，供持久层和界面明确解释。"""
        class FailedSummary(FakeModel):
            """取得来源后模拟上游整理失败，不抛含秘密的未知异常。"""
            def answer(self):
                """以受控公开错误中止整理，让图的部分结果分支处理。"""
                raise AgentError('整理暂时中断')
        service = CompanionAgentService(model_factory=FailedSummary, search_factory=FakeSearch)
        self.addCleanup(service.close)
        _, future = service.news(CONFIG, self.request(), lambda _: None)
        report = future.result(10)
        self.assertEqual(report.sources, (SOURCE,))
        self.assertTrue(report.warning)


if __name__ == '__main__':
    unittest.main()
