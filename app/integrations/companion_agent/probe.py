"""源码/冻结发布共用的智能体运行自检；使用固定夹具，不联网、不打开用户库。"""
import threading
from .search import parse_public_results
from .edge_search import SearchDOM
from .relevance import relevance
from ...modules.companion.api import SearchSource, AgentTurn, AgentToolCall
from .graph import run_search
from .stream import VisibleText


def selfcheck():
    """执行真实图/MCP 路径及解析/过滤夹具；失败抛异常，成功返回能力检查标记。"""
    source = SearchSource('runtime probe', 'https://example.org', 'runtime probe')
    class Search:
        """无网络搜索夹具，让自检能检测真实工具执行与来源保留。"""
        def search(self, topic, cancel):
            """返回固定公开来源，不发起任何外部请求。"""
            return (source,)
    class Model:
        """无模型服务夹具，模拟选择工具、接收观察、生成引用答案的两轮流程。"""
        def turn(self, messages, tools, cancel, on_text=lambda _: None):
            """首轮请求搜索，收到工具观察后结束；验证图不是固定摘要调用。"""
            if messages[-1]['role'] != 'tool':
                return AgentTurn(tool_calls=(AgentToolCall('probe', 'web_search', '{"query":"runtime probe"}'),))
            return AgentTurn('runtime probe [1]')
    progress = []
    report = run_search('runtime-probe', 'runtime probe', Model(), Search(), threading.Event(), progress.append)
    visible = VisibleText()
    text = visible.feed('<thi') + visible.feed('nk>discard</think>visible') + visible.finish()
    if report.summary != 'runtime probe [1]' or report.sources != (source,) or text != 'visible':
        raise RuntimeError('Companion agent runtime verification failed')
    sources = parse_public_results(b'<rss><channel><item><title>probe</title><link>https://example.org</link><description>snippet</description></item></channel></rss>')
    if len(sources) != 1:
        raise RuntimeError('Missing public search parser')
    dom = SearchDOM()
    dom.feed('<li class="b_algo"><h2><a href="https://example.org">probe</a></h2><p>snippet</p></li>')
    if not dom.rows or dom.rows[0]['url'] != 'https://example.org':
        raise RuntimeError('Missing Edge DOM parser')
    if relevance('明日方舟最新干员', SearchSource('出云市官网', 'https://example.org', '旅游与市政')) >= .75:
        raise RuntimeError('Unrelated search evidence accepted')
    return dict(langgraph=True, react=True, mcp_tools=True, stream_filter=True,
                public_search=True, edge_parser=True, network=False, database=False)
