"""Correction, scheduling and migrations on isolated data; never uses AI/network."""
from datetime import datetime, timedelta, date
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.modules.english.api import SpellingSession, Word, next_schedule, sentence_alignment, sentence_accuracy
from app.modules.english.service import EnglishService
from app.storage.db import init_schema, connect_db
from app.storage.session import DataSession


class LearningSessionTests(unittest.TestCase):
    def test_correction_is_unscored_retest_is_bounded_and_independent(self):
        session = SpellingSession([Word('apple', '苹果'), Word('pear', '梨')], learning=True)
        first = session.submit('aple')
        self.assertTrue(session.correcting)
        with self.assertRaises(ValueError):
            session.advance()
        self.assertFalse(session.correct('aple'))
        self.assertTrue(session.correct('APPLE'))
        self.assertEqual(len(session.results), 1)
        session.advance()
        session.submit('pear')
        session.advance()
        self.assertEqual(session.phase, 'retest')
        self.assertEqual(session.current.key, 'apple')
        retest = session.submit('wrong-again')
        self.assertNotEqual(first['id'], retest['id'])
        session.correct(skip=True)
        self.assertFalse(session.advance())
        view = session.view()
        self.assertEqual((view.first_correct, view.first_total, view.retest_total), (1, 2, 1))
        self.assertEqual((view.corrected, view.correction_skipped), (1, 1))

    def test_assisted_success_retests_without_hint_and_pending_result_is_stable(self):
        session = SpellingSession([Word('apple', '苹果')], learning=True)
        session.hint()
        pending = session.prepare('apple')
        self.assertEqual(session.prepare_reveal(), pending)
        self.assertEqual(session.prepare('wrong'), pending)
        session.confirm(pending)
        session.correct(skip=True)
        session.advance()
        result = session.submit('apple')
        self.assertTrue(result['independent'])
        self.assertTrue(result['retest'])
        self.assertFalse(session.advance())
        self.assertEqual(session.view().first_correct, 0)
        self.assertEqual(session.view().retest_correct, 1)

    def test_alignment_error_count_equals_existing_score(self):
        for answer, expected in [('We go to home.', 'We go home.'), ('We home.', 'We go home.'),
                                 ('we goes home', 'We go home'), ('', 'One'), ('Extra', ''),
                                 ("IT’S mother-in-law", "it's Mother-in-law")]:
            tokens = sentence_alignment(answer, expected)
            score = sentence_accuracy(answer, expected)
            self.assertEqual(sum(t['kind'] != 'equal' for t in tokens), score['errors'])
        self.assertIn('missing', [t['kind'] for t in sentence_alignment('we home', 'we go home')])
        self.assertIn('extra', [t['kind'] for t in sentence_alignment('we go to home', 'we go home')])


class ReviewRuleTests(unittest.TestCase):
    def test_intervals_overdue_same_day_and_final_cap(self):
        day = '2026-10-13'
        state = next_schedule(None, day=day, independent=True)
        self.assertEqual((state['stage'], state['due_day']), (1, '2026-10-14'))
        for interval in (3, 7, 14, 30, 30):
            day = (date.fromisoformat(state['due_day']) + timedelta(days=2)).isoformat()
            state = next_schedule(state, day=day, independent=True, due_review=True)
            self.assertEqual((date.fromisoformat(state['due_day']) - date.fromisoformat(day)).days, interval)
            self.assertEqual(next_schedule(state, day=day, independent=True, due_review=True), state)
        self.assertEqual(state['stage'], 5)
        failed = next_schedule(state, day=day, independent=False)
        self.assertEqual((failed['stage'], failed['due_day']), (0, day))
        corrected = next_schedule(failed, day=day, independent=True, retest=True)
        self.assertEqual((corrected['stage'], corrected['due_day']), (1, (date.fromisoformat(day)+timedelta(days=1)).isoformat()))

    def test_extra_practice_keeps_future_schedule(self):
        state = dict(stage=4, due_day='2026-11-01', last_success_day='2026-10-01')
        self.assertEqual(next_schedule(state, day='2026-10-13', independent=True), state)


class ReviewStorageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        init_schema(self.conn)
        self.repo = DataSession(self.conn)
        self.addCleanup(self.conn.close)

    def event(self, operation='one', **kwargs):
        return dict(dict(id=operation, deck='cet4', word='apple', mode='spelling', correct=True,
                         assisted=False, elapsed=1, app_day='2026-10-13'), **kwargs)

    def test_attempt_and_schedule_rollback_dedup_and_due_order(self):
        self.conn.execute("CREATE TRIGGER reject_review BEFORE INSERT ON english_review_schedule BEGIN SELECT RAISE(FAIL,'test'); END;")
        self.conn.commit()
        with self.assertRaises(sqlite3.Error):
            self.repo.english.record_attempt(self.event())
        self.assertEqual(self.repo.english.summary('cet4')['attempts'], 0)
        self.conn.execute('DROP TRIGGER reject_review')
        self.conn.commit()
        self.assertTrue(self.repo.english.record_attempt(self.event()))
        self.assertFalse(self.repo.english.record_attempt(self.event()))
        self.repo.english.record_attempt(self.event('two', word='pear', correct=False))
        self.assertEqual(self.repo.english.review_plan('cet4', '2026-10-13')['due_words'], ['pear'])
        self.assertEqual(self.repo.english.review_plan('cet4', '2026-10-14')['due_words'], ['pear','apple'])

    def test_service_uses_injected_clock_and_custom_day_cut(self):
        class Clock:
            def now(self): return datetime(2026,10,14,3,59)
        self.repo.set_setting('day_start_hour', '4')
        service = EnglishService(self.repo, clock=Clock())
        service.start('cet4', 1)
        word = service.session.current.word
        service.submit(word)
        row = self.conn.execute('SELECT * FROM english_review_schedule').fetchone()
        self.assertEqual(row['last_success_day'], '2026-10-13')
        self.assertEqual(row['due_day'], '2026-10-14')
        self.repo.set_setting('day_start_hour', '0')
        self.assertEqual(service.application_day(), '2026-10-14')


class ReviewMigrationTests(unittest.TestCase):
    def test_v1_backed_up_preserves_history_and_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            conn = connect_db(Path(directory)/'app.db')
            try:
                init_schema(conn)
                repo = DataSession(conn)
                repo.english.record_attempt(dict(id='old', deck='cet4', word='apple', mode='spelling',
                    correct=False, assisted=False, elapsed=1))
                conn.execute('DROP TABLE english_review_schedule')
                conn.execute('PRAGMA user_version=1')
                conn.commit()
                from app.modules.english.repository import migrate_review_schema
                def failed(conn, day):
                    migrate_review_schema(conn, day)
                    raise RuntimeError('migration failure')
                with patch('app.modules.english.repository.migrate_review_schema', side_effect=failed):
                    with self.assertRaises(RuntimeError):
                        init_schema(conn)
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 1)
                self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='english_review_schedule'").fetchone())
                init_schema(conn)
                self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], 2)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM english_attempts').fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT stage FROM english_review_schedule').fetchone()[0], 0)
                backups = list((Path(directory)/'migration-backups').glob('*.db'))
                self.assertEqual(len(backups), 2)
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main()
