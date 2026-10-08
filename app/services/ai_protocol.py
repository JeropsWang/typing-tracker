"""思考协议与接口用量；不访问网络、数据库或 UI。"""
from dataclasses import dataclass
from urllib.parse import urlsplit

THINKING_LIMIT = 8192
PROTOCOLS = (
    ('auto', '自动识别'),
    ('thinking', '对象开关 · thinking'),
    ('enable_thinking', '布尔开关 · enable_thinking'),
    ('reasoning_effort', '强度开关 · reasoning_effort'),
)


def thinking_enabled(config):
    return config.get('thinking', '0') in (True, '1')


@dataclass(frozen=True)
class ThinkingPolicy:
    protocol: str = 'none'
    can_disable: bool = True
    completion_budget: bool = False
    description: str = '未识别思考控制协议；普通模型无需开关，代理接口可手动选择协议。'
    stream_thinking: bool = False


def thinking_policy(config, endpoint, model):
    host = urlsplit(endpoint).hostname
    model = model.lower()
    switchable = model.startswith(('gpt-5.1', 'gpt-5.2', 'gpt-5.4', 'gpt-5.5', 'gpt-5.6',
                                   'gpt-6-sol', 'gpt-6-luna'))
    reasoning = switchable or model.startswith(('o1', 'o3', 'o4', 'gpt-5', 'gpt-6'))
    if host == 'api.openai.com':
        if reasoning:
            return ThinkingPolicy('reasoning_effort', switchable, True,
                                  'OpenAI：none 关闭 / high 开启。' if switchable
                                  else '当前模型无法关闭思考；换用支持非思考的模型或开启思考模式。')
    if host == 'api.deepseek.com' and model in ('deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-pro'):
        return ThinkingPolicy('thinking', description='DeepSeek：已识别思考开关。')
    if config.get('backend') == 'ollama':
        return ThinkingPolicy('reasoning_effort', description='Ollama：请求 none / high，实际支持范围取决于本地模型。')
    if host in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com',
                'dashscope-us.aliyuncs.com', 'coding.dashscope.aliyuncs.com'):
        forced = ('thinking' in model or model.startswith(('deepseek-r1', 'qwq', 'glm-5.3')))
        hybrid = model.startswith(('qwen3', 'qwen-plus', 'qwen-flash', 'qwen-turbo', 'deepseek-v4'))
        if forced or (hybrid and not any(part in model for part in ('coder', 'instruct', 'omni'))):
            return ThinkingPolicy('enable_thinking', not forced, description=(
                '当前模型无法关闭思考；换用混合思考模型或开启思考模式。' if forced
                else '百炼：已识别 enable_thinking 开关；思考时使用流式响应。'), stream_thinking=True)
    protocol = config.get('thinking_protocol', 'auto')
    if protocol in dict(PROTOCOLS) and protocol != 'auto':
        openai_reasoning = protocol == 'reasoning_effort' and reasoning
        return ThinkingPolicy(protocol, switchable if openai_reasoning else True,
                              openai_reasoning, '手动协议：请确认服务与模型支持所选开关。',
                              stream_thinking=protocol == 'enable_thinking')
    return ThinkingPolicy()


def chat_payload(config, endpoint, model, messages, max_tokens):
    policy = thinking_policy(config, endpoint, model)
    enabled = thinking_enabled(config)
    if not enabled and not policy.can_disable:
        raise ValueError('当前模型无法关闭思考，请换用支持非思考的模型或开启思考模式')
    if enabled and policy.protocol == 'none':
        raise ValueError('未识别思考开关协议，请选择匹配的接口协议或使用支持思考开关的模型')
    limit = max(max_tokens, THINKING_LIMIT) if enabled else max_tokens
    payload = {'model': model, 'messages': messages,
               'max_completion_tokens' if policy.completion_budget else 'max_tokens': limit}
    if policy.protocol == 'thinking':
        payload['thinking'] = {'type': 'enabled' if enabled else 'disabled'}
    elif policy.protocol == 'enable_thinking':
        payload['enable_thinking'] = enabled
    elif policy.protocol == 'reasoning_effort':
        payload['reasoning_effort'] = 'high' if enabled else 'none'
    if not policy.completion_budget:
        payload['temperature'] = 0.8
    if enabled and policy.stream_thinking:
        payload['stream'] = True
        payload['stream_options'] = {'include_usage': True}
    return payload


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_response(cls, response):
        usage = response.get('usage') if isinstance(response, dict) else None
        if not isinstance(usage, dict) or not usage:
            return None
        details = usage.get('completion_tokens_details') or usage.get('output_tokens_details')
        details = details if isinstance(details, dict) else {}
        return cls(_count(usage.get('prompt_tokens', usage.get('input_tokens'))),
                   _count(usage.get('completion_tokens', usage.get('output_tokens'))),
                   _count(details.get('reasoning_tokens')),
                   _count(usage.get('total_tokens')))


def usage_text(usage):
    if usage is None:
        return '本次 token · 接口未返回用量'
    def label(value):
        return f'{value:,}' if value is not None else '接口未返回'
    return (f'本次 token · 输入 {label(usage.input_tokens)} / 输出 {label(usage.output_tokens)}'
            f' / 思考 {label(usage.reasoning_tokens)} / 总计 {label(usage.total_tokens)}')
