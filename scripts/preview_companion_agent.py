"""Isolated real desktop worker preview; sample report, no model requests or hooks."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from contextlib import nullcontext
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    """用隔离数据预览智能体配置、输入框和结果卡片并保存截图；真实本机模型或公共搜索须显式启用对应参数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive', action='store_true')
    parser.add_argument('--test-local-model', action='store_true', help='Explicit real Ollama draft connection test')
    parser.add_argument('--test-public-search', action='store_true', help='Explicit real keyless search and local model through Qt')
    parser.add_argument('--topic', default='Python 编程语言官方网站', help='Topic for explicit live search preview')
    parser.add_argument('--label', default='', help='Legacy preview marker; kept out of product window titles')
    parser.add_argument('--output', type=Path, default=ROOT/'.local/companion-agent/preview')
    args = parser.parse_args()
    if not args.interactive:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from scripts.ui_test_support import prepare_fonts, load_fonts
    prepare_fonts()
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QPoint, QEvent, QRect, QSize
    from PySide6.QtGui import QPainter, QPixmap, QColor
    from PySide6.QtTest import QTest
    from app.bootstrap.application import DesktopApplication
    from app.bootstrap.features import DesktopQueries
    from app.modules.companion.api import AgentReport, SearchSource
    from app.integrations.ai.api import AIService
    from app.theme.theme_manager import ThemeManager
    from app.ui.main_window import MainWindow
    from app.ui.companion.agent_settings import AgentSettingsDialog
    app = QApplication([])
    load_fonts()
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        from PySide6.QtGui import QFontDatabase
        serif = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/simsun.ttc'
        if serif.is_file():
            QFontDatabase.addApplicationFont(str(serif))
    args.output.mkdir(parents=True, exist_ok=True)
    if args.interactive:
        persistent = args.output / ('interactive-data-' + uuid.uuid4().hex)
        persistent.mkdir()
        data_context = nullcontext(str(persistent))
    else:
        data_context = tempfile.TemporaryDirectory(dir=args.output)
    with data_context as data:
        balance = json.loads((ROOT/'config/balance.json').read_text(encoding='utf-8'))
        application = DesktopApplication(data, balance, {}, defaults={'reduced_motion': '1'})
        queries = DesktopQueries(application)
        theme = ThemeManager(app, data, queries.get_setting, queries.set_setting)
        theme.apply(theme.current_id(), persist=False)
        window = MainWindow(application.counter, queries, balance,
            checkin=application.checkin, rewards=application.rewards, achievements=application.achievements,
            challenge=application.practice, ai_service=AIService(queries), theme_manager=theme,
            data_dir=Path(data), application=application)
        theme.register_window(window)
        window.show()
        agent = window._companion.agent
        window.setWindowTitle('Sariana · 界面预览')
        application.set_settings({'companion_agent_enabled': '1', 'companion_agent_provider': 'local'}).result(5)
        report = AgentReport('sample', '最近有哪些值得留意的天文发现？',
            '给你捎来一点宇宙的新鲜事。\n\n示例卡片展示：先用短段落概括，再逐条整理重点。'
            '\n\n• 新发现为什么值得关注？\n• 资料有哪些共同结论？\n• 哪些信息还需要继续核对？'
            '\n\n你可以滚动阅读，也可以打开详情查看原始来源。\n\n这是界面示例，不是实时新闻。',
            (SearchSource('示例来源 · LangGraph 文档', 'https://docs.langchain.com/oss/python/langgraph/graph-api',
                          '界面示例资料，不代表本次已经进行真实联网搜索。'),),
            datetime.now(timezone.utc).isoformat())
        agent.report = report
        agent.show_last_report()
        QTest.qWait(100)
        window.grab().save(str(args.output/'window.png'))
        agent.card.grab().save(str(args.output/'card.png'))
        agent.open_search()
        agent.input.grab().save(str(args.output/'input.png'))
        agent.input.hide()
        app.sendEvent(window._companion.view, QEvent(QEvent.Enter))
        agent.actions.grab().save(str(args.output/'actions.png'))
        agent.actions.hide()
        agent.open_detail()
        agent.detail.grab().save(str(args.output/'detail.png'))
        agent.detail.hide()
        agent.open_settings(window)
        if args.test_local_model:
            import time
            agent.settings.test_model()
            deadline = time.monotonic() + 60
            while agent.settings._job is not None and time.monotonic() < deadline:
                QTest.qWait(20)
            if '模型连接成功' not in agent.settings.model_status.text():
                raise RuntimeError(agent.settings.feedback.text())
            print(agent.settings.model_status.text())
        QTest.qWait(100)
        agent.settings.grab().save(str(args.output/'settings.png'))
        agent.settings.tabs.setCurrentIndex(1)
        QTest.qWait(50)
        agent.settings.grab().save(str(args.output/'settings-search.png'))
        agent.settings.tabs.setCurrentIndex(2)
        QTest.qWait(50)
        agent.settings.grab().save(str(args.output/'settings-future.png'))
        agent.settings.tabs.setCurrentIndex(0)
        if not args.test_public_search and not args.test_local_model:
            # Composite the real Qt surfaces at their actual desktop positions.
            # The supplied report is still a sample; this does not call a model.
            from app.ui.companion.agent_visuals import colors
            companion = window._companion
            application.set_settings({'companion_mode': 'desktop',
                'companion_position': json.dumps([340, 425])}).result(5)
            QTest.qWait(100)
            companion.switch_mode('desktop', persist=False, desktop_position=QPoint(340, 425))
            agent.settings.hide()
            agent._place(agent.card)
            agent._place(agent.actions, above=False)
            agent.card.show()
            agent.actions.show()
            companion._render()
            QTest.qWait(50)

            def scene(name, widgets):
                """按多个浮窗的全局位置合成一张带边距的预览图，保存到本次指定截图目录。"""
                bounds = QRect()
                for widget in widgets:
                    bounds = bounds.united(QRect(widget.mapToGlobal(QPoint()), widget.size()))
                canvas = QPixmap(bounds.size() + QSize(48, 48))
                canvas.fill(QColor(colors().bg))
                painter = QPainter(canvas)
                for widget in widgets:
                    painter.drawPixmap(widget.mapToGlobal(QPoint()) - bounds.topLeft() + QPoint(24, 24), widget.grab())
                painter.end()
                canvas.save(str(args.output/name))

            scene('scene.png', [companion.view, agent.actions, agent.card])
            agent.actions.hide()
            companion.set_agent_feedback('focused', '我在努力思考，把重点串起来。')
            agent.card.show_progress('找到一些有趣的线索，我正在读原文、核对来源。', 'reading')
            agent._place(agent.card)
            QTest.qWait(50)
            scene('thinking-scene.png', [companion.view, agent.card])
            companion.set_agent_feedback()
            agent.show_last_report()
            application.set_settings({'companion_mode': 'window'}).result(5)
            QTest.qWait(50)
            companion.switch_mode('window', persist=False)
        if args.test_public_search:
            import time
            agent.settings.hide()
            agent.search(args.topic)
            deadline = time.monotonic() + 120
            while agent._busy and time.monotonic() < deadline:
                QTest.qWait(20)
                # Let the Python graph thread run as well as the Qt event queue.
                time.sleep(.01)
            if agent._busy or agent.report is report or agent.report.warning:
                message = agent.card.body.toPlainText()
                agent.shutdown()
                window.hide()
                application.close()
                raise RuntimeError(message)
            agent.card.grab().save(str(args.output/'live-search-card.png'))
            print('真实 Qt 搜索成功 · 来源 ' + str(len(agent.report.sources)))
        if args.interactive:
            agent.show_last_report()
            agent.open_settings(window)
            app.setQuitOnLastWindowClosed(True)
            app.exec()
        window._companion.shutdown()
        window.hide()
        application.close()
    print(str(args.output))


if __name__ == '__main__': main()
