"""来信配置与通知的隔离 Qt 回归，不使用真实模型或用户数据库。"""
from unittest.mock import patch
from PySide6.QtCore import QTime
from test_ui_workflow import APP, UIFixture
from app.modules.companion.api import NewsConfig, MemorySnapshot
from app.ui.companion.news_settings import NewsSettingsPanel
from app.ui.companion.agent_settings import AgentSettingsDialog
from test_companion_news_desktop import NewsDesktopTests


class NewsSettingsTests(UIFixture):
    """配置草稿保持原生时间输入、显式保存和取消隔离。"""
    def test_default_and_quiet_validation(self):
        """默认关闭，等长安静时段拒绝保存，兴趣输入规范化去重。"""
        panel = NewsSettingsPanel(NewsConfig(), MemorySnapshot())
        self.addCleanup(panel.deleteLater)
        self.assertFalse(panel.enabled.isChecked())
        panel.interests.setPlainText('AI\nAI\n天文学')
        panel.quiet_end.setTime(panel.quiet_start.time())
        with self.assertRaises(ValueError):
            panel.values()
        panel.quiet_end.setTime(QTime(8, 0))
        self.assertEqual(NewsConfig.from_values(panel.values()).interests, ('AI', '天文学'))

    def test_cancel_keeps_news_draft_out_of_storage(self):
        """取消不会把兴趣或排期草稿写入本地设置。"""
        dialog = AgentSettingsDialog(self.repo)
        self.addCleanup(dialog.deleteLater)
        dialog.news_panel.interests.setPlainText('尚未保存的兴趣')
        dialog.reject()
        self.assertIsNone(self.repo.get_setting('companion_news_interests'))

    def test_all_sections_share_theme_and_keep_drafts(self):
        """第四个记忆入口也有同一纸张色系，切换不丢来信草稿或索引越界。"""
        dialog = AgentSettingsDialog(self.repo)
        self.addCleanup(dialog.deleteLater)
        dialog.news_panel.interests.setPlainText('草稿兴趣')
        for section in range(4):
            dialog._tab_tone(section)
        self.assertEqual(dialog.news_panel.interests.toPlainText(), '草稿兴趣')


class NewsNoticeTests(NewsDesktopTests):
    """沿用真实数据库工作线程夹具验证通知延后，模型仍为确定夹具。"""
    def test_hidden_or_practicing_defers_notice(self):
        """隐藏、练习中和搜索卡占用时只保存，不受理通知；恢复后只显示一封。"""
        self.enable()
        self.pet.view.hide()
        self.controller.tick()
        self.wait_report()
        self.assertFalse(self.agent.shown)
        self.pet.practicing = True
        self.pet.view.show()
        self.controller.tick()
        APP.processEvents()
        self.assertFalse(self.agent.shown)
        self.pet.practicing = False
        self.agent.occupied = True
        self.controller.tick()
        self.assertFalse(self.agent.shown)
        self.agent.occupied = False
        self.controller.tick()
        from test_ui_workflow import pump_until
        self.assertTrue(pump_until(lambda: bool(self.agent.shown)))
        self.assertEqual(len(self.agent.shown), 1)

    def test_notice_accept_failure_does_not_show_card(self):
        """受理事务失败不能提前弹卡，移除故障后只重试通知，不再次运行模型。"""
        self.enable()
        self.application.worker.submit(lambda context: context['repo']._conn.execute(
            "CREATE TRIGGER no_notice BEFORE UPDATE OF notified_at ON companion_news_tasks "
            "BEGIN SELECT RAISE(FAIL,'test'); END")).result(5)
        self.controller.tick()
        self.wait_report()
        from test_ui_workflow import pump_until
        self.assertTrue(pump_until(lambda: not self.controller._notice_pending))
        self.assertFalse(self.agent.shown)
        self.assertEqual(len(self.model_calls), 1)
