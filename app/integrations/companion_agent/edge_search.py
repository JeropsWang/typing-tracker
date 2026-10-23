"""Read public search DOM with an isolated, owned headless Edge process."""
from dataclasses import replace
from html.parser import HTMLParser
import base64
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlencode, urlsplit, parse_qs
from ...modules.companion.api import SearchSource
from .search import AgentError, check_cancel, source_url, MAX_RESPONSE
from .relevance import split_query, focused_query, relevance


def edge_executable():
    """在本机已安装位置查找 Edge，可用性不足时提示改用其他搜索，不安装浏览器。"""
    for directory in (os.environ.get('PROGRAMFILES(X86)'), os.environ.get('PROGRAMFILES'),
                      os.environ.get('LOCALAPPDATA')):
        if directory:
            path = Path(directory) / 'Microsoft/Edge/Application/msedge.exe'
            if path.is_file():
                return path
    raise AgentError('未找到 Microsoft Edge，请安装 Edge，或切换轻量网页搜索、Tavily 或已有 SearXNG。', code='configuration')


def stop_process(process):
    """只结束本次拥有的浏览器进程及其子进程，避免关闭用户正在使用的浏览器。"""
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            process.kill()
        process.wait(timeout=10)


def browser_dom(url, cancel):
    """用独立临时配置取得有界 DOM；清理自己进程，配置目录占用不覆盖正文或主异常。"""
    executable = edge_executable()
    check_cancel(cancel)
    # Windows 子进程退出后可能短暂占用目录（实测 WinError145）；尽力清理不能覆盖搜索结果。
    with tempfile.TemporaryDirectory(prefix='sariana-edge-', ignore_cleanup_errors=True) as directory:
        profile = Path(directory) / 'profile'
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen([str(executable), '--headless=new', '--disable-gpu',
                '--no-first-run', '--no-default-browser-check', '--disable-extensions',
                '--disable-background-networking', '--user-data-dir=' + str(profile),
                '--dump-dom', '--timeout=15000', '--virtual-time-budget=3000', url],
                stdout=output, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            deadline = time.monotonic() + 30
            try:
                while process.poll() is None:
                    check_cancel(cancel)
                    if time.monotonic() >= deadline or output.tell() > MAX_RESPONSE:
                        raise AgentError('Edge 页面加载超时或内容过大，请稍后重试。', code='timeout')
                    cancel.wait(.1)
                check_cancel(cancel)
                output.seek(0)
                raw = output.read(MAX_RESPONSE + 1)
                if process.returncode or len(raw) > MAX_RESPONSE:
                    raise AgentError('Edge 未能读取搜索页面，请检查网络后重试。', code='connection')
                return raw.decode('utf-8', errors='replace')
            finally:
                stop_process(process)


def result_url(url):
    """Decode Bing's public click wrapper; never hand it to the model as evidence."""
    parsed = urlsplit(url)
    if parsed.hostname and parsed.hostname.endswith('bing.com') and parsed.path == '/ck/a':
        value = parse_qs(parsed.query).get('u', [''])[0]
        if value.startswith('a1'):
            try:
                encoded = value[2:]
                url = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)).decode('utf-8')
            except (ValueError, UnicodeError):
                return ''
    return source_url(url)


class SearchDOM(HTMLParser):
    """中文搜索结果的纯 HTML 提取器，仅保留结果标题、链接与摘要，不执行脚本。"""
    def __init__(self):
        """初始化结果行和标题/段落/隐藏区深度。"""
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.depth = 0
        self.heading = 0
        self.paragraph = 0
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        """定位结果列表项和标题链接，记录段落及不可读脚本区域。"""
        attrs = dict(attrs)
        if tag == 'li' and 'b_algo' in attrs.get('class', '').split():
            self.row = dict(title=[], content=[], url='')
            self.depth = 1
        elif self.row is not None and tag == 'li':
            self.depth += 1
        if self.row is None:
            return
        if tag == 'h2': self.heading += 1
        if tag == 'p': self.paragraph += 1
        if tag in ('script', 'style'): self.hidden += 1
        if tag == 'a' and self.heading and not self.row['url']:
            self.row['url'] = result_url(attrs.get('href', ''))

    def handle_endtag(self, tag):
        """结束结果及文本区域，完整行才进入候选来源列表。"""
        if self.row is None: return
        if tag == 'h2': self.heading = max(0, self.heading - 1)
        if tag == 'p': self.paragraph = max(0, self.paragraph - 1)
        if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
        if tag == 'li':
            self.depth -= 1
            if self.depth == 0:
                self.rows.append(self.row)
                self.row = None
                self.heading = self.paragraph = self.hidden = 0

    def handle_data(self, data):
        """仅收集可见标题/段落文字，脚本和样式内容忽略。"""
        if self.row is not None and not self.hidden:
            if self.heading: self.row['title'].append(data)
            elif self.paragraph: self.row['content'].append(data)


