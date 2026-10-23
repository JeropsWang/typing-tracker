"""网络线程中的 LangGraph ReAct 编排：模型选择行动，工具观察回到下一轮判断。

本模块执行次数、上下文、截止时间与取消边界；不读写数据库，不访问 Qt 控件。
"""
import json
import re
import time
from datetime import datetime, timezone
from typing import TypedDict
from ...modules.companion.api import (AgentReport, AgentProgress, AgentRunLimits,
                                      search_system_prompt, news_system_prompt, agent_failure_code)
from .search import AgentError, AgentCancelled, check_cancel
from .model import CompanionModel
from .mcp_tools import SearchMcpServer, McpToolClient


class SearchState(TypedDict, total=False):
    """单次图执行的内存状态；messages 含协议续接数据，不进入最终报告。"""
    messages: list
    turns: int
    actions: int
    pending: tuple
    summary: str
    warning: str
    correction: bool
    failure_code: str


class RunSignal:
    """把用户取消和合作式截止时间传给网络工具；阻塞 I/O 仍由传输超时结束。"""
    def __init__(self, parent, seconds):
        """捕获原取消信号，用单调时钟计算本次任务的秒级截止时间。"""
        self.parent, self.deadline = parent, time.monotonic() + seconds

    def is_set(self):
        """用户取消返回 True；超时抛 AgentError，以便界面区分取消与失败。"""
        if self.parent.is_set():
            return True
        if time.monotonic() >= self.deadline:
            raise AgentError('这次寻找资料用时太久，先把已有线索交给你。', code='timeout')
        return False


def run_search(request_id, topic, model, search, cancel, progress, *, limits=None, reader=None):
    """保持主动搜索兼容入口，复用有界图执行器，不改变话题和工具权限。"""
    return _run_agent(request_id, topic, model, search, cancel, progress, limits=limits, reader=reader)


def run_news(request_id, request, model, search, cancel, progress, *, limits=None, reader=None):
    """以独立来信契约运行同一张图；无来源结果不能被当成成功持久化。"""
    report = _run_agent(request_id, request.topic, model, search, cancel, progress,
                         limits=limits, reader=reader, news_request=request)
    if not report.sources:
        raise AgentError(report.warning or '这次没有找到可引用的新动态。')
    return report


