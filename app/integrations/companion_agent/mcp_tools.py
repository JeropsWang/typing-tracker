"""网络线程使用的进程内 MCP 工具子集：初始化、发现与调用采用 JSON-RPC。

工具服务持有单次任务的来源台账和限额；客户端将 schema 转成模型函数声明。
不连接任意外部 MCP 服务器，不开放文件或系统命令工具。
"""
import json
from dataclasses import replace
from ...modules.companion.api import SearchSource, validate_topic
from .search import AgentError, AgentCancelled, check_cancel, source_url
from .pages import article_excerpt

PROTOCOL_VERSION = '2025-11-25'
TOOLS = (
    dict(name='web_search', description='搜索公开资料。可改写关键词或补搜，返回稳定 source_id 与摘录。',
         inputSchema=dict(type='object', properties=dict(query=dict(type='string', minLength=1, maxLength=200)),
                          required=['query'], additionalProperties=False)),
    dict(name='read_webpage', description='读取已搜索来源的公开 HTTPS 正文节选，核对日期和细节。不能读取任意 URL。',
         inputSchema=dict(type='object', properties=dict(source_id=dict(type='integer', minimum=1, maximum=8)),
                          required=['source_id'], additionalProperties=False)),
)


def observation(value, *, error=False):
    """把结构化结果包装成 MCP 观察；isError 让模型能区分失败并修正行动。"""
    return dict(content=[dict(type='text', text=json.dumps(value, ensure_ascii=False))],
                structuredContent=value, isError=error)


class SearchMcpServer:
    """单次任务的只读工具服务；只由所属网络线程操作台账、缓存和计数。"""
    def __init__(self, search, cancel, limits, announce, *, reader=None):
        """装配搜索/原文适配器及进度回调，创建互不共享的任务状态。"""
        self.search, self.cancel, self.limits, self.announce = search, cancel, limits, announce
        self.reader = reader or article_excerpt
        self.sources = []
        self.searches = self.reads = 0
        self.cache = {}
        self.last_error = ''
        self.initialized = self.ready = False

    def dispatch(self, request):
        """处理协议请求，返回带相同 ID 的结果/协议错误；初始化通知无响应。"""
        check_cancel(self.cancel)
        identifier = request.get('id') if isinstance(request, dict) else None
        def failure(code, message):
            """保持请求关联 ID，将协议错误编码为 JSON-RPC error 对象。"""
            return dict(jsonrpc='2.0', id=identifier, error=dict(code=code, message=message))
        if not isinstance(request, dict) or request.get('jsonrpc') != '2.0':
            return failure(-32600, 'Invalid JSON-RPC request')
        method, params = request.get('method'), request.get('params', {})
        if not isinstance(params, dict):
            return failure(-32602, 'Parameters must be an object')
        if method == 'notifications/initialized' and 'id' not in request:
            self.ready = self.initialized
            return None
        if identifier is None or type(identifier) not in (str, int):
            return failure(-32600, 'Request id is required')
        if method == 'initialize':
            if self.initialized:
                return failure(-32600, 'Already initialized')
            if params.get('protocolVersion') != PROTOCOL_VERSION:
                return failure(-32602, 'Unsupported protocol version')
            self.initialized = True
            result = dict(protocolVersion=PROTOCOL_VERSION, capabilities=dict(tools={}),
                          serverInfo=dict(name='sariana-search', version='1'))
        elif not self.ready:
            return failure(-32600, 'Initialize before using tools')
        elif method == 'tools/list':
            if params:
                return failure(-32602, 'This server has one tools page')
            result = dict(tools=list(TOOLS))
        elif method == 'tools/call':
            name, arguments = params.get('name'), params.get('arguments', {})
            if not isinstance(name, str) or name not in {t['name'] for t in TOOLS}:
                return failure(-32602, 'Unknown tool')
            if not self.valid_arguments(name, arguments):
                return failure(-32602, 'Arguments do not match inputSchema')
            result = self.call(name, arguments)
        else:
            return failure(-32601, 'Method not found')
        return dict(jsonrpc='2.0', id=identifier, result=result)

    @staticmethod
    def valid_arguments(name, arguments):
        """严格校验两项白名单工具的 schema，拒绝额外字段和布尔来源编号。"""
        if not isinstance(arguments, dict):
            return False
        if name == 'web_search':
            return (set(arguments) == {'query'} and isinstance(arguments['query'], str)
                    and 1 <= len(arguments['query']) <= 200 and bool(arguments['query'].strip()))
        return (set(arguments) == {'source_id'} and type(arguments['source_id']) is int
                and 1 <= arguments['source_id'] <= 8)

    def record(self, index):
        """把从零开始的台账索引转换成用于模型引用的稳定、从一开始的编号。"""
        source = self.sources[index]
        return dict(source_id=index + 1, title=source.title, url=source.url, excerpt=source.snippet)

    def call(self, name, arguments):
        """执行已校验的工具，更新真实来源；工具失败变成观察，用户取消继续抛出。"""
        # 精确重复的行动复用成功或失败结果；更换关键词才能触发新的搜索 I/O。
        key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
        if key in self.cache:
            return self.cache[key]
        try:
            if name == 'web_search':
                if self.searches >= self.limits.searches:
                    raise AgentError('本次搜索次数已用完，请根据已有资料结束回答。')
                query = validate_topic(arguments['query'])
                self.searches += 1
                self.announce('searching', '我正翻找资料：' + query)
                found = self.search.search(query, self.cancel)
                check_cancel(self.cancel)
                indexes = []
                for source in found:
                    if not isinstance(source, SearchSource) or not source_url(source.url):
                        continue
                    index = next((i for i, item in enumerate(self.sources) if item.url == source.url), None)
                    # 按 URL 去重但不重排，补搜后旧引用编号与已读取正文都保持有效。
                    if index is None:
                        if len(self.sources) >= self.limits.sources:
                            continue
                        index = len(self.sources)
                        self.sources.append(SearchSource(source.title[:200], source.url, source.snippet[:2000]))
                    if index not in indexes:
                        indexes.append(index)
                if not indexes:
                    raise AgentError('没有找到新的可引用资料，请换关键词或说明资料不足。')
                result = observation(dict(kind='search_excerpt', sources=[self.record(i) for i in indexes]))
            else:
                if self.reads >= self.limits.page_reads:
                    raise AgentError('本次正文读取次数已用完，请根据已有资料结束回答。')
                index = arguments['source_id'] - 1
                if index >= len(self.sources):
                    raise AgentError('source_id 不存在，请先搜索，再选择结果中的编号。')
                self.reads += 1
                self.announce('reading', '我正在核对这条来源的日期和正文…')
                text = self.reader(self.sources[index].url, self.cancel)
                check_cancel(self.cancel)
                if not text:
                    raise AgentError('正文暂时无法读取，仅保留搜索摘录；请勿声称读过原文。')
                self.sources[index] = replace(self.sources[index], snippet=('正文节选：\n' + text)[:2500])
                result = observation(dict(kind='page_excerpt', source=self.record(index)))
        except AgentCancelled:
            raise
        except (AgentError, ValueError) as error:
            check_cancel(self.cancel)
            result = observation(dict(error=str(error)), error=True)
        except Exception:
            check_cancel(self.cancel)
            result = observation(dict(error='资料工具暂时不可用，请调整方案或说明资料不足。'), error=True)
        self.cache[key] = result
        if result['isError']:
            self.last_error = result['structuredContent']['error']
        return result


