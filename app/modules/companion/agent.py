"""桌宠智能体的不可变业务契约与配置规则；不依赖数据库、Qt 或网络。"""
from dataclasses import dataclass, field
from typing import Callable, Protocol
from collections.abc import Mapping


MODEL_PRESETS = {
    'openai': ('https://api.openai.com/v1', 'gpt-4o-mini'),
    'deepseek': ('https://api.deepseek.com/v1', 'deepseek-chat'),
    'local': ('http://127.0.0.1:11434/v1', 'qwen3:1.7b'),
    'custom': ('', ''),
}


class AgentBusyError(RuntimeError):
    """共享网络准入被占用；自动排期应退让，不能将其记成已执行的上游失败。"""
    pass


@dataclass(frozen=True)
class AgentConfig:
    """单次请求使用的独立配置快照；模型和搜索凭据分别持有，repr 隐藏密钥。"""
    enabled: bool = False
    provider: str = 'openai'
    base_url: str = ''
    model: str = ''
    api_key: str = field(default='', repr=False)
    search_provider: str = 'web'
    search_url: str = ''
    search_key: str = field(default='', repr=False)
    default_topic: str = ''
    thinking: bool = True

    @classmethod
    def from_settings(cls, settings):
        """从已提交的设置快照构造配置，兼容旧托管搜索开关而不修改保存值。"""
        # 一次读取整个脱离数据库的快照，避免后台更新时混用不同版本的服务与密钥。
        snapshot = getattr(settings, 'settings', None)
        get = settings.get if isinstance(settings, Mapping) else (snapshot().get if callable(snapshot) else settings.get_setting)
        legacy_managed = get('companion_agent_managed_search', '0') == '1'
        return cls(enabled=get('companion_agent_enabled', '0') == '1',
                   thinking=get('companion_agent_thinking', '1') != '0',
                   **{name: ('web' if name == 'search_provider' and legacy_managed
                            else get('companion_agent_' + name, default) or default)
                      for name, default in [('provider', 'openai'), ('base_url', ''),
                          ('model', ''), ('api_key', ''), ('search_provider', 'web'),
                          ('search_url', ''), ('search_key', ''), ('default_topic', '')]})

    def model_settings(self):
        """补全服务预设并转为共享模型协议配置；空地址/模型采用所选服务默认值。"""
        url, model = MODEL_PRESETS.get(self.provider, ('', ''))
        return dict(backend='ollama' if self.provider == 'local' else 'openai',
                    base_url=self.base_url.strip() or url,
                    model=self.model.strip() or model, api_key=self.api_key,
                    thinking='1' if self.thinking else '0', thinking_protocol='auto')


@dataclass(frozen=True)
class SearchSource:
    """工具实际取得的可引用来源；snippet 可为搜索摘要或有界正文节选。"""
    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class AgentReport:
    """交给 UI 的任务结果；request_id 拒绝迟到回传，warning 标明未完整成功。"""
    request_id: str
    topic: str
    summary: str
    sources: tuple[SearchSource, ...]
    fetched_at: str
    warning: str = ''


@dataclass(frozen=True)
class AgentProgress:
    """网络线程发布的阶段或可见草稿；UI 按请求 ID 过滤已取消任务。"""
    request_id: str
    stage: str
    text: str


@dataclass(frozen=True)
class AgentConnectionResult:
    """草稿连接检查结果；elapsed_seconds 为秒，source_count 仅用于搜索检查。"""
    message: str
    elapsed_seconds: float
    source_count: int = 0


@dataclass(frozen=True)
class AgentTool:
    """兼容旧代码的可调用工具契约；生产图的工具发现使用 MCP 描述与 schema。"""
    name: str
    description: str
    execute: Callable


@dataclass(frozen=True)
class AgentToolCall:
    """模型本轮请求的工具行动；arguments 保留原始 JSON，交工具层校验再执行。"""
    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class AgentTurn:
    """模型单轮的可见文字、工具行动及仅用于协议续接的私有推理字段。"""
    text: str = ''
    tool_calls: tuple[AgentToolCall, ...] = ()
    # 仅用于供应商工具调用的协议连续性，不展示、不记录日志、不持久化。
    reasoning: str = field(default='', repr=False)


@dataclass(frozen=True)
class AgentRunLimits:
    """单次任务的硬边界；计数含失败尝试，context_chars 为字符，seconds 为秒。"""
    model_turns: int = 6
    tool_calls: int = 8
    searches: int = 3
    page_reads: int = 3
    sources: int = 8
    context_chars: int = 96_000
    seconds: float = 300


class CompanionAgent(Protocol):
    """UI 使用的异步能力契约；只交换配置、进度和结果，不传数据库或控件。"""
    def search(self, config: AgentConfig, topic: str, progress: Callable):
        """启动主动话题搜索，返回稳定请求 ID 与 Future，进度通过回调传递。"""
        ...
    def news(self, config: AgentConfig, request, progress: Callable):
        """以专用主动兴趣契约生成来信，与搜索共用同一网络准入和图执行器。"""
        ...
    def judge(self, config: AgentConfig, question: str, progress: Callable):
        """启动仅模型的娱乐占卜，返回请求ID及OracleResult Future，不校验搜索配置。"""
        ...
    def cancel(self, request_id=None):
        """请求取消当前所有者任务；后台真正结束前仍持有运行准入。"""
        ...
    def close(self):
        """停止接收新任务并请求取消在途任务，供界面退出时调用。"""
        ...


def validate_topic(topic):
    """去除话题两端空白；空内容或超过 200 字抛 ValueError，不触发网络。"""
    topic = topic.strip()
    if not topic:
        raise ValueError('请先写下想了解的话题。')
    if len(topic) > 200:
        raise ValueError('话题请控制在 200 字以内。')
    return topic
