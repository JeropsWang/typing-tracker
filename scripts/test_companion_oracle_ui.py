"""占卜轮盘与Qt异步回传回归；使用隔离窗口和受控Future，不调用真实模型。"""
from concurrent.futures import Future
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_ui_workflow import UIFixture, APP, pump_until
from app.modules.companion.api import OracleResult


class OracleUITests(UIFixture):
    """检查占卜入口、百分数与失效回传，不读取真实用户数据。"""
    def oracle(self):
        """创建正式桌宠控制器，只替换外部网络边界。"""
        self.repo.set_setting('companion_agent_enabled', '1')
        window = self.window()
        window.show()
        self.addCleanup(window._companion.shutdown)
        agent = window._companion.agent
        class Service:
            """受控模型Future，保留真实Qt控制器的状态变化。"""
            def judge(self, config, question, progress):
                """捕获主动问题并返回未完成任务。"""
                self.question = question
                self.future = Future()
                return 'oracle-test', self.future
            def cancel(self, request_id=None):
                """记录所有者取消，未来仍可返回迟到结果。"""
                self.cancelled = request_id
        service = Service()
        agent.oracle.service = service
        return window, agent, service

    def test_entry_and_validated_result_are_visible_without_explanation(self):
        """轮盘可打开50字输入，最终卡片只显示问题、判断和准确的三项占比。"""
        window, agent, service = self.oracle()
        self.assertTrue(agent.actions.buttons[0].isEnabled())
        QTest.mouseClick(agent.actions.buttons[0], Qt.LeftButton)
        self.assertTrue(agent.oracle.input.isVisible())
        self.assertEqual(agent.oracle.input.topic.maxLength(), 50)
        agent.oracle.submit('会顺利吗')
        self.assertFalse(agent.can_show_news())
        service.future.set_result(OracleResult('oracle-test', '会顺利吗', 80, 10, 10))
        self.assertTrue(pump_until(lambda: not agent.oracle.busy))
        self.assertEqual(agent.oracle.card.result.yes, 80)
        self.assertIn('80%', agent.oracle.card.percentages.text())
        self.assertIsNone(agent.report)

    def test_cancelled_result_does_not_reopen_card_or_replace_state(self):
        """取消后迟到成功不得成为可见结果；退出也要清理占卜浮层。"""
        window, agent, service = self.oracle()
        agent.oracle.submit('问题')
        agent.oracle.cancel()
        self.assertEqual(service.cancelled, 'oracle-test')
        service.future.set_result(OracleResult('oracle-test', '问题', 80, 10, 10))
        APP.processEvents()
        self.assertIsNone(agent.oracle.card.result)
        agent.shutdown()
        self.assertFalse(agent.oracle.card.isVisible())

    def test_escape_inflight_card_stays_hidden_after_result(self):
        """Escape 收起后迟到结果不得重新打开卡片。"""
        window, agent, service = self.oracle()
        agent.oracle.submit('问题')
        QTest.keyClick(agent.oracle.card, Qt.Key_Escape)
        self.assertFalse(agent.oracle.card.isVisible())
        service.future.set_result(OracleResult('oracle-test', '问题', 80, 10, 10))
        self.assertTrue(pump_until(lambda: not agent.oracle.busy))
        self.assertFalse(agent.oracle.card.isVisible())

    def test_dismissed_inflight_card_stays_hidden_after_result(self):
        """用户主动收起在途卡片后，结果仍留内存，但完成不能再次打扰用户。"""
        window, agent, service = self.oracle()
        agent.oracle.submit('问题')
        QTest.mouseClick(agent.oracle.card.close_button, Qt.LeftButton)
        self.assertFalse(agent.oracle.card.isVisible())
        service.future.set_result(OracleResult('oracle-test', '问题', 80, 10, 10))
        self.assertTrue(pump_until(lambda: not agent.oracle.busy))
        self.assertIsNotNone(agent.oracle.card.result)
        self.assertFalse(agent.oracle.card.isVisible())


if __name__ == '__main__':
    import unittest
    unittest.main()