class ArticleDOM(HTMLParser):
    """公开原文的纯 HTML 摘录器，提取正文和网页标注日期，排除导航/脚本。"""
    def __init__(self):
        """创建标签栈、正文片段和网页日期集合。"""
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = []
        self.dates = []

    def handle_starttag(self, tag, attrs):
        """记录正文上下文和 time/meta 日期，避免把当前请求时间当发布日期。"""
        values = dict(attrs)
        if tag == 'time' and values.get('datetime'):
            self.dates.append(values['datetime'][:80])
        if tag == 'meta' and values.get('property') in ('article:published_time', 'article:modified_time'):
            self.dates.append(values.get('content', '')[:80])
        if tag not in ('br', 'img', 'meta', 'link', 'input', 'hr', 'source', 'wbr'):
            self.stack.append(tag)

    def handle_endtag(self, tag):
        """同步标签栈，结束不可读或正文区域。"""
        if tag in self.stack:
            self.stack = self.stack[:len(self.stack) - 1 - self.stack[::-1].index(tag)]

    def handle_data(self, data):
        """只收集正文标签中的可见规范化文字，排除页面导航和脚本装饰。"""
        if not any(tag in self.stack for tag in ('script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript')):
            if any(tag in self.stack for tag in ('p', 'h1', 'h2', 'h3', 'article', 'main')):
                value = ' '.join(data.split())
                if value: self.text.append(value)


class EdgeSearch:
    """只读浏览器搜索适配器，最多两次查询尝试，过滤跑题结果并限制来源。"""
    def __init__(self, *, browser=browser_dom):
        """注入 DOM 读取能力，允许离线夹具验证解析与取消。"""
        self.browser = browser

    def search(self, topic, cancel):
        """先中文入口检索，缺少相关证据时改核心词/入口一次；仍不足就明确失败。"""
        sources, seen = [], set()
        query = split_query(topic)
        focused = focused_query(topic)
        # Short questions can fail upstream as a whole sentence. Retry with the
        # subject at the Chinese endpoint before resorting to another region.
        attempts = [('cn.bing.com', query),
                    ('cn.bing.com', focused) if focused != query else ('www.bing.com', query)]
        raw_count = 0
        for host, query in attempts:
            check_cancel(cancel)
            parser = SearchDOM()
            parser.feed(self.browser('https://' + host + '/search?' + urlencode(
                dict(q=query, count=10, mkt='zh-CN', setlang='zh-hans')), cancel))
            check_cancel(cancel)
            raw_count += len(parser.rows)
            for row in parser.rows[:30]:
                source = SearchSource(' '.join(row['title'])[:200] or row['url'],
                                      row['url'], ' '.join(row['content'])[:2000])
                if source.url and source.url not in seen and relevance(topic, source) >= .75:
                    seen.add(source.url)
                    sources.append(source)
            if sources:
                return tuple(sources[:5])
        if not raw_count:
            raise AgentError('搜索页面没有返回可读取的结果，可能加载失败、限流或需要验证。已尝试备用查询，请稍后重试或切换搜索服务。', code='no_sources')
        raise AgentError('搜索返回的资料与话题不匹配，已过滤跑题结果并尝试备用查询。请换一种说法或切换搜索服务；本次不会用无关来源生成回答。', code='no_sources')

    def enrich(self, sources, cancel):
        # Read only two public pages. Do not navigate into local/private networks.
        """兼容旧流程只尝试前两条公开 HTTPS 正文，失败保留原摘录，不与 ReAct 编号读取混用。"""
        from .pages import article_excerpt
        enriched = []
        for index, source in enumerate(sources):
            check_cancel(cancel)
            read_url = ('https://' + source.url[7:]) if source.url.startswith('http://') else source.url
            excerpt = article_excerpt(read_url, cancel) if index < 2 else ''
            enriched.append(replace(source, snippet=(source.snippet + '\n正文节选：' + excerpt)[:4000]) if excerpt else source)
        return tuple(enriched)
