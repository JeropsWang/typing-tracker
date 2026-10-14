"""Bounded public-page excerpts; failures retain the original search snippet."""
import ipaddress
import socket
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, getproxies
from .search import AgentError, check_cancel, MAX_RESPONSE


def public_page(url):
    """校验公开 HTTPS 地址及 DNS，拒绝内网/凭据；代理 Fake-IP 只对公开域名映射例外。"""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise AgentError('仅读取公开 HTTPS 资料。')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    # A configured HTTPS proxy resolves the public host itself. Fake-IP DNS is
    # common in local proxies; allow that mapping only for domain requests sent
    # through such a proxy, never for a direct benchmark/private-IP URL.
    proxy_dns = literal is None and bool(getproxies().get('https'))
    benchmark = ipaddress.ip_network('198.18.0.0/15')
    def allowed(address):
        """判断解析 IP 是否全球可路由，或是经 HTTPS 代理使用的域名 Fake-IP 映射。"""
        value = ipaddress.ip_address(address)
        return value.is_global or (proxy_dns and value.version == 4 and value in benchmark)
    if not addresses or any(not allowed(row[4][0]) for row in addresses):
        raise AgentError('不读取本机或内网资料。')


class PublicRedirect(HTTPRedirectHandler):
    """公开原文的逐跳地址校验器，重定向不能绕过内网拒绝。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """校验下一跳公开地址后才交由默认 HTTPS 重定向处理。"""
        public_page(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def article_excerpt(url, cancel):
    """有界读取已许可公开 HTML，提取日期和最多 2500 字正文；读取失败返回空串，取消仍抛出。"""
    check_cancel(cancel)
    try:
        public_page(url)
        request = Request(url, headers={'User-Agent':'Sariana/companion-search', 'Accept':'text/html'})
        with build_opener(PublicRedirect()).open(request, timeout=6) as response:
            if 'text/html' not in response.headers.get('Content-Type', '').lower(): return ''
            raw = response.read(MAX_RESPONSE + 1)
            encoding = response.headers.get_content_charset() or 'utf-8'
        check_cancel(cancel)
        if len(raw) > MAX_RESPONSE: return ''
        from .edge_search import ArticleDOM
        parser = ArticleDOM()
        parser.feed(raw.decode(encoding, errors='replace'))
        dates = ('网页标注日期：' + ', '.join(parser.dates[:3]) + '\n') if parser.dates else ''
        return (dates + '\n'.join(parser.text))[:2500]
    except (OSError, ValueError, LookupError, AgentError):
        check_cancel(cancel)
        return ''
