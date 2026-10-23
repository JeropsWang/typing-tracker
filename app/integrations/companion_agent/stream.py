"""有界 JSON/SSE 轮次读取：区分可见正文、原生工具行动和私有协议续接字段。"""
import json
import time
from .search import AgentError, MAX_RESPONSE, check_cancel, open_response
from ...modules.companion.api import AgentTurn, AgentToolCall


class VisibleText:
    """逐片段过滤思考标签的状态机；跨片段保留标签残片，但不输出推理正文。"""
    TAGS = ('<think>', '</think>', '<analysis>', '</analysis>')

    def __init__(self):
        """创建单次响应的过滤状态；pending 是待判定文本，closing 是思考结束标签。"""
        self.pending = ''
        self.closing = ''

    def feed(self, text):
        """接收一个正文分片，仅返回此时可确认不属于思考标签/区块的文字。"""
        self.pending += text
        visible = []
        while self.pending:
            lower = self.pending.lower()
            if self.closing:
                index = lower.find(self.closing)
                if index < 0:
                    # 思考区块内只保留可能拼成闭合标签的尾部，不缓存或泄漏整段推理。
                    self.pending = self.pending[-(len(self.closing) - 1):]
                    break
                self.pending = self.pending[index + len(self.closing):]
                self.closing = ''
                continue
            index = lower.find('<')
            if index < 0:
                visible.append(self.pending)
                self.pending = ''
                break
            if index:
                visible.append(self.pending[:index])
                self.pending = self.pending[index:]
                lower = self.pending.lower()
            if any(tag.startswith(lower) for tag in self.TAGS):
                break
            match = next((tag for tag in self.TAGS if lower.startswith(tag)), None)
            if match:
                self.pending = self.pending[len(match):]
                if not match.startswith('</'):
                    self.closing = '</' + match[1:]
            else:
                visible.append(self.pending[0])
                self.pending = self.pending[1:]
        return ''.join(visible)

    def finish(self):
        """结束过滤；不完整标签和未闭合的思考区块保持隐藏，避免尾片泄漏。"""
        if self.closing or any(tag.startswith(self.pending.lower()) for tag in self.TAGS):
            return ''
        return self.pending


def read_model_text(request, cancel, on_text, *, opener=None, timeout=25):
    """按 timeout 秒传输预算读取正文；返回工具行动时拒绝，不偷偷执行。"""
    turn = read_model_turn(request, cancel, on_text, opener=opener, timeout=timeout)
    if turn.tool_calls:
        raise AgentError('当前请求不支持工具调用。')
    return turn.text


