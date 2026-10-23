"""显式运行本机 Ollama 来信验收；隔离正式 Qt/工作线程，区分受控搜索和真实公开搜索。"""
import argparse
import faulthandler
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    """经显式命令调用本机模型；只创建 .local 隔离库，保存脱敏阶段证据和界面截图。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', default='qwen3.5:4b')
    parser.add_argument('--public-search', action='store_true')
    parser.add_argument('--search-provider', choices=('web', 'web-lite'), default='web')
    parser.add_argument('--timer', action='store_true', help='等待下一分钟排期，由正式三十秒 Qt 定时器触发')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/news-reliability/ollama')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to((ROOT / '.local').resolve()):
        parser.error('验收产物必须位于本仓库 .local 下，不能指向用户数据目录。')
    output.mkdir(parents=True, exist_ok=True)
    stack_log = (output / 'stacks.log').open('w', encoding='utf-8')
    faulthandler.dump_traceback_later(60, repeat=True, file=stack_log)
    data = output / ('data-' + uuid.uuid4().hex)
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from scripts.ui_test_support import prepare_fonts, load_fonts
    prepare_fonts()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from app.bootstrap.application import DesktopApplication
    from app.bootstrap.features import DesktopQueries
    from app.modules.companion.api import NewsConfig, SearchSource
    from app.integrations.companion_agent.model import CompanionModel
    from app.integrations.companion_agent.service import CompanionAgentService
    from app.integrations.ai.api import AIService
    from app.theme.theme_manager import ThemeManager
    from app.ui.main_window import MainWindow
    app = QApplication([])
    load_fonts()

    def local_now():
        """明确使用用户所在地 UTC+8 本机自然日，与统计日切分离。"""
        return datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)

    def utc_now():
        """记录真实 UTC 时间，不把固定夹具时刻当作实际触发证据。"""
        return datetime.now(timezone.utc).isoformat(timespec='seconds')

    stats = dict(model_turns=0, tool_calls=0, fixture_searches=0, notices=0, notice_after_commit=False)

    class CountedModel(CompanionModel):
        """使用真实模型传输，仅记录调用次数和工具数量，不记录消息、Key 或私有推理。"""
        def turn(self, *values, **kwargs):
            """计数成功返回的真实工具轮次；不会替模型选择工具或补造回答。"""
            stats['model_turns'] += 1
            turn = super().turn(*values, **kwargs)
            stats['tool_calls'] += len(turn.tool_calls)
            return turn

    class FixtureSearch:
        """固定公开形状资料，仅用于真实模型／图／持久化验证，不代表实际联网新闻。"""
        def __init__(self, config):
            """接受正式服务的配置快照，但不请求搜索服务。"""
            pass

        def validate(self):
            """受控资料无需端点或凭据。"""
            pass

        def search(self, topic, cancel):
            """返回明确标记验收夹具的资料，由真实模型决定如何整合及引用。"""
            stats['fixture_searches'] += 1
            return (SearchSource('LangGraph 验收夹具资料', 'https://example.org/langgraph-fixture',
                '这是受控验收资料，不是实时新闻。LangGraph 用 StateGraph 定义状态、节点和边，编译后执行。'
                '本次固定样本用于验证工具调用、来源引用和来信保存，不证明近期发布动态。'),)

    def fixture_page(url, cancel):
        """正文读取同样受控，避免夹具模式因模型选择阅读而意外访问外站。"""
        return '受控验收正文：LangGraph 使用图组织智能体行动和状态；此页不是新闻，发布日期未核实。'

    balance = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
    application = DesktopApplication(data, balance, {}, defaults={'reduced_motion': '1'},
                                     news_local_now=local_now, news_utc_now=utc_now)
    queries = DesktopQueries(application)
    window = service = None
    result = dict(model=args.model, mode='live-public-web' if args.public_search else 'controlled-search-and-pages',
                  search_provider=args.search_provider if args.public_search else 'fixture',
                  timer=args.timer, passed=False, network='real-local-ollama', data_directory=data.name)
    try:
        target = ((local_now() + timedelta(minutes=1)).replace(second=0, microsecond=0)
                  if args.timer else local_now() + timedelta(hours=1))
        config = NewsConfig(enabled=True, interests=('LangGraph 开源项目近期动态',), time=target.strftime('%H:%M'),
                            quiet_enabled=False)
        values = dict(companion_agent_enabled='1', companion_agent_provider='local',
                      companion_agent_base_url='http://127.0.0.1:11434/v1', companion_agent_model=args.model,
                      companion_agent_thinking='0', companion_agent_search_provider=args.search_provider, **config.settings_values())
        application.news_commands.save_settings(values, operation_id='local-verification', now_utc=utc_now()).result(10)
        theme = ThemeManager(app, data, queries.get_setting, queries.set_setting)
        theme.apply(theme.current_id(), persist=False)
        window = MainWindow(application.counter, queries, balance, checkin=application.checkin,
            rewards=application.rewards, achievements=application.achievements, challenge=application.practice,
            ai_service=AIService(queries), theme_manager=theme, data_dir=data, application=application)
        theme.register_window(window)
        window.show()
        agent = window._companion.agent
        agent.service.close()
        service = CompanionAgentService(model_factory=CountedModel,
            **({} if args.public_search else dict(search_factory=FixtureSearch)))
        agent.service = agent.news.service = service
        original_notice = agent.show_news_task

        def show_notice(task):
            """记录正式卡片展示时读模型中的通知标志，随后执行原生产展示方法。"""
            saved = next(item for item in queries.news_snapshot().tasks if item.task_id == task.task_id)
            stats['notices'] += 1
            stats['notice_after_commit'] = bool(saved.notified_at and saved.report)
            original_notice(task)

        agent.show_news_task = show_notice
        started = time.monotonic()
        result['planned_local'] = target.isoformat(timespec='seconds')
        print(json.dumps(dict(event='waiting', mode=result['mode'], planned=result['planned_local']), ensure_ascii=False), flush=True)
        context = nullcontext() if args.public_search else patch(
            'app.integrations.companion_agent.mcp_tools.article_excerpt', fixture_page)
        with context:
            if not args.timer:
                agent.news.run_now()
            last_state = None
            last_log = time.monotonic()
            while time.monotonic() - started < 400:
                # Qt 的 qWait 不保证给 Python 网络线程交出 GIL；处理事件后显式短睡眠。
                app.processEvents()
                time.sleep(.025)
                tasks = queries.news_snapshot().tasks
                state = tasks[0].state if tasks else 'waiting-for-timer'
                if state != last_state:
                    print(json.dumps(dict(event='task', state=state, model_turns=stats['model_turns']), ensure_ascii=False), flush=True)
                    last_state = state
                if time.monotonic() - last_log >= 20:
                    print(json.dumps(dict(event='progress', state=state, model_turns=stats['model_turns'],
                        service_busy=service.busy, controller_busy=agent.news.busy), ensure_ascii=False), flush=True)
                    last_log = time.monotonic()
                if tasks and state in ('completed', 'failed', 'cancelled') and not agent.news.busy:
                    if state != 'completed' or stats['notices']:
                        break
            tasks = queries.news_snapshot().tasks
            task = tasks[0] if tasks else None
            before = dict(stats)
            for _ in range(50):
                agent.news.tick()
            # 等工作线程屏障和 Qt 领取回调真正排空，避免把尚未启动的异步任务误判为去重成功。
            barrier = application.worker.submit(lambda _: None)
            drain_started = time.monotonic()
            while (not barrier.done() or agent.news._claim_pending) and time.monotonic() - drain_started < 5:
                app.processEvents()
                time.sleep(.025)
            app.processEvents()
            result.update(stats)
            result.update(seconds=round(time.monotonic() - started, 2), state=task.state if task else 'missing',
                error_code=task.error_code if task else '', attempt=task.attempt if task else 0,
                started_at=task.started_at if task else '', finished_at=task.finished_at if task else '',
                sources=len(task.report.sources) if task and task.report else 0,
                warning=task.report.warning if task and task.report else '',
                duplicate_wakeups_safe=(barrier.done() and not agent.news._claim_pending and not agent.news.busy
                    and before == stats and len(queries.news_snapshot().tasks) == 1))
            result['passed'] = bool(task and task.state == 'completed' and task.report and not task.report.warning
                and stats['tool_calls'] and stats['notice_after_commit'] and result['duplicate_wakeups_safe'])
            if agent.card.isVisible():
                agent.card.grab().save(str(output / 'card.png'))
            agent.open_settings(window)
            agent.settings.tabs.setCurrentIndex(2)
            QTest.qWait(100)
            agent.settings.grab().save(str(output / 'settings.png'))
    finally:
        if window:
            window._companion.shutdown()
            window.hide()
        if service:
            service.close()
        application.close()
        app.processEvents()
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False), flush=True)
        faulthandler.cancel_dump_traceback_later()
        stack_log.close()
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    sys.exit(main())
