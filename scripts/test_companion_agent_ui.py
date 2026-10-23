"""Qt presenter delivery, hover tools, safe details and draft preservation."""
from concurrent.futures import Future
from datetime import datetime, timezone
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from test_ui_workflow import UIFixture, APP, pump_until
from app.modules.companion.api import AgentReport, SearchSource, AgentProgress
from app.ui.companion.agent_settings import AgentSettingsDialog


class ControlledService:
    """由测试控制 Future/进度的桌宠能力，支持制造迟到回传。"""
    def __init__(self):
        """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
        self.future = Future()
        self.cancelled = False
        self.closed = False
        self.calls = 0
    def search(self, config, topic, progress):
        """提供本例搜索结果/阻塞/错误观察，不请求真实搜索上游。"""
        self.calls += 1
        self.topic, self.progress = topic, progress
        return 'request-one', self.future
    def cancel(self, request_id=None):
        """记录取消或作废本例结果，保留迟到回传条件用于检查过滤。"""
        self.cancelled = True
    def close(self):
        """结束本例模拟服务生命周期，供清理/退出行为验证。"""
        self.closed = True


class CompanionAgentUITests(UIFixture):
    """桌宠浮层、配置草稿与迟到结果的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def test_model_test_is_draft_only_and_cancel_discards_success(self):
        """验证草稿测试不保存，取消后成功结果也被丢弃。"""
        from app.modules.companion.api import AgentConnectionResult
        class Setup:
            """受控草稿检查能力，以 Future 驱动完成/取消场景。"""
            def __init__(self):
                """建立本用例夹具的配置、响应或同步初始状态，不用于生产装配。"""
                self.future = Future(); self.cancelled = False
            def test_model(self, config):
                """提供本用例草稿连接检查的模拟能力，按测试安排返回结果或失败。"""
                self.config = config; return self.future
            def cancel(self):
                """记录取消或作废本例结果，保留迟到回传条件用于检查过滤。"""
                self.cancelled = True
        setup = Setup()
        dialog = AgentSettingsDialog(self.repo, setup=setup)
        self.addCleanup(dialog.deleteLater)
        dialog.provider.setCurrentIndex(dialog.provider.findData('local'))
        dialog.model.setText('qwen3:1.7b')
        dialog.test_model()
        self.assertEqual(setup.config.model, 'qwen3:1.7b')
        self.assertFalse(dialog.save.isEnabled())
        dialog.reject()
        self.assertTrue(setup.cancelled)
        setup.future.set_result(AgentConnectionResult('连接成功', .1))
        self.assertTrue(pump_until(lambda:dialog._job is None))
        self.assertIn('已取消', dialog.model_status.text())
        self.assertIsNone(self.repo.get_setting('companion_agent_model'))

    def test_model_test_success_and_changed_draft_invalidate_result(self):
        """验证连接成功但草稿变更后结果不应用于当前配置。"""
        from app.modules.companion.api import AgentConnectionResult
        class Setup:
            """受控草稿检查能力，以 Future 驱动完成/取消场景。"""
            def test_model(self, config):
                """提供本用例草稿连接检查的模拟能力，按测试安排返回结果或失败。"""
                self.future = Future(); return self.future
        setup = Setup()
        dialog = AgentSettingsDialog(self.repo, setup=setup)
        self.addCleanup(dialog.deleteLater)
        dialog.test_model()
        setup.future.set_result(AgentConnectionResult('连接成功', .1))
        self.assertTrue(pump_until(lambda:dialog._job is None))
        self.assertIn('连接成功', dialog.model_status.text())
        dialog.test_model()
        dialog.model.setText('different-model')
        setup.future.set_result(AgentConnectionResult('旧配置连接成功', .1))
        self.assertTrue(pump_until(lambda:dialog._job is None))
        self.assertIn('不应用', dialog.model_status.text())

    def test_keyless_search_selection_checks_draft_without_persisting(self):
        """验证免 Key 搜索草稿可检查但不自动保存。"""
        from app.modules.companion.api import AgentConnectionResult
        class Setup:
            """受控草稿检查能力，以 Future 驱动完成/取消场景。"""
            def test_search(self, config, progress):
                """提供本用例草稿连接检查的模拟能力，按测试安排返回结果或失败。"""
                assert config.search_provider == 'web'
                self.future = Future(); return self.future
        setup = Setup()
        dialog = AgentSettingsDialog(self.repo, setup=setup)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.search_provider.currentData(), 'web')
        self.assertTrue(dialog.thinking.isChecked())
        self.assertTrue(dialog.draft_config().thinking)
        dialog.thinking.setChecked(False)
        self.assertFalse(dialog.draft_config().thinking)
        self.assertIsNone(self.repo.get_setting('companion_agent_thinking'))
        self.assertTrue(dialog.search_url.isHidden())
        self.assertTrue(dialog.search_key.isHidden())
        self.assertFalse(hasattr(dialog, 'prepare_search'))
        dialog.test_search()
        setup.future.set_result(AgentConnectionResult('搜索连接成功', .1, 2))
        self.assertTrue(pump_until(lambda:dialog._job is None))
        self.assertIn('连接成功', dialog.search_status.text())
        self.assertIsNone(self.repo.get_setting('companion_agent_search_provider'))

    def agent(self):
        """创建带受控异步能力的隔离桌宠，供界面进度/结果测试。"""
        window = self.window()
        companion = window._companion
        self.addCleanup(companion.shutdown)
        agent = companion.agent
        agent.service.close()
        agent.service = ControlledService()
        self.repo.set_setting('companion_agent_enabled', '1')
        return window, agent

    def report(self):
        """构造固定只读报告，不把示例内容当成实时新闻。"""
        return AgentReport('request-one', '测试话题', '可靠摘要 ' * 200,
            (SearchSource('<img src=x>', 'https://example.org', '来源摘录'),),
            datetime.now(timezone.utc).isoformat())

    def test_hover_actions_and_right_menu_alternative(self):
        """验证悬停轮盘和右键菜单均提供搜索入口。"""
        window, agent = self.agent()
        APP.sendEvent(window._companion.view, QEvent(QEvent.Enter))
        self.assertTrue(agent.actions.isVisible())
        self.assertEqual([b.isEnabled() for b in agent.actions.buttons], [False, True, True])
        self.assertTrue(all(b.width() >= 44 for b in agent.actions.buttons))
        agent.open_search()
        self.assertTrue(agent.input.isVisible())

    def test_repeated_click_stream_and_detail(self):
        """验证重复点击入口、流式卡片和详情协作，不重建额外请求。"""
        window, agent = self.agent()
        agent.input.topic.setText('草稿话题')
        agent.search('草稿话题')
        agent.search('重复')
        self.assertEqual(agent.service.calls, 1)
        agent.service.progress(AgentProgress('request-one', 'streaming', '正在流式呈现正文'))
        APP.processEvents()
        self.assertIn('流式', agent.card.body.toPlainText())
        agent.service.future.set_result(self.report())
        self.assertTrue(pump_until(lambda:agent.report is not None))
        self.assertTrue(agent.card.detail.isEnabled())
        agent.open_detail()
        self.assertIn('<img src=x>', agent.detail.body.toPlainText())
        self.assertTrue(agent.card.body.verticalScrollBar().maximum() > 0)

    def test_cancel_discards_late_progress_and_result(self):
        """验证取消后迟到进度和报告不能重新显示。"""
        window, agent = self.agent()
        agent.search('话题')
        agent.cancel()
        self.assertTrue(agent.service.cancelled)
        agent.service.progress(AgentProgress('request-one', 'streaming', '迟到正文'))
        agent.service.future.set_result(self.report())
        self.assertTrue(pump_until(lambda:not agent._busy))
        self.assertIsNone(agent.report)
        self.assertNotIn('迟到', agent.card.body.toPlainText())

    def test_hiding_pet_keeps_input_draft_and_prevents_popup(self):
        """验证隐藏桌宠保留话题草稿且阻止迟到卡片弹出。"""
        window, agent = self.agent()
        agent.input.topic.setText('暂存话题')
        agent.search('话题')
        window._companion.hide_companion()
        self.assertFalse(agent.card.isVisible())
        agent.service.future.set_result(self.report())
        self.assertTrue(pump_until(lambda:agent.report is not None))
        self.assertFalse(agent.card.isVisible())
        self.assertEqual(agent.input.topic.text(), '暂存话题')

    def test_settings_cancel_does_not_save_key_or_enable(self):
        """验证取消智能体配置不保存密钥或启用开关。"""
        dialog = AgentSettingsDialog(self.repo)
        self.addCleanup(dialog.deleteLater)
        dialog.enabled.setChecked(True)
        dialog.api_key.setText('draft-only-key')
        dialog.reject()
        self.assertIsNone(self.repo.get_setting('companion_agent_api_key'))
        self.assertIsNone(self.repo.get_setting('companion_agent_enabled'))

    def test_orbit_keeps_pet_centre_clickable_and_search_prominent(self):
        """验证轮盘中心穿透供互动，搜索入口明显且可用。"""
        window, agent = self.agent()
        actions = agent.actions
        self.assertFalse(actions.mask().contains(QPoint(actions.width() // 2, 115)))
        self.assertTrue(all(actions.mask().contains(b.geometry().center()) for b in actions.buttons))
        self.assertGreater(actions.buttons[-1].width(), actions.buttons[0].width())
        self.assertLess(actions.buttons[1].y(), actions.buttons[0].y())
        QTest.mouseClick(actions.buttons[-1], Qt.LeftButton)
        self.assertTrue(agent.input.isVisible())

    def test_search_pose_tracks_graph_without_overriding_pet_interaction(self):
        """验证搜索姿态跟随真实图阶段但让位于桌宠明确互动。"""
        from app.modules.companion.api import CompanionEvent
        window, agent = self.agent()
        companion = window._companion
        agent.search('星星')
        self.assertEqual(companion.view._pose_motion.state, 'focused')
        self.assertEqual(agent.actions.buttons[-1].caption, '思考')
        self.assertTrue(agent._thinking.isActive())
        agent.service.progress(AgentProgress('request-one', 'reading', '核对来源'))
        APP.processEvents()
        self.assertEqual(agent.card.journey.stage, 1)
        self.assertIn('原文', companion.view._text)
        companion.handle_event(CompanionEvent('pet'))
        self.assertEqual(companion.view._pose_motion.state, 'shy')
        agent.cancel()
        self.assertIsNone(companion._agent_feedback)
        self.assertFalse(agent._thinking.isActive())
        self.assertFalse(agent.card.journey._timer.isActive())
        agent.service.future.set_result(self.report())
        self.assertTrue(pump_until(lambda:not agent._busy))
        self.assertIsNone(companion._agent_feedback)

    def test_report_feedback_expires_and_reduced_motion_stays_static(self):
        """验证报告短回应到期恢复，减弱动效保持静态。"""
        window, agent = self.agent()
        companion = window._companion
        self.repo.set_setting('reduced_motion', '1')
        companion.sync_settings()
        agent.search('星星')
        self.assertFalse(agent.card.journey._timer.isActive())
        self.assertFalse(agent.actions.buttons[-1].motion)
        agent.service.future.set_result(self.report())
        self.assertTrue(pump_until(lambda:agent.report is not None))
        self.assertEqual(companion.view._pose_motion.state, 'happy')
        self.assertFalse(agent._thinking.isActive())
        companion.set_agent_feedback('happy', '短暂回应', duration=.01)
        QTest.qWait(30)
        companion._render()
        self.assertIsNone(companion._agent_feedback)
        self.assertNotEqual(companion.view._pose_motion.state, 'happy')

    def test_stream_keeps_reader_position_and_hidden_card_stops_pulse(self):
        """验证正文更新保留用户阅读位置，卡片隐藏停止进度脉冲。"""
        window, agent = self.agent()
        card = agent.card
        card.show_progress('搜索资料')
        card.show()
        text = '\n'.join(f'第 {i} 行 · 资料内容' for i in range(100))
        card.show_partial(text)
        APP.processEvents()
        bar = card.body.verticalScrollBar()
        bar.setValue(12)
        card.show_partial(text + '\n新追加的正文')
        APP.processEvents()
        self.assertEqual(bar.value(), 12)
        self.assertTrue(card.journey._timer.isActive())
        card.hide()
        self.assertFalse(card.journey._timer.isActive())

    def test_edge_placement_follows_pet_without_covering_its_character(self):
        """验证屏幕边缘浮层仍跟随桌宠并避开角色图像。"""
        from unittest.mock import patch
        from PySide6.QtCore import QRect
        window, agent = self.agent()
        view = window._companion.view
        area = QRect(0, 0, 1280, 900)
        window.move(0, 0)
        view.move(520, 12)
        agent.card.show_report(self.report())
        with patch('app.ui.companion.agent_controller.available_screens', return_value=[area]), \
             patch('app.ui.companion.desktop.available_screens', return_value=[area]):
            agent._place(agent.card)
        origin = view.mapToGlobal(QPoint())
        pet_rect = view.image_rect().translated(origin)
        self.assertFalse(agent.card.geometry().intersects(pet_rect))
        self.assertTrue(area.contains(agent.card.geometry()))
        self.assertTrue(48 <= agent.card.tail_x <= agent.card.width() - 58)

    def test_settings_tabs_preserve_drafts_across_sections(self):
        """验证切换配置分区保留模型/搜索草稿。"""
        dialog = AgentSettingsDialog(self.repo)
        self.addCleanup(dialog.deleteLater)
        dialog.api_key.setText('draft-only-key')
        dialog.tabs.setCurrentIndex(1)
        dialog.default_topic.setText('天文学')
        dialog.tabs.setCurrentIndex(2)
        dialog.tabs.setCurrentIndex(0)
        self.assertEqual(dialog.api_key.text(), 'draft-only-key')
        self.assertEqual(dialog.default_topic.text(), '天文学')
        self.assertEqual(dialog.tabs.count(), 3)
        dialog.reject()
        self.assertIsNone(self.repo.get_setting('companion_agent_api_key'))

    def test_card_follows_parent_window_global_movement(self):
        """验证父窗口全球坐标变化时卡片跟随桌宠。"""
        window, agent = self.agent()
        window.move(0, 0)
        window._companion.view.move(220, 500)
        agent.card.show_report(self.report())
        agent.card.show()
        APP.processEvents()
        agent._place(agent.card)
        before = agent.card.pos()
        window.move(window.pos() + QPoint(60, 0))
        APP.processEvents()
        self.assertEqual(agent.card.x() - before.x(), 60)
        self.assertEqual(agent.card.y(), before.y())

    def test_section_navigation_uses_one_palette_with_dark_platform_background(self):
        """验证深色原生平台下分区导航/内容使用同一配色，避免黑底泄漏。"""
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QTabBar, QFrame, QWidget
        previous = APP.palette()
        dark = QPalette(previous)
        dark.setColor(QPalette.Window, QColor('#2c2c2c'))
        dark.setColor(QPalette.Button, QColor('#2c2c2c'))
        APP.setPalette(dark)
        self.addCleanup(APP.setPalette, previous)
        dialog = AgentSettingsDialog(self.repo)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.assertIsNone(dialog.findChild(QTabBar))
        self.assertEqual(dialog.tabs.frameShape(), QFrame.NoFrame)
        backgrounds = []
        for index in range(3):
            QTest.mouseClick(dialog.nav_buttons[index], Qt.LeftButton)
            APP.processEvents()
            c = dialog.section_palette
            backgrounds.append(c.bg)
            self.assertEqual(dialog.tabs.currentIndex(), index)
            self.assertEqual([b.isChecked() for b in dialog.nav_buttons], [i == index for i in range(len(dialog.nav_buttons))])
            self.assertEqual(dialog.palette().color(QPalette.Window), QColor(c.bg))
            navigation = dialog.findChild(QWidget, 'agentSectionNavigation')
            sample = navigation.grab().toImage().pixelColor(navigation.width() - 4, 4)
            self.assertEqual(sample, QColor(c.bg))
        self.assertEqual(len(set(backgrounds)), 3)

    def test_open_layout_reflows_without_losing_configuration_fields(self):
        """验证设置开放布局宽窄重排不丢字段草稿。"""
        dialog = AgentSettingsDialog(self.repo)
        self.addCleanup(dialog.deleteLater)
        dialog.api_key.setText('draft-only-key')
        dialog.show()
        for width in (820, 560, 820):
            dialog.resize(width, 640)
            APP.processEvents()
            for index in range(3):
                dialog.tabs.setCurrentIndex(index)
                APP.processEvents()
                self.assertEqual(dialog.tabs.currentWidget().horizontalScrollBar().maximum(), 0)
            self.assertEqual(dialog._wide, width >= 700)
        self.assertEqual(dialog.api_key.text(), 'draft-only-key')


if __name__ == '__main__':
    import unittest
    unittest.main()