def read_model_turn(request, cancel, on_text=lambda _: None, *, opener=None, timeout=25):
    """读取完整模型轮次，拼接有界工具参数与正文，截断/格式错误抛 AgentError。

    可见草稿通过 on_text 传递；reasoning_content 只进入返回轮次的私有字段。
    cancel 在读取检查点生效，阻塞读取由 timeout 秒预算结束（默认25，本机模型120）。
    """
    visible = VisibleText()
    result = ''
    finished = None
    started = time.monotonic()
    calls, reasoning = {}, ''
    def append(text):
        """过滤正文并限制长度；已发现工具行动时不把伴随文字当作答案草稿。"""
        nonlocal result
        check_cancel(cancel)
        result += visible.feed(text)
        if len(result) > 6000:
            raise AgentError('模型回答过长，请缩小话题范围。')
        if not calls:
            on_text(result)

    def consume(message, *, delta=False):
        """解析完整消息或 SSE 增量，按调用序号合并参数并分别收集协议推理/正文。"""
        nonlocal reasoning
        if not isinstance(message, dict):
            raise AgentError('模型消息格式不正确。')
        private = message.get('reasoning_content')
        if private is not None:
            if not isinstance(private, str):
                raise AgentError('模型协议字段格式不正确。')
            reasoning += private
            if len(reasoning) > 64_000:
                raise AgentError('模型思考响应过大，请关闭思考或缩小话题。')
        fragments = message.get('tool_calls') or []
        if not isinstance(fragments, list) or len(fragments) > 8:
            raise AgentError('模型工具调用过多或格式不正确。')
        for position, fragment in enumerate(fragments):
            if not isinstance(fragment, dict):
                raise AgentError('模型工具调用格式不正确。')
            index = fragment.get('index', position) if delta else position
            if type(index) is not int or not 0 <= index < 8:
                raise AgentError('模型工具调用序号不正确。')
            if fragment.get('type', 'function') != 'function':
                raise AgentError('模型返回不支持的工具类型。')
            call = calls.setdefault(index, dict(id='', name='', arguments=''))
            # 工具名称、ID 和 JSON 参数可能跨多个 SSE 分片，须拼完整后再校验/执行。
            function = fragment.get('function') or {}
            if not isinstance(function, dict):
                raise AgentError('模型工具参数格式不正确。')
            for key, value in [('id', fragment.get('id')), ('name', function.get('name')),
                               ('arguments', function.get('arguments'))]:
                if value is not None:
                    if not isinstance(value, str):
                        raise AgentError('模型工具参数格式不正确。')
                    call[key] += value
                    if len(call[key]) > (8192 if key == 'arguments' else 200):
                        raise AgentError('模型工具参数过长。')
        text = message.get('content')
        if text is not None:
            if not isinstance(text, str):
                raise AgentError('模型正文格式不正确。')
            append(text)

    with open_response(request, opener=opener, timeout=timeout) as response:
        if 'text/event-stream' not in response.headers.get('Content-Type', '').lower():
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise AgentError('模型返回内容过大。')
            data = json.loads(raw.decode('utf-8'))
            try:
                choice = data['choices'][0]
                finished = choice.get('finish_reason')
                consume(choice['message'])
            except (KeyError, IndexError, TypeError, ValueError):
                raise AgentError('模型未返回正文，请检查模型名或思考模式。') from None
        else:
            received, fields = 0, []
            while True:
                check_cancel(cancel)
                if time.monotonic() - started > 180:
                    raise AgentError('模型整理超时，请缩小话题或换用更快的模型。', code='timeout')
                line = response.readline(65_537)
                if not line:
                    break
                received += len(line)
                if len(line) > 65_536 or received > MAX_RESPONSE:
                    raise AgentError('模型流式响应过大。')
                line = line.decode('utf-8').rstrip('\r\n')
                if line.startswith('data:'):
                    fields.append(line[5:].lstrip())
                if line or not fields:
                    continue
                event = '\n'.join(fields)
                fields.clear()
                if event == '[DONE]':
                    break
                data = json.loads(event)
                if not isinstance(data, dict) or data.get('error'):
                    raise AgentError('模型流式响应出现错误，请重试。')
                choices = data.get('choices')
                if not isinstance(choices, list):
                    raise AgentError('模型流式响应格式不正确。')
                for choice in choices:
                    if not isinstance(choice, dict):
                        raise AgentError('模型流式响应格式不正确。')
                    if choice.get('index', 0) != 0:
                        continue
                    delta = choice.get('delta') or {}
                    if not isinstance(delta, dict):
                        raise AgentError('模型流式响应格式不正确。')
                    consume(delta, delta=True)
                    if choice.get('finish_reason'):
                        finished = choice['finish_reason']
    if finished == 'length':
        # 即使当前参数片段恰好能解析，也不能执行被输出预算截断的工具响应。
        raise AgentError('模型回答达到长度上限，未完成整理。')
    if finished is None:
        raise AgentError('模型响应提前结束，请重试。')
    if finished not in ('stop', 'tool_calls'):
        raise AgentError('模型未正常完成本轮响应。')
    result += visible.finish()
    check_cancel(cancel)
    tool_calls = tuple(AgentToolCall(**calls[index]) for index in sorted(calls))
    if any(not call.id or not call.name for call in tool_calls) or len({c.id for c in tool_calls}) != len(tool_calls):
        raise AgentError('模型工具调用缺少标识或存在重复标识。')
    if finished == 'tool_calls' and not tool_calls:
        raise AgentError('模型没有提供可执行的工具调用。')
    if not result.strip() and not tool_calls:
        raise AgentError('模型没有返回正文，可能思考耗尽输出预算；可关闭思考或换模型重试。')
    return AgentTurn(result.strip(), tool_calls, reasoning)
