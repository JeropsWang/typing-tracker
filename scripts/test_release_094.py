"""0.9.4: word alignment, fixed-time mashing and short AI nonsense."""
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class SentenceAccuracyTests(unittest.TestCase):
    def setUp(self):
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        from app.english.service import EnglishService
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        init_schema(self.conn)
        self.service = EnglishService(Repository(self.conn))

    def test_spacing_case_and_punctuation_do_not_misalign_words(self):
        result = self.service.record_sentence('cet4', 'The apple, is red.', 'the  apple is\nred', 3)
        self.assertEqual(result['accuracy'], 1)

    def test_one_missing_word_does_not_mark_following_words_wrong(self):
        result = self.service.record_sentence('cet4', 'The apple is very red.', 'The apple is red.', 3)
        self.assertAlmostEqual(result['accuracy'], .8)

    def test_wrong_and_extra_words_are_penalized(self):
        for reference, answer, expected in [('The apple is red.', 'The pear is red.', .75),
                                            ('The apple is red.', 'The apple is red red.', .8),
                                            ('The apple is red.', '!!!', 0),
                                            ("I can't re-enter.", 'I can’t re-enter!', 1)]:
            with self.subTest(answer=answer):
                self.assertAlmostEqual(self.service.record_sentence('cet4', reference, answer, 3)['accuracy'], expected)


class KeyboardSessionTests(unittest.TestCase):
    def test_deadline_counts_tw_and_rejects_late_input(self):
        from app.core.keyboard_warrior import KeyboardSession
        now = [100.0]
        session = KeyboardSession(clock=lambda: now[0])
        session.add_text('中ab ')
        now[0] = 114.99
        session.add_text('!')
        now[0] = 115.0
        session.add_text('late')
        result = session.result()
        self.assertEqual(result['tw'], 6)
        self.assertEqual(result['speed'], 24)
        self.assertEqual(result['elapsed_seconds'], 15)

    def test_cannot_settle_before_deadline(self):
        from app.core.keyboard_warrior import KeyboardSession
        session = KeyboardSession(clock=lambda: 1)
        with self.assertRaises(ValueError):
            session.result()

    def test_leaderboard_is_persistent_and_duplicate_finish_is_idempotent(self):
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        from app.services.keyboard_warrior_service import KeyboardWarriorService
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        init_schema(conn)
        service = KeyboardWarriorService(Repository(conn))
        now = [0.0]
        from app.core.keyboard_warrior import KeyboardSession
        session = KeyboardSession(clock=lambda: now[0])
        session.add_text('abc')
        now[0] = 15
        service.record(session)
        service.record(session)
        rows = KeyboardWarriorService(Repository(conn)).leaderboard()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['speed'], 12)


class ChaosTests(unittest.TestCase):
    def test_ai_output_is_hard_limited_to_sixty_characters(self):
        from app.services.ai_service import AIService
        ai = AIService(config={'backend': 'openai'})
        with patch.object(ai, '_chat', return_value='云朵\n' * 50):
            ok, text = ai.generate_chaos('月亮')
        self.assertTrue(ok)
        self.assertEqual(len(text), 60)
        self.assertNotIn('\n', text)

    def test_failure_and_disabled_ai_remain_errors(self):
        from app.services.ai_service import AIService
        self.assertFalse(AIService(config={'backend': 'off'}).generate_chaos('')[0])
        ai = AIService(config={'backend': 'openai'})
        with patch.object(ai, '_chat', side_effect=TimeoutError()):
            self.assertFalse(ai.generate_chaos('')[0])


if __name__ == '__main__':
    unittest.main()
