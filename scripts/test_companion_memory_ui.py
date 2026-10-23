"""记忆双视角的原生 Qt 展示回归，文本内容均为隔离样例。"""
from concurrent.futures import Future
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime, timezone
from test_ui_workflow import APP, UIFixture, pump_until
from app.modules.companion.api import MemorySnapshot, NewsConfig, NewsTask, AgentReport, SearchSource
from app.ui.companion.memory_page import MemoryPage


class MemoryPageTests(UIFixture):
    """同一数据源、纯文本显示和删除失败不移除记录。"""
    def page(self):
        """构造脱离数据库的不可变样例与受控异步删除能力。"""
        self.future = Future()
        report = AgentReport('r', '话题', '<img src=x> ' + '中文很长' * 100,
                             (SearchSource('<b>来源</b>', 'https://example.org', '摘录'),),
                             datetime.now(timezone.utc).isoformat())
        task = NewsTask('news:2026-10-20', 'auto', '2026-10-20', '09:00', 'f', 'completed', 1, 'r',
                        '2026-10-20T01:00:00+00:00', report=report)
        snapshot = MemorySnapshot(NewsConfig(interests=('天文学',)), (task,))
        presenter = SimpleNamespace(snapshot=lambda: snapshot, forget=lambda *args: self.future)
        page = MemoryPage(presenter, None)
        self.addCleanup(page.deleteLater)
        page.show()
        APP.processEvents()
        return page

    def test_both_views_share_record_identity(self):
        """切换开发者标签后选中相同 ID，网络内存结果不会出现额外保存记录。"""
        page = self.page()
        self.assertEqual(page.records.count(), 1)
        page.views.setCurrentIndex(1)
        self.assertIn('news:2026-10-20', page.developer_text.toPlainText())
        self.assertEqual(page.selected_id, 'news:2026-10-20')

    def test_source_html_and_long_chinese_are_plain_text(self):
        """来源和模型标记作为字面文本显示，不执行 HTML，也不截断正文。"""
        page = self.page()
        self.assertIn('<img src=x>', page.content.toPlainText())
        self.assertIn('<b>来源</b>', page.content.toPlainText())

    def test_failed_forget_preserves_card_and_cancel_does_not_write(self):
        """取消删除不提交；提交失败保留原卡片和同一删除重试操作 ID。"""
        from PySide6.QtWidgets import QMessageBox
        page = self.page()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.No):
            page.forget_selected()
        self.assertFalse(page._saving)
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            page.forget_selected()
        self.future.set_exception(RuntimeError('test'))
        self.assertTrue(pump_until(lambda: not page._saving))
        self.assertEqual(page.records.count(), 1)
        self.assertIn('失败', page.status.text())
