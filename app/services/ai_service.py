"""AI 范文生成服务：OpenAI 兼容 API / 本地 Ollama / 自定义端点。

- Ollama 与 llama.cpp / LM Studio 均提供 OpenAI 兼容的 /v1/chat/completions
  端点，因此统一走同一协议，仅 base_url / api_key 不同。
- 全部使用标准库 urllib，无新增依赖；调用应在工作线程中进行。
"""
from __future__ import annotations

import json
import urllib.request

DEFAULTS = {
    'openai': {'base_url': 'https://api.openai.com/v1', 'model': 'gpt-4o-mini'},
    'ollama': {'base_url': 'http://127.0.0.1:11434/v1', 'model': 'llama3.2'},
}


class AIService:
    def __init__(self, repo):
        self._repo = repo

    # ---------- 配置 ----------
    def _cfg(self):
        return {
            'backend': self._repo.get_setting('ai_backend', 'off') or 'off',
            'base_url': self._repo.get_setting('ai_base_url', '') or '',
            'api_key': self._repo.get_setting('ai_api_key', '') or '',
            'model': self._repo.get_setting('ai_model', '') or '',
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
        body = json.dumps({
            'model': self._model(),
            'messages': messages,
            'max_tokens': max_tokens,
            'temperature': 0.8,
        }).encode('utf-8')
        req = urllib.request.Request(self._endpoint(), data=body,
                                     headers=self._headers(), method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode('utf-8'))
        return data['choices'][0]['message']['content']

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
        if not self.enabled():
            return False, 'AI 未启用（设置 → AI 配置）'
        try:
            reply = self._chat(
                [{'role': 'user', 'content': 'ping'}],
                max_tokens=8, timeout=20)
            return True, f'连接成功（{self.backend_label()} · {self._model()}）：{reply.strip()[:40]}'
        except Exception as e:
            return False, self._friendly_error(e)

    def generate(self, topic: str, lang: str = 'cn', length: int = 260):
        """生成一篇打字练习范文；返回 (成功, 文本或错误信息)。"""
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
