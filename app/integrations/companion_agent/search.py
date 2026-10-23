"""Bounded search transport. Only user-configured services receive credentials."""
import ipaddress
import json
from contextlib import contextmanager
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError
from xml.etree import ElementTree
from ...modules.companion.api import SearchSource, agent_failure_code

MAX_RESPONSE = 2_000_000


class AgentError(RuntimeError):
    """兼容可见异常，增加固定阶段／类别；异常文字不能直接写入任务表。"""
    def __init__(self, message='', *, stage='agent', code='unknown'):
        """保留旧字符串构造；新增元数据只接受领域白名单，不接收响应正文。"""
        super().__init__(message)
        self.stage, self.code = stage, code
        self.stage, self.code = agent_failure_code(self).split('.')


class AgentCancelled(AgentError):
    """用户取消的独立异常类型，不能当作工具失败吞掉继续搜索。"""
    pass


@contextmanager
def error_stage(stage, default_code='protocol'):
    """为适配器错误补足阶段与默认类别，取消保持原类型，不改变可见兼容文字。"""
    try:
        yield
    except AgentCancelled:
        raise
    except AgentError as error:
        code = default_code if error.code == 'unknown' else error.code
        raise AgentError(str(error), stage=stage, code=code) from None


def check_cancel(cancel):
    """检查取消信号并抛 AgentCancelled，供所有读取/工具检查点复用。"""
    if cancel.is_set():
        raise AgentCancelled('已取消这次搜索。')


def endpoint_url(url):
    """Remote credentials require TLS; loopback/LAN model servers allow HTTP."""
    parsed = urlsplit(url)
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AgentError('服务地址需为完整 URL，不能含账号、查询参数或片段。')
    try:
        local = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname).is_private
    except ValueError:
        local = parsed.hostname.endswith('.local')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise AgentError('远程服务请使用 HTTPS；本机或局域网服务可使用 HTTP。')
    return url.rstrip('/')


def source_url(url):
    """仅接收有界、无嵌入凭据的 HTTP/HTTPS 来源链接，非法值返回空串。"""
    if not isinstance(url, str) or len(url) > 2048:
        return ''
    try:
        p = urlsplit(url)
        return url if p.scheme in ('https', 'http') and p.hostname and not p.username and not p.password else ''
    except ValueError:
        return ''


