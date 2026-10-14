"""Real-time companion decisions, without Qt widgets or wall-clock waits."""
import random
import unittest


class RuntimeTests(unittest.TestCase):
    """桌宠纯姿态状态机的回归用例，使用隔离对象与受控输入验证实际行为。"""
    def setUp(self):
        """准备本组回归需要的隔离对象和初始状态，不使用用户真实数据。"""
        from app.companion.runtime import Runtime
        self.now = 0.0
        self.runtime = Runtime(clock=lambda: self.now, rng=random.Random(7))
        self.runtime.set_visible(True)

    def event(self, kind, identity='', **payload):
        """构造带稳定 ID、应用日或状态的测试事件，用于去重及排期验证。"""
        from app.companion.models import CompanionEvent
        return self.runtime.react(CompanionEvent(kind, payload, identity))

    def test_reaction_restores_current_base_and_expires_bubble(self):
        """验证临时反应到期恢复当前基础姿态并结束气泡。"""
        self.runtime.update_activity('2026-10-09', 0, True)
        self.event('pet')
        self.assertEqual(self.runtime.sample().state, 'shy')
        self.now = 5.1
        self.assertFalse(self.runtime.sample().bubble)
        self.now = 6.1
        self.assertEqual(self.runtime.sample().state, 'focused')

    def test_duplicate_event_and_priority(self):
        """验证事件去重和高低优先级反应规则。"""
        self.assertTrue(self.event('record', 'r1'))
        self.assertFalse(self.event('record', 'r1'))
        self.assertFalse(self.event('finished', 'r2'))
        self.assertEqual(self.runtime.sample().state, 'proud')
        self.assertTrue(self.event('pet'))
        self.assertEqual(self.runtime.sample().state, 'shy')

    def test_snapshot_baselines_rollover_and_counter_drop(self):
        """验证活动快照基线正确处理日切和计数回退。"""
        self.runtime.set_frequency('off')
        self.runtime.update_activity('2026-10-09', 2000, False)
        self.assertEqual(self.runtime.sample().state, 'idle')
        self.runtime.update_activity('2026-10-09', 2001, False)
        self.assertEqual(self.runtime.sample().state, 'focused')
        self.now = 4
        self.runtime.update_activity('2026-10-10', 50, False)
        self.assertEqual(self.runtime.sample().state, 'idle')
        self.runtime.update_activity('2026-10-10', 10, False)
        self.assertEqual(self.runtime.sample().state, 'idle')
        self.now = 305
        self.assertEqual(self.runtime.sample().state, 'sleepy')

    def test_practice_and_hidden_do_not_accumulate_random_memes(self):
        """验证练习/隐藏不积累自动表情，恢复后不集中补发。"""
        self.runtime.update_activity('day', 0, True)
        self.now = 10000
        self.assertEqual(self.runtime.sample().state, 'focused')
        self.runtime.set_visible(False)
        self.assertFalse(self.event('level', 'l1'))
        self.runtime.set_visible(True)
        self.runtime.update_activity('day', 0, False)
        self.assertFalse(self.runtime.sample().bubble)
        self.now += 500
        self.assertEqual(self.runtime.sample().kind, 'meme')

    def test_frequency_is_bounded_and_paused(self):
        """验证主动互动排期有界且暂停时不执行。"""
        self.runtime.set_frequency('quiet')
        self.assertGreaterEqual(self.runtime.next_random, 480)
        self.assertLessEqual(self.runtime.next_random, 720)
        self.runtime.set_frequency('off')
        self.now = 2000
        self.assertNotEqual(self.runtime.sample().kind, 'meme')

    def test_practice_interrupts_automatic_reactions_but_allows_click(self):
        """验证练习中中断自动反馈，但保留明确点击互动。"""
        self.event('meme')
        self.assertTrue(self.runtime.sample().bubble)
        self.runtime.update_activity('day', 0, True)
        self.assertEqual(self.runtime.sample().state, 'focused')
        self.assertFalse(self.runtime.sample().bubble)
        self.assertFalse(self.event('achievement', 'during-practice'))
        self.assertTrue(self.event('pet'))
        self.assertEqual(self.runtime.sample().state, 'shy')
        self.runtime.update_activity('day', 0, False)
        self.now = 7
        self.assertFalse(self.event('achievement', 'during-practice'))

    def test_custom_meme_duration_expires_from_original_start(self):
        """验证自定义表情期限从原开始时间计算，不因刷新无限延长。"""
        self.event('meme')
        self.runtime.set_reaction_duration(30)
        self.now = 29
        self.assertEqual(self.runtime.sample().kind, 'meme')
        self.assertFalse(self.runtime.sample().bubble)
        self.now = 31
        self.assertNotEqual(self.runtime.sample().kind, 'meme')


if __name__ == '__main__':
    unittest.main()
