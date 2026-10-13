"""OpenAI 兼容响应读取；聚合正文与用量，不保留思考内容。"""
import json


def _events(response):
    """读取 SSE data 事件，兼容空行、注释与多行 data。"""
    fields = []
    for line in response:
        line = line.decode('utf-8').rstrip('\r\n')
        if not line:
            if fields:
                yield '\n'.join(fields)
                fields.clear()
        elif line.startswith('data:'):
            fields.append(line[5:].lstrip(' '))
    if fields:
        yield '\n'.join(fields)


def read_chat_response(response, capture_usage):
    if 'text/event-stream' not in response.headers.get('Content-Type', '').lower():
        result = json.loads(response.read().decode('utf-8'))
        capture_usage(result)
        return result
    text = []
    reasoning_seen = False
    finish = None
    for event in _events(response):
        if event == '[DONE]':
            break
        data = json.loads(event)
        if not isinstance(data, dict) or data.get('error'):
            raise ValueError('AI 服务返回流式错误，请检查接口与模型配置')
        capture_usage(data)
        choices = data.get('choices')
        if not isinstance(choices, list):
            raise ValueError('AI 流式响应格式不正确')
        for choice in choices:
            if not isinstance(choice, dict):
                raise ValueError('AI 流式响应格式不正确')
            if choice.get('index', 0) != 0:
                continue
            delta = choice.get('delta') or {}
            if not isinstance(delta, dict):
                raise ValueError('AI 流式响应格式不正确')
            content = delta.get('content')
            if content is not None:
                if not isinstance(content, str):
                    raise ValueError('AI 流式响应正文不是文本')
                text.append(content)
            reasoning_seen = reasoning_seen or bool(delta.get('reasoning_content'))
            if choice.get('finish_reason'):
                finish = choice['finish_reason']
    if finish is None:
        raise ValueError('AI 流式响应提前结束，正文未完成，请重试')
    return {'choices': [{'finish_reason': finish,
                         'message': {'content': ''.join(text), 'reasoning_content': reasoning_seen}}]}
