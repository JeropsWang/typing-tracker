"""Browser search extraction, private-page refusal and owned process cleanup."""
import base64
import io
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.integrations.companion_agent.edge_search import EdgeSearch, SearchDOM, ArticleDOM, result_url, stop_process, browser_dom
from app.integrations.companion_agent.pages import public_page
from app.integrations.companion_agent.search import AgentError, AgentCancelled
from app.modules.companion.api import SearchSource
from app.integrations.companion_agent.relevance import split_query, focused_query, relevance

DOM = '<ol><li class="b_algo"><h2><a href="https://example.org">AI 真实来源</a></h2><p>资料摘录</p></li></ol>'


class EdgeTests(unittest.TestCase):
    """只读浏览器搜索及公开原文边界的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def test_wrong_topic_results_are_rejected_before_model(self):
        """验证无关搜索结果在模型整理前被拒绝。"""
        wrong = '<li class="b_algo"><h2><a href="https://example.org">出云市官方网站</a></h2><p>市政与旅游</p></li>'
        calls = []
        search = EdgeSearch(browser=lambda url, cancel:(calls.append(url) or wrong))
        with self.assertRaisesRegex(AgentError, '不匹配'):
            search.search('明日方舟最新干员', threading.Event())
        self.assertEqual(len(calls), 2)
        self.assertIn('cn.bing.com', calls[0])
        self.assertEqual(split_query('明日方舟最新干员'), '明日方舟 最新 干员')

    def test_savings_alias_and_keyword_retry(self):
        """验证省钱等意图别名及无关结果后的核心词重试。"""
        self.assertEqual(focused_query('如何省钱'), '省钱')
        self.assertEqual(relevance('如何省钱', SearchSource('节约开支的办法', 'https://example.org','减少支出')), 1)
        self.assertEqual(relevance('如何省钱', SearchSource('市政新闻', 'https://example.org','旅游')), 0)
        calls = []
        valid = '<li class="b_algo"><h2><a href="https://example.org">节约开支</a></h2><p>减少日常支出</p></li>'
        def browser(url, cancel):
            """返回预定搜索 DOM，验证解析/关键词行为而不启动真实浏览器。"""
            calls.append(url)
            return '<html></html>' if len(calls) == 1 else valid
        sources = EdgeSearch(browser=browser).search('如何省钱', threading.Event())
        from urllib.parse import urlsplit, parse_qs
        self.assertEqual(parse_qs(urlsplit(calls[1]).query)['q'], ['省钱'])
        self.assertEqual(urlsplit(calls[1]).hostname, 'cn.bing.com')
        self.assertEqual(sources[0].title, '节约开支')

    def test_empty_search_has_distinct_error_from_irrelevant_search(self):
        """验证无搜索结果与全部跑题结果分别提示。"""
        with self.assertRaisesRegex(AgentError, '没有返回'):
            EdgeSearch(browser=lambda *_:'<html></html>').search('如何省钱', threading.Event())

    def test_related_sources_keep_entity_and_exclude_similar_game(self):
        """验证主题实体匹配保留相关来源，排除名称相似的其他游戏。"""
        self.assertEqual(relevance('明日方舟最新干员', SearchSource('明日方舟官网', 'https://example.org','干员公告')), 1)
        self.assertLess(relevance('明日方舟最新干员', SearchSource('明日之后', 'https://example.org','最新干员')), .75)
        valid = '<li class="b_algo"><h2><a href="https://example.org">明日方舟 Wiki</a></h2><p>干员资料</p></li>'
        wrong = '<li class="b_algo"><h2><a href="https://other.org">知网</a></h2><p>期刊</p></li>'
        calls = []
        search = EdgeSearch(browser=lambda url, cancel:(calls.append(url) or (wrong if len(calls)==1 else valid)))
        self.assertEqual(search.search('明日方舟最新干员', threading.Event())[0].title, '明日方舟 Wiki')
        self.assertEqual(len(calls), 2)

    def test_search_uses_rendered_dom_not_rss(self):
        """验证 Edge 适配器读取实际渲染 DOM，未伪装为 RSS 搜索。"""
        calls = []
        search = EdgeSearch(browser=lambda url, cancel:(calls.append(url) or DOM))
        sources = search.search('今天 AI 新闻', threading.Event())
        self.assertIn('q=', calls[0])
        self.assertNotIn('format=rss', calls[0])
        self.assertEqual(sources[0].title, 'AI 真实来源')
        self.assertEqual(sources[0].snippet, '资料摘录')

    def test_decodes_click_links_and_deduplicates_unsafe_results(self):
        """验证搜索点击包装链接解码、去重及非法来源过滤。"""
        encoded = base64.urlsafe_b64encode(b'https://example.org').decode().rstrip('=')
        self.assertEqual(result_url('https://www.bing.com/ck/a?u=a1'+encoded), 'https://example.org')
        self.assertEqual(result_url('javascript:alert(1)'), '')
        sources = EdgeSearch(browser=lambda *_:DOM+DOM).search('AI 新闻', threading.Event())
        self.assertEqual(len(sources), 1)
        with self.assertRaisesRegex(AgentError, '验证'):
            EdgeSearch(browser=lambda *_:'<html>captcha</html>').search('AI 新闻', threading.Event())

    def test_article_discards_scripts_and_navigation(self):
        """验证正文解析排除脚本、样式及页面导航。"""
        parser = ArticleDOM()
        parser.feed('<nav><p>导航</p></nav><main><h1>标题</h1><p>正文<script>隐藏</script>内容</p></main>')
        self.assertEqual(parser.text, ['标题','正文','内容'])

    def test_enrich_reads_only_two_sources_preserves_failures(self):
        """验证兼容补正文路径只尝试前两条，失败保留原摘录。"""
        sources = EdgeSearch(browser=lambda *_:DOM).search('AI 新闻', threading.Event()) * 5
        with patch('app.integrations.companion_agent.pages.article_excerpt', side_effect=['正文','']) as read:
            result = EdgeSearch().enrich(sources, threading.Event())
        self.assertEqual(read.call_count, 2)
        self.assertIn('正文节选：正文', result[0].snippet)
        self.assertEqual(result[1:], sources[1:])

    def test_private_and_non_https_pages_never_read(self):
        """验证内网及非 HTTPS 来源不执行正文读取。"""
        with patch('socket.getaddrinfo', return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]):
            with self.assertRaises(AgentError): public_page('https://example.org')
        for url in ('file:///secret','http://example.org','https://user:pass@example.org'):
            with self.assertRaises(AgentError): public_page(url)

    def test_fake_ip_requires_configured_https_proxy_and_domain(self):
        """验证 Fake-IP 例外只用于配置 HTTPS 代理的公开域名映射。"""
        addresses = [(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.2',443))]
        with patch('socket.getaddrinfo', return_value=addresses), patch('app.integrations.companion_agent.pages.getproxies', return_value={}):
            with self.assertRaises(AgentError): public_page('https://example.org')
        with patch('socket.getaddrinfo', return_value=addresses), patch('app.integrations.companion_agent.pages.getproxies', return_value={'https':'http://127.0.0.1:7890'}):
            public_page('https://example.org')
            with self.assertRaises(AgentError): public_page('https://198.18.0.2')

    def test_cancel_before_browser_does_not_spawn(self):
        """验证预先取消的搜索不会启动浏览器进程。"""
        cancel = threading.Event(); cancel.set()
        with patch('app.integrations.companion_agent.edge_search.edge_executable', return_value=Path('edge.exe')), \
             patch('subprocess.Popen') as start:
            with self.assertRaises(AgentCancelled): browser_dom('https://www.bing.com', cancel)
        start.assert_not_called()

    def test_stop_targets_only_owned_process(self):
        """验证清理浏览器仅作用于本次拥有的进程。"""
        process = Mock(pid=12345); process.poll.return_value = None
        with patch('subprocess.run') as run:
            stop_process(process)
        if sys.platform == 'win32':
            self.assertEqual(run.call_args.args[0], ['taskkill','/PID','12345','/T','/F'])
        process.wait.assert_called_once()

    def test_locked_profile_cleanup_does_not_replace_successful_dom(self):
        """Edge 子进程暂占配置目录时，清理竞争不应吞掉已经取得的搜索正文。"""
        class LockedDirectory:
            """模拟 Windows 临时目录的尽力清理协议，不创建真实浏览器或私人目录。"""
            def __init__(self, *args, ignore_cleanup_errors=False, **kwargs):
                """记录临时目录对残留文件占用的处理策略。"""
                self.ignore = ignore_cleanup_errors
            def __enter__(self):
                """返回仅用于组装命令的夹具目录。"""
                return 'isolated-profile'
            def __exit__(self, *args):
                """模拟已有成功输出，但 Windows 删除非空目录时发生145竞争。"""
                if not self.ignore:
                    raise OSError(41, 'fixture directory not empty')
        process = Mock(returncode=0)
        process.poll.return_value = 0
        with patch('app.integrations.companion_agent.edge_search.edge_executable', return_value=Path('edge.exe')), \
             patch('app.integrations.companion_agent.edge_search.tempfile.TemporaryDirectory', LockedDirectory), \
             patch('app.integrations.companion_agent.edge_search.tempfile.TemporaryFile', return_value=io.BytesIO(DOM.encode())), \
             patch('subprocess.Popen', return_value=process):
            self.assertEqual(browser_dom('https://www.bing.com', threading.Event()), DOM)


if __name__ == '__main__': unittest.main()