class NoRedirect(HTTPRedirectHandler):
    """含凭据请求的重定向拒绝器，避免模型/搜索密钥被发送到另一个地址。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Avoid sending a model/search credential to another origin.
        """拒绝上游重定向并提示用户填写最终端点，不转发凭据。"""
        raise AgentError('服务发生重定向，请在配置中填写最终接口地址。')


@contextmanager
def open_response(request, *, opener=None, timeout=25):
    """用调用方指定的有限秒数打开响应；默认25秒，模型本机冷启动可单独放宽。"""
    opener = opener or build_opener(NoRedirect()).open
    try:
        with opener(request, timeout=timeout) as response:
            yield response
    except AgentError:
        raise
    except HTTPError as error:
        code = error.code
        error.close()
        if code in (401, 403):
            raise AgentError('服务拒绝访问，请检查 API Key 和权限。', code='auth') from None
        if code == 429:
            raise AgentError('请求太频繁或额度不足，请稍后再试。', code='rate_limit') from None
        raise AgentError(f'服务返回 HTTP {code}，请检查接口配置。', code='protocol') from None
    except TimeoutError:
        raise AgentError('服务响应超时，请稍后重试。', code='timeout') from None
    except (URLError, OSError) as error:
        code = 'timeout' if isinstance(getattr(error, 'reason', None), TimeoutError) else 'connection'
        raise AgentError('暂时连接不上服务，请检查网络和服务是否启动。', code=code) from None
    except (ValueError, UnicodeError):
        raise AgentError('服务没有返回有效 JSON，请检查接口地址。') from None


def read_json(request, *, opener=None):
    """读取最多 MAX_RESPONSE 字节的对象 JSON，过大或类型错误明确失败。"""
    with open_response(request, opener=opener) as response:
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise AgentError('服务返回内容过大，请缩小搜索范围。')
        value = json.loads(raw.decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError()
        return value


class WebSearch:
    """独立搜索配置的只读适配器，支持 Edge、公开 RSS、Tavily 与已有 SearXNG。"""
    def __init__(self, config, *, opener=None):
        """保存搜索配置快照和可注入传输，不读取或混用模型密钥。"""
        self.config, self.opener = config, opener

    def validate(self):
        """按搜索服务校验必要密钥/端点，公开搜索不要求 Key 或管理外部服务。"""
        with error_stage('search', 'configuration'):
            self._validate()

    def _validate(self):
        """校验内部搜索配置，由公开入口补齐搜索阶段与配置失败类别。"""
        if self.config.search_provider in ('web', 'web-lite'):
            return
        if self.config.search_provider == 'tavily':
            if not self.config.search_key.strip():
                raise AgentError('请在桌宠自定义 → 智能体中填写 Tavily 搜索 Key。')
        elif self.config.search_provider == 'searxng':
            endpoint_url(self.config.search_url)
        else:
            raise AgentError('请选择免 Key 网页搜索、Tavily 或已有 SearXNG 服务。')

    def search(self, topic, cancel):
        """执行所选只读搜索并校验/去重/限制来源，返回真实摘录或明确错误。"""
        with error_stage('search'):
            return self._search(topic, cancel)

    def _search(self, topic, cancel):
        """在已设定搜索错误边界内执行传输，外层统一保留分类。"""
        self.validate()
        check_cancel(cancel)
        if self.config.search_provider == 'web':
            from .edge_search import EdgeSearch
            return EdgeSearch().search(topic, cancel)
        if self.config.search_provider == 'web-lite':
            return self._public_search(topic, cancel)
        if self.config.search_provider == 'tavily':
            request = Request('https://api.tavily.com/search', method='POST',
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.config.search_key},
                data=json.dumps(dict(query=topic, max_results=5, search_depth='basic',
                                     include_answer=False, include_raw_content=False)).encode('utf-8'))
        else:
            base = endpoint_url(self.config.search_url)
            if not base.endswith('/search'):
                base += '/search'
            request = Request(base + '?' + urlencode(dict(q=topic, format='json')),
                              headers={'Accept': 'application/json', 'User-Agent': 'Sariana/companion-search'})
        data = read_json(request, opener=self.opener)
        check_cancel(cancel)
        entries = data.get('results')
        if not isinstance(entries, list):
            raise AgentError('搜索服务没有返回结果列表；SearXNG 需开启 JSON 格式。')
        results, seen = [], set()
        for row in entries[:30]:
            if not isinstance(row, dict):
                continue
            url = source_url(row.get('url'))
            title, content = row.get('title', ''), row.get('content', '')
            if not url or url in seen or not isinstance(title, str) or not isinstance(content, str):
                continue
            seen.add(url)
            results.append(SearchSource(title[:200] or url, url, content[:2000]))
            if len(results) == 5:
                break
        if not results:
            raise AgentError('没有找到可引用的结果，试试更具体的话题。', code='no_sources')
        return tuple(results)

    def enrich(self, sources, cancel):
        """兼容旧读取入口，仅 Edge 路径补正文；生产 ReAct 使用独立编号读取工具。"""
        if self.config.search_provider == 'web':
            from .edge_search import EdgeSearch
            return EdgeSearch().enrich(sources, cancel)
        return sources

    def _public_search(self, topic, cancel):
        # Public RSS results need no credential, daemon or external executable.
        # Keep each attempt bounded; never mistake a CAPTCHA page for results.
        """最多尝试两个公开 RSS 入口，验证码/非 RSS/空结果不当作成功，取消不继续备用请求。"""
        last_code = 'no_sources'
        for host in ('www.bing.com', 'cn.bing.com'):
            check_cancel(cancel)
            request = Request('https://' + host + '/search?' + urlencode(
                dict(q=topic, format='rss')), headers={
                    'Accept': 'application/rss+xml, application/xml',
                    'User-Agent': 'Sariana/companion-search'})
            try:
                with open_response(request, opener=self.opener) as response:
                    raw = response.read(MAX_RESPONSE + 1)
                check_cancel(cancel)
                if len(raw) > MAX_RESPONSE:
                    raise AgentError('搜索结果过大。')
                results = parse_public_results(raw)
                if results:
                    return results
                last_code = 'no_sources'
            except AgentCancelled:
                raise
            except AgentError as error:
                last_code = error.code
                continue
            except (ElementTree.ParseError, ValueError):
                last_code = 'protocol'
                continue
        raise AgentError('免 Key 搜索暂时不可用或没有结果，请稍后重试；也可在配置中切换 Tavily 或已有 SearXNG。', code=last_code)


def parse_public_results(raw):
    """Parse bounded RSS only, with no DTD/entity expansion or HTML execution."""
    if len(raw) > MAX_RESPONSE:
        raise ValueError('Unsupported search response')
    # RSS endpoint uses UTF-8. Decode first so UTF-16 cannot hide declarations.
    text = raw.decode('utf-8-sig')
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('Unsupported search response')
    root = ElementTree.fromstring(text)
    if root.tag != 'rss':
        return ()
    results, seen = [], set()
    for item in root.findall('./channel/item')[:30]:
        url = source_url(item.findtext('link', ''))
        if not url or url in seen:
            continue
        seen.add(url)
        results.append(SearchSource(item.findtext('title', '')[:200] or url,
                                    url, item.findtext('description', '')[:2000]))
        if len(results) == 5:
            break
    return tuple(results)
