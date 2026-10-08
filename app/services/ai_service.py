"""AI 范文生成服务：OpenAI 兼容 API / 本地 Ollama / 自定义端点。

- Ollama 与 llama.cpp / LM Studio 均提供 OpenAI 兼容的 /v1/chat/completions
  端点，因此统一走同一协议，仅 base_url / api_key 不同。
- 全部使用标准库 urllib，无新增依赖；调用应在工作线程中进行。
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from .ai_protocol import TokenUsage, chat_payload, thinking_enabled, usage_text
from .ai_response import read_chat_response

DEFAULTS = {
    'openai': {'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini'},
    'ollama': {'base_url': 'http://127.0.0.1:11434/v1', 'model': 'llama3.2'},
}


def _completion_text(data) -> str:
    """只接收完整正文；思考内容不能作为范文或英语训练材料。"""
    choices = data.get('choices') if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError('AI 服务返回格式不正确：缺少生成结果')
    choice = choices[0]
    message = choice.get('message')
    if not isinstance(message, dict):
        raise ValueError('AI 服务返回格式不正确：缺少正文消息')
    text = message.get('content')
    if text is None:
        text = ''
    if not isinstance(text, str):
        raise ValueError('AI 服务返回格式不正确：正文不是文本')
    if choice.get('finish_reason') == 'length':
        raise ValueError('生成达到输出上限，正文未完成；请关闭模型思考模式或缩短练习内容')
    if not text.strip():
        if message.get('reasoning_content'):
            raise ValueError('模型只返回了思考内容，没有正文；请关闭模型思考模式后重试')
        raise ValueError('AI 服务未返回正文，请检查模型配置后重试')
    return text


class AIService:
    def __init__(self, repo=None, *, config=None):
        """主线程从仓储读设置；工作线程使用独立配置快照，不持有数据库连接。"""
        if repo is None and config is None:
            raise ValueError('AIService 需要仓储或配置快照')
        self._repo = repo
        self._config = dict(config) if config is not None else None
        self.last_usage = None

    def snapshot(self) -> AIService:
        """主线程在启动请求前捕获配置；后续设置变更只影响下一次请求。"""
        return AIService(config=self._cfg())

    # ---------- 配置 ----------
    def _cfg(self):
        if self._config is not None:
            return dict(self._config)
        return {
            'backend': self._repo.get_setting('ai_backend', 'off') or 'off',
            'base_url': self._repo.get_setting('ai_base_url', '') or '',
            'api_key': self._repo.get_setting('ai_api_key', '') or '',
            'model': self._repo.get_setting('ai_model', '') or '',
            'thinking': self._repo.get_setting('ai_thinking', '0') or '0',
            'thinking_protocol': self._repo.get_setting('ai_thinking_protocol', 'auto') or 'auto',
        }

    def enabled(self) -> bool:
        return self._cfg()['backend'] in ('openai', 'ollama')

    def backend_label(self) -> str:
        cfg = self._cfg()
        names = {'openai': 'OpenAI 兼容', 'ollama': 'Ollama 本地'}
        return names.get(cfg['backend'], '未启用')

    def _endpoint(self) -> str:
        cfg = self._cfg()
        base = cfg['base_url'] or DEFAULTS.get(cfg['backend'], {}).get('base_url', '')
        base = base.rstrip('/')
        # 用户可能直接粘贴完整端点（…/v1/chat/completions），避免重复拼接
        if base.endswith('/chat/completions'):
            return base
        return base + '/chat/completions'

    def _model(self) -> str:
        cfg = self._cfg()
        return (cfg['model']
                or DEFAULTS.get(cfg['backend'], {}).get('model', 'gpt-4o-mini'))

    def _headers(self) -> dict:
        cfg = self._cfg()
        h = {'Content-Type': 'application/json'}
        if cfg['api_key']:
            h['Authorization'] = f'Bearer {cfg["api_key"]}'
        return h

    # ---------- 请求 ----------
    def _chat(self, messages, max_tokens=600, timeout=90) -> str:
        self.last_usage = None
        endpoint = self._endpoint()
        model = self._model()
        payload = chat_payload(self._cfg(), endpoint, model, messages, max_tokens)
        body = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(endpoint, data=body,
                                     headers=self._headers(), method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = read_chat_response(r, self._capture_usage)
        except urllib.error.HTTPError as error:
            try:
                self.last_usage = TokenUsage.from_response(json.loads(error.read(1_048_576).decode('utf-8')))
            except (ValueError, OSError):
                pass
            raise
        return _completion_text(data)

    def _capture_usage(self, data):
        usage = TokenUsage.from_response(data)
        if usage is not None:
            self.last_usage = usage

    def chat(self, messages, max_tokens=600, timeout=90):
        """供英语等独立模块复用网络协议；调用者负责输出结构校验。"""
        return self._chat(messages, max_tokens=max_tokens, timeout=timeout)

    # ---------- 功能 ----------
    def _friendly_error(self, e: Exception) -> str:
        """把常见网络异常翻译成可操作的提示（曾直接抛原始异常，v0.8.9）。"""
        msg = str(e)
        if isinstance(e, TimeoutError) or 'timed out' in msg or 'timeout' in msg.lower():
            return '请求超时：模型响应过慢，请检查模型是否已加载、网络是否通畅'
        if isinstance(e, ConnectionRefusedError) or '10061' in msg:
            return '连接被拒绝：Ollama/服务未启动？请先启动本地服务再试'
        if 'Name or service not known' in msg or 'getaddrinfo' in msg.lower() \
                or '无法连接到' in msg:
            return '无法解析地址：请检查 Base URL 是否正确'
        if isinstance(e, OSError) and '10060' in msg:
            return '连接超时：目标不可达，请检查网络或服务地址'
        if 'HTTP Error' in msg:
            return f'服务返回错误（{msg}）：请检查 Base URL、API Key 与模型名'
        return f'请求失败：{msg}'

    def test_connection(self):
        """连通性测试；返回 (成功, 消息)。"""
        self.last_usage = None
        if not self.enabled():
            return False, 'AI 未启用（设置 → AI 配置）'
        try:
            reply = self._chat(
                [{'role': 'user', 'content': '只回复 OK。'}],
                max_tokens=64, timeout=90 if thinking_enabled(self._cfg()) else 20)
            return True, (f'连接成功（{self.backend_label()} · {self._model()}）：{reply.strip()[:40]}\n'
                          + usage_text(self.last_usage))
        except Exception as e:
            return False, self._friendly_error(e) + '\n' + usage_text(self.last_usage)

    def generate(self, topic: str, lang: str = 'cn', length: int = 260):
        """生成一篇打字练习范文；返回 (成功, 文本或错误信息)。"""
        self.last_usage = None
        if not self.enabled():
            return False, 'AI 未启用，请在设置中配置'
        if not topic.strip():
            return False, '请输入主题'
        lang_name = '中文' if lang == 'cn' else 'English'
        prompt = (
            f'你是打字练习文本生成器。请生成一段约 {length} 字的{lang_name}打字练习文本，'
            f'主题：{topic}。要求：语句通顺、内容连贯、无生僻字、不使用引号包裹、'
            f'不要解释，只输出正文。')
        try:
            text = self._chat([{'role': 'user', 'content': prompt}])
        except Exception as e:
            return False, self._friendly_error(e)
        text = text.strip().strip('"“”\'').replace('\n', ' ').replace('\r', ' ')
        text = ' '.join(text.split())
        if not text:
            return False, '生成结果为空，请重试'
        if len(text) > 800:
            text = text[:800]
        return True, text
