"""Real local Ollama + LangGraph. Without --search-url, search HTTP is a fixture."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    """调用指定本机模型执行智能体图，并根据参数选择搜索夹具、公共搜索或 SearXNG；保存脱敏结果，最终关闭服务和夹具。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen3:1.7b')
    parser.add_argument('--model-url', default='http://127.0.0.1:11434/v1')
    parser.add_argument('--public-search', action='store_true', help='Real keyless public search')
    parser.add_argument('--search-url', help='Real SearXNG URL with JSON search enabled')
    parser.add_argument('--topic', default='简述 LangGraph 与 Pi 架构如何配合')
    parser.add_argument('--output', type=Path, default=ROOT/'.local/companion-agent/ollama-graph.json')
    args = parser.parse_args()
    from app.modules.companion.api import AgentConfig
    from app.integrations.companion_agent import CompanionAgentService
    server = None
    if not args.search_url and not args.public_search:
        class Handler(BaseHTTPRequestHandler):
            """搜索协议的本机 HTTP 夹具，只提供固定文档来源，不代表真实搜索引擎连通。"""
            def do_GET(self):
                """返回固定 LangGraph/Pi 文档条目，供本机模型的工具调用与来源整合验证使用。"""
                body = json.dumps(dict(results=[
                    dict(title='LangGraph Graph API', url='https://docs.langchain.com/oss/python/langgraph/graph-api',
                         content='StateGraph uses nodes and edges with typed state, then compiles before execution.'),
                    dict(title='Pi agent core', url='https://github.com/earendil-works/pi',
                         content='Stateful agent with tool execution and event streaming. Model API, agent runtime and UI are separated.')])).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                """抑制本机夹具访问日志，避免混入智能体验证报告。"""
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    config = AgentConfig(enabled=True, provider='local', base_url=args.model_url, model=args.model,
        search_provider='web' if args.public_search else 'searxng', search_url=args.search_url or (f'http://127.0.0.1:{server.server_port}' if server else ''))
    events = []
    service = CompanionAgentService()
    try:
        started = time.monotonic()
        _, future = service.search(config, args.topic, events.append)
        # ReAct may make several bounded provider turns; leave room for cancellation.
        report = future.result(330)
        result = dict(model=args.model, search_mode='live-public-web' if args.public_search else ('live-searxng' if args.search_url else 'local-http-fixture'),
            seconds=round(time.monotonic()-started, 2), streaming_events=sum(e.stage=='streaming' for e in events),
            summary=report.summary, warning=report.warning, sources=len(report.sources),
            original_page_excerpts=sum('正文节选：' in s.snippet for s in report.sources),
            reasoning_visible=any('<think>' in e.text or '<analysis>' in e.text for e in events))
        if report.warning or not result['streaming_events'] or result['reasoning_visible']:
            raise RuntimeError('Local model verification failed: ' + report.warning)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        service.close()
        if server:
            server.shutdown()
            server.server_close()


if __name__ == '__main__': main()
