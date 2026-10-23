"""来信无网络自检与历史构建清单兼容，不运行打包或安装器。"""
from pathlib import Path
import tempfile
import unittest
from app.integrations.companion_agent.probe import selfcheck
from build_release import news_runtime_modules


class NewsReleaseTests(unittest.TestCase):
    """当前源码要求来信模块，旧版不存在来信文件时保留原构建行为。"""
    def test_news_selfcheck_uses_no_network_or_database(self):
        """真实 LangGraph 来信路径与排期规则均进入冻结自检。"""
        result = selfcheck()
        self.assertTrue(result['news'])
        self.assertTrue(result['news_schedule'])
        self.assertFalse(result['network'])
        self.assertFalse(result['database'])

    def test_historical_source_does_not_require_news_modules(self):
        """旧版本没有来信模块不强制增加当前模块，避免新工具无法补编历史包。"""
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=root / '.local') as directory:
            source = Path(directory)
            self.assertEqual(news_runtime_modules(source), [])
            path = source / 'app/modules/companion/news.py'
            path.parent.mkdir(parents=True)
            path.write_text('"""test"""', encoding='utf-8')
            required = news_runtime_modules(source)
            self.assertIn('app.ui.companion.memory_page', required)
            self.assertIn('app.workflows.companion_news', required)
            for name in ('failures', 'news_status'):
                (path.parent / (name + '.py')).write_text('"""fixture"""', encoding='utf-8')
            required = news_runtime_modules(source)
            self.assertIn('app.modules.companion.failures', required)
            self.assertIn('app.modules.companion.news_status', required)
