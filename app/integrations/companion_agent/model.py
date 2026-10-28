"""网络适配层：把桌宠轮次转换为 OpenAI 兼容协议，支持云端与本地 /v1 服务。"""
import json
from datetime import datetime, timezone
from urllib.request import Request
from urllib.error import HTTPError
from ..ai.protocol import chat_payload, thinking_policy
from ...modules.companion.api import (summary_system_prompt, parse_oracle, validate_question,
                                     ORACLE_SCHEMA, oracle_system_prompt, AgentProgress)
from .search import AgentError, endpoint_url, check_cancel, error_stage, build_opener, NoRedirect
from .stream import read_model_text, read_model_turn


class UnsupportedOracleFormat(RuntimeError):
    """仅内部使用的明确格式参数拒绝信号，不携带供应商响应正文。"""
    pass


class CompanionModel:
    """单次任务的模型适配器；持有独立配置，网络读取由调用它的后台线程执行。"""
    def __init__(self, config, *, opener=None):
        """补全配置中的模型预设；opener 用于注入隔离传输夹具。"""
        self.config = config
        self.settings = config.model_settings()
        self.opener = opener

    def validate(self):
        """检查服务类型、地址、模型与所需密钥；配置无效时抛用户可读 AgentError。"""
        with error_stage('model', 'configuration'):
            self._validate()

    def _validate(self):
        """执行模型配置校验，外层赋予固定模型阶段而不暴露配置值。"""
        if self.config.provider not in ('openai', 'deepseek', 'local', 'custom'):
            raise AgentError('请选择可用的模型服务。')
        endpoint_url(self.settings['base_url'])
        if not self.settings['model']:
            raise AgentError('请填写模型名称。')
        if self.config.provider != 'local' and not self.settings['api_key'].strip():
            raise AgentError('请在桌宠自定义 → 智能体中填写模型 API Key。')

    def summarize(self, topic, sources, cancel, on_text=lambda _: None):
        """兼容入口：仅根据已提供来源生成正文，不执行 ReAct 或工具调用。"""
        current_time = datetime.now(timezone.utc).isoformat(timespec='seconds')
        messages = [
            {'role': 'system', 'content': summary_system_prompt(current_time)},
            {'role': 'user', 'content': json.dumps(dict(topic=topic,
                current_time=current_time, sources=[
                dict(number=i, title=s.title, excerpt=s.snippet) for i, s in enumerate(sources, 1)]), ensure_ascii=False)},
        ]
        return self._chat(messages, 1200, cancel, on_text)

    def test_connection(self, cancel):
        """用非思考短请求检查授权和模型可用性；通过不代表支持工具调用。"""
        return self._chat([{'role': 'user', 'content': '只回复 OK。'}], 32, cancel, lambda _: None, test=True)

    def turn(self, messages, tools, cancel, on_text=lambda _: None):
        """发送一次携带工具声明的模型请求，返回 AgentTurn，正文草稿经回调发布。"""
        return self._chat(messages, 1600, cancel, on_text, tools=tools)

    def judge(self, request_id, question, cancel, progress):
        """最多两次HTTP尝试完成严格概率判断；格式降级与纠错共享预算，网络错误不重试。"""
        question = validate_question(question)
        messages = [{'role': 'system', 'content': oracle_system_prompt()},
                    {'role': 'user', 'content': json.dumps({'question': question}, ensure_ascii=False)}]
        structured = self.config.provider != 'custom'
        response_format = ({'type': 'json_object'} if self.config.provider == 'deepseek' else
                           {'type': 'json_schema', 'json_schema': {
                               'name': 'sariana_oracle', 'strict': True, 'schema': ORACLE_SCHEMA}})
        for attempt in range(2):
            check_cancel(cancel)
            progress(AgentProgress(request_id, 'judging' if not attempt else 'repairing',
                                   '正在判断这个小问题。' if not attempt else '正在修正概率格式。'))
            try:
                text = self._chat(messages, 256, cancel, lambda _: None, short=True,
                                  response_format=response_format if structured else None)
            except UnsupportedOracleFormat:
                if attempt:
                    break
                structured = False
                continue
            check_cancel(cancel)
            try:
                return parse_oracle(text, request_id, question)
            except ValueError:
                # 不把无效正文拼回下一次上下文，也不向界面流式泄漏候选内容。
                messages.append({'role': 'user', 'content': '上次概率格式不合要求。请严格只输出三个整数，总和100的JSON对象。'})
        raise AgentError('模型没有返回有效的概率格式，请重试或更换模型。', stage='model', code='protocol')

    @staticmethod
    def assistant_message(turn):
        """将轮次转成可续接的 assistant 消息，保持工具 ID 及私有协议字段。"""
        message = dict(role='assistant', content=turn.text or None)
        if turn.tool_calls:
            message['tool_calls'] = [dict(id=c.id, type='function',
                function=dict(name=c.name, arguments=c.arguments)) for c in turn.tool_calls]
        if turn.reasoning:
            # DeepSeek 后续工具轮次要求重传前序推理；该字典只留在任务内存中。
            message['reasoning_content'] = turn.reasoning
        return message

    def _chat(self, messages, budget, cancel, on_text, *, test=False, tools=None,
              response_format=None, short=False):
        """统一组装鉴权/思考/工具参数并读响应；仅所配置模型端点收到模型密钥。

        tools=None 表示只读正文，非 None 返回工具轮次；测试始终走短小非思考路径。
        budget 是正文预算，开启思考时实际总预算由共享协议策略决定。
        """
        self.validate()
        check_cancel(cancel)
        base = endpoint_url(self.settings['base_url'])
        endpoint = base if base.endswith('/chat/completions') else base + '/chat/completions'
        headers = {'Content-Type': 'application/json'}
        if self.settings['api_key']:
            headers['Authorization'] = 'Bearer ' + self.settings['api_key']
        try:
            settings = dict(self.settings)
            policy = thinking_policy(settings, endpoint, settings['model'])
            # 普通模型无思考开关；连接测试显式禁用支持协议的思考以控制测试成本。
            if test or policy.protocol == 'none' or (short and policy.can_disable):
                settings['thinking'] = '0'
            payload = chat_payload(settings, endpoint, settings['model'], messages, budget)
        except ValueError:
            raise AgentError('当前模型无法关闭思考，请改用普通或非思考模型。', stage='model', code='configuration') from None
        payload['stream'] = True
        if response_format is not None:
            payload['response_format'] = response_format
        if tools is not None:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'
        if self.config.provider == 'local':
            payload['think'] = settings['thinking'] == '1'
        request = Request(endpoint, headers=headers, method='POST', data=json.dumps(payload).encode('utf-8'))
        # Ollama 冷启动实测超过25秒；只给本机模型120秒 I/O 预算，仍受图的合作截止和取消约束。
        timeout = 120 if self.config.provider == 'local' else 25
        opener = self.opener
        if response_format is not None:
            transport = opener or build_opener(NoRedirect()).open
            def format_opener(request, *, timeout):
                """仅明确的格式参数拒绝允许降级；其余HTTP错误交现有分类，不输出上游原文。"""
                try:
                    return transport(request, timeout=timeout)
                except HTTPError as error:
                    if error.code in (400, 422):
                        raw = error.read(8193)
                        description = raw.decode('utf-8', errors='replace').lower() if len(raw) <= 8192 else ''
                        if 'response_format' in description and any(word in description for word in
                                ('unsupported', 'not supported', 'not support')):
                            error.close()
                            raise UnsupportedOracleFormat() from None
                    raise
            opener = format_opener
        with error_stage('model'):
            if tools is not None:
                return read_model_turn(request, cancel, on_text, opener=opener, timeout=timeout)
            return read_model_text(request, cancel, on_text, opener=opener, timeout=timeout)
