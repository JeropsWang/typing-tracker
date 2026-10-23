"""有界来信报告序列化；写入和读取使用同一验证，不把存储 JSON 当可信 HTML。"""
from datetime import datetime, timedelta
import ipaddress
import json
import re
from urllib.parse import urlsplit

from .agent import AgentReport, SearchSource

MAX_REPORT_BYTES = 256_000


def _text(value, maximum, *, empty=True):
    """验证单个纯文本字段，拒绝错误类型和超限内容，不静默截断引用。"""
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError('来信字段为空、过长或格式不正确。')
    return value


def _source(value):
    """验证来源字段和公开链接形状；不解析 DNS、不请求地址、不接受凭据与内网字面量。"""
    if not isinstance(value, dict) or set(value) != {'title', 'url', 'snippet'}:
        raise ValueError('来信来源格式不正确。')
    title = _text(value['title'], 300, empty=False)
    url = _text(value['url'], 2048, empty=False)
    snippet = _text(value['snippet'], 2500)
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower().rstrip('.')
        if (parsed.scheme not in ('http', 'https') or not host or parsed.username is not None
                or parsed.password is not None or parsed.port == 0 or '\\' in url
                or any(ord(char) < 33 or ord(char) == 127 for char in url)
                or host == 'localhost' or host.endswith(('.localhost', '.local', '.internal'))):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            # 浏览器可能把 127.1、八进制或十六进制标签解释为 IPv4；不当作普通域名。
            if '.' not in host or all(re.fullmatch(r'(?:\d+|0x[0-9a-f]+)', part) for part in host.split('.')):
                raise ValueError
        else:
            if not address.is_global:
                raise ValueError
    except ValueError:
        raise ValueError('来信来源必须是无凭据的公开网页地址。') from None
    return SearchSource(title, url, snippet)


def decode_report(text: str) -> AgentReport:
    """读取严格字段集合的有界 JSON，损坏或缺来源时抛可读错误，不返回假成功。"""
    if not isinstance(text, str) or len(text) > MAX_REPORT_BYTES or len(text.encode('utf-8')) > MAX_REPORT_BYTES:
        raise ValueError('来信存储内容超过读取上限。')
    try:
        value = json.loads(text)
        if not isinstance(value, dict) or set(value) != {'request_id', 'topic', 'summary', 'sources', 'fetched_at', 'warning'}:
            raise ValueError
        request_id = _text(value['request_id'], 128, empty=False)
        topic = _text(value['topic'], 200, empty=False)
        summary = _text(value['summary'], 12_000, empty=False)
        warning = _text(value['warning'], 1000)
        stamp = _text(value['fetched_at'], 40, empty=False)
        fetched = datetime.fromisoformat(stamp)
        if fetched.tzinfo is None or fetched.utcoffset() != timedelta(0):
            raise ValueError
        sources = value['sources']
        if not isinstance(sources, list) or not 1 <= len(sources) <= 8:
            raise ValueError
        return AgentReport(request_id, topic, summary, tuple(_source(item) for item in sources), stamp, warning)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError('来信损坏、超限或没有安全可引用来源，无法读取。') from None


def encode_report(report: AgentReport) -> str:
    """只序列化可见报告与来源并执行读回校验，私有推理与原始协议没有保存入口。"""
    try:
        text = json.dumps(dict(request_id=report.request_id, topic=report.topic, summary=report.summary,
                               sources=[dict(title=item.title, url=item.url, snippet=item.snippet)
                                        for item in report.sources],
                               fetched_at=report.fetched_at, warning=report.warning), ensure_ascii=False)
    except (TypeError, AttributeError, ValueError):
        raise ValueError('来信报告格式不正确。') from None
    decode_report(text)
    return text
