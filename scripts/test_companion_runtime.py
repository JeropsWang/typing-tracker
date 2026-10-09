"""Real-time companion decisions, without Qt widgets or wall-clock waits."""
import random
import unittest


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        from app.companion.runtime import Runtime
        self.now = 0.0
        self.runtime = Runtime(clock=lambda: self.now, rng=random.Random(7))
        self.runtime.set_visible(True)

    def event(self, kind, identity='', **payload):
        from app.companion.models import CompanionEvent
        return self.runtime.react(CompanionEvent(kind, payload, identity))

    def test_reaction_restores_current_base_and_expires_bubble(self):
        self.runtime.update_activity('2026-10-09', 0, True)
        self.event('pet')
        self.assertEqual(self.runtime.sample().state, 'shy')
        self.now = 5.1
        self.assertFalse(self.runtime.sample().bubble)
        self.now = 6.1
        self.assertEqual(self.runtime.sample().state, 'focused')

    def test_duplicate_event_and_priority(self):
        self.assertTrue(self.event('record', 'r1'))
        self.assertFalse(self.event('record', 'r1'))
        self.assertFalse(self.event('finished', 'r2'))
        self.assertEqual(self.runtime.sample().state, 'proud')
        self.assertTrue(self.event('pet'))
        self.assertEqual(self.runtime.sample().state, 'shy')

    def test_snapshot_baselines_rollover_and_counter_drop(self):
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
        self.runtime.set_frequency('quiet')
        self.assertGreaterEqual(self.runtime.next_random, 480)
        self.assertLessEqual(self.runtime.next_random, 720)
        self.runtime.set_frequency('off')
        self.now = 2000
        self.assertNotEqual(self.runtime.sample().kind, 'meme')

    def test_practice_interrupts_automatic_reactions_but_allows_click(self):
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
        self.event('meme')
        self.runtime.set_reaction_duration(30)
        self.now = 29
        self.assertEqual(self.runtime.sample().kind, 'meme')
        self.assertFalse(self.runtime.sample().bubble)
        self.now = 31
        self.assertNotEqual(self.runtime.sample().kind, 'meme')


if __name__ == '__main__':
    unittest.main()