class McpToolClient:
    """单次任务的本机协议客户端，将模型调用适配为 MCP 请求，不直接执行工具。"""
    def __init__(self, server):
        """完成版本协商/初始化通知，再发现本次任务可用的工具。"""
        self.server, self.sequence = server, 0
        self.request('initialize', dict(protocolVersion=PROTOCOL_VERSION, capabilities={},
                     clientInfo=dict(name='sariana-agent', version='1')))
        server.dispatch(dict(jsonrpc='2.0', method='notifications/initialized'))
        self.tools = self.request('tools/list', {})['tools']

    def request(self, method, params):
        """序列化协议边界并检查响应 ID；协议错误抛 AgentError 交给调用方处理。"""
        self.sequence += 1
        # 用序列化副本隔离调用方与服务端状态，避免共享可变字典产生隐式修改。
        request = json.loads(json.dumps(dict(jsonrpc='2.0', id=self.sequence, method=method, params=params)))
        response = self.server.dispatch(request)
        if response.get('id') != self.sequence:
            raise AgentError('工具协议响应标识不匹配。')
        if 'error' in response:
            raise AgentError(response['error']['message'])
        return json.loads(json.dumps(response['result']))

    def declarations(self):
        """将已发现的 MCP inputSchema 转为兼容模型原生 tools 的函数声明。"""
        return [dict(type='function', function=dict(name=t['name'], description=t['description'],
                     parameters=t['inputSchema'])) for t in self.tools]

    def execute(self, call):
        """解析模型 JSON 参数并调用工具；参数/协议错误反馈为观察，取消不吞掉。"""
        check_cancel(self.server.cancel)
        try:
            if len(call.arguments) > 8192:
                raise ValueError()
            arguments = json.loads(call.arguments)
        except (ValueError, TypeError):
            return observation(dict(error='工具参数必须是有效的 JSON 对象，请修正后重试。'), error=True)
        try:
            return self.request('tools/call', dict(name=call.name, arguments=arguments))
        except AgentCancelled:
            raise
        except AgentError as error:
            check_cancel(self.server.cancel)
            return observation(dict(error=str(error)), error=True)