def _run_agent(request_id, topic, model, search, cancel, progress, *, limits=None, reader=None, news_request=None):
    """执行有界搜索任务并返回只读报告，progress 回调只传数据给 UI 桥接层。

    model/search 是可替换的网络适配器，reader 可注入原文读取夹具。
    用户取消向外抛 AgentCancelled；已有来源时保留资料并报告失败/限额警告。
    """
    try:
        from langgraph.graph import StateGraph, START, END
    except ImportError:
        raise AgentError('缺少 LangGraph 依赖，请安装 requirements.txt 后重试。') from None
    limits = limits or AgentRunLimits()
    if (min(limits.model_turns, limits.tool_calls, limits.searches, limits.sources, limits.context_chars) < 1
            or limits.page_reads < 0 or limits.sources > 8 or limits.seconds <= 0):
        raise ValueError('Invalid agent run limits')
    signal = RunSignal(cancel, limits.seconds)

    def announce(stage, text):
        """检查任务仍有效后，以稳定请求 ID 发布真实阶段或可见正文。"""
        check_cancel(signal)
        progress(AgentProgress(request_id, stage, text))

    server = SearchMcpServer(search, signal, limits, announce, reader=reader)
    client = McpToolClient(server)
    declarations = client.declarations()
    seen_ids = set()

    def incomplete(message, *, failure_code=''):
        """构造失败/限额终态，保留工具证据及明确终止类别，不以无来源覆盖超时。"""
        check_cancel(cancel)
        text = ('资料找到了，暂时没能整理成回答。你可以先查看下面的搜索摘录。'
                if server.sources else '这次没有找到可引用的资料，可以换个关键词再试试。')
        return dict(summary=text, warning=message, pending=(), failure_code=failure_code)

    def model_node(state):
        """请求一轮模型判断，分流工具调用或最终答案，并校验来源与引用编号。"""
        check_cancel(cancel)
        try:
            check_cancel(signal)
            if state['turns'] >= limits.model_turns:
                return incomplete('已达到本次判断次数上限。')
            if len(json.dumps(state['messages'], ensure_ascii=False)) > limits.context_chars:
                return incomplete('本次资料已达到上下文上限，请缩小话题范围。')
            announce('summarizing', '我在想该从哪里找线索…' if not server.sources
                     else '我正在对照资料，判断还需不需要补充…')
            last_partial = 0.0
            def partial(text):
                """取得来源后节流发布可见草稿；整轮完成校验后才确认为最终报告。"""
                nonlocal last_partial
                check_cancel(signal)
                now = time.monotonic()
                # 第一轮无证据时只显示思考提示，避免把模型记忆伪装成搜索草稿。
                if server.sources and text and now - last_partial >= .08:
                    announce('streaming', text)
                    last_partial = now
            turn = model.turn(state['messages'], declarations, signal, on_text=partial)
            check_cancel(signal)
            messages = state['messages'] + [CompanionModel.assistant_message(turn)]
            update = dict(messages=messages, turns=state['turns'] + 1, pending=turn.tool_calls)
            if turn.tool_calls:
                # 同一标识不能指向两个行动，否则后续 tool 消息无法可靠对应请求。
                identifiers = {c.id for c in turn.tool_calls}
                if len(identifiers) != len(turn.tool_calls) or identifiers & seen_ids:
                    return incomplete('模型返回重复的工具调用标识，已停止执行。')
                seen_ids.update(identifiers)
                return update
            invalid_citation = any(int(i) < 1 or int(i) > len(server.sources)
                                   for i in re.findall(r'\[(\d+)\]', turn.text))
            if (not server.sources or invalid_citation) and not state['correction']:
                # 只允许一次结果修正；错误工具观察仍可在总轮次预算内继续补搜。
                instruction = ('尚未取得搜索证据，请先调用 web_search；若搜索失败请明确说明，不能凭记忆回答。'
                               if not server.sources else '回答引用了不存在的 source_id，请使用工具返回的真实编号修正回答。')
                return dict(update, correction=True, messages=messages + [dict(role='user', content=instruction)])
            if not server.sources:
                return incomplete((server.last_error or '搜索没有返回可引用的资料。') if server.searches
                                  else '模型未执行有效搜索，请使用支持原生工具调用的模型。')
            if invalid_citation or not turn.text.strip():
                return incomplete('模型未提供可用的资料回答。')
            announce('streaming', turn.text)
            return dict(update, summary=turn.text, warning='')
        except AgentCancelled:
            raise
        except AgentError as error:
            check_cancel(cancel)
            if not server.sources:
                raise
            return incomplete(str(error), failure_code=agent_failure_code(error))

    def tools_node(state):
        """顺序执行本轮工具调用，把成功或错误观察按 tool_call_id 回填上下文。"""
        try:
            check_cancel(signal)
            if state['turns'] >= limits.model_turns:
                return incomplete('已达到本次判断次数上限，未继续请求工具。')
            messages, actions = list(state['messages']), state['actions']
            for call in state['pending']:
                check_cancel(signal)
                if actions >= limits.tool_calls:
                    return incomplete('已达到本次工具调用上限。')
                # 错误参数和未知工具也消耗预算，防止模型在校验失败上无限循环。
                actions += 1
                result = client.execute(call)
                check_cancel(signal)
                messages.append(dict(role='tool', tool_call_id=call.id,
                                     content=json.dumps(result, ensure_ascii=False)))
            return dict(messages=messages, actions=actions, pending=())
        except AgentCancelled:
            raise
        except AgentError as error:
            check_cancel(cancel)
            return incomplete(str(error), failure_code=agent_failure_code(error))

    def next_node(state):
        """按图状态选择终止、执行工具或再调用模型，不在 UI 中维护行动循环。"""
        if 'summary' in state:
            return END
        return 'tools' if state.get('pending') else 'model'

    graph = StateGraph(SearchState)
    graph.add_node('model', model_node)
    graph.add_node('tools', tools_node)
    graph.add_edge(START, 'model')
    graph.add_conditional_edges('model', next_node)
    graph.add_conditional_edges('tools', next_node)
    from langsmith import tracing_context
    current = datetime.now(timezone.utc).isoformat(timespec='seconds')
    system = (news_system_prompt(current, news_request, limits) if news_request
              else search_system_prompt(current, limits))
    # 兴趣是有结构的用户数据，不向消息中添加模型配置、统计或被动输入。
    user = (json.dumps(dict(task_type='news', local_date=news_request.local_day,
                            interests=news_request.interests), ensure_ascii=False)
            if news_request else topic)
    messages = [dict(role='system', content=system), dict(role='user', content=user)]
    with tracing_context(enabled=False):
        # 即使外部环境开启 tracing，也不上传桌宠话题和含协议推理的上下文。
        state = graph.compile().invoke(dict(messages=messages, turns=0, actions=0, correction=False),
                                       config={'recursion_limit': limits.model_turns * 2 + 3})
    check_cancel(cancel)
    # 对外报告只含可见答案和真实来源，协议推理与工具对话留在本次运行内存中。
    if news_request and not server.sources:
        # MCP 错误先反馈模型；最终没有证据时仍保留最后一次真实搜索失败类别。
        stage, code = (state.get('failure_code') or server.last_search_failure_code
                       or server.last_failure_code or 'agent.no_sources').split('.')
        raise AgentError(state.get('warning') or '这次没有找到可引用的新动态。', stage=stage, code=code)
    return AgentReport(request_id, topic, state['summary'], tuple(server.sources),
                       datetime.now(timezone.utc).isoformat(timespec='seconds'), state.get('warning', ''))
