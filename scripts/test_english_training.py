"""英语领域回归；真实词库与隔离 SQLite，不联网。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class VocabularyTests(unittest.TestCase):
    def test_imported_counts_and_cet6_contains_cet4(self):
        from app.english.catalog import VocabularyCatalog
        catalog = VocabularyCatalog()
        books = {key: catalog.load(key) for key in ('cet4', 'cet6', 'kaoyan')}
        self.assertEqual({k: len(v) for k, v in books.items()},
                         {'cet4': 3846, 'cet6': 5802, 'kaoyan': 4801})
        self.assertLessEqual({w.word.casefold() for w in books['cet4']},
                             {w.word.casefold() for w in books['cet6']})
        for words in books.values():
            self.assertEqual(len(words), len({w.word.casefold() for w in words}))
            self.assertTrue(all(w.meaning.strip() for w in words))
        manifest = json.loads((ROOT / 'config/vocabulary/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['revision'], 'bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b')
        self.assertIn('Copyright (c) 2025 Linwei',
                      (ROOT / 'config/vocabulary/LICENSE-ECDICT.txt').read_text(encoding='utf-8'))

    def test_catalog_missing_phonetic_and_unknown_deck(self):
        from app.english.catalog import VocabularyCatalog
        catalog = VocabularyCatalog()
        self.assertTrue(any(not w.phonetic for w in catalog.load('cet4')))
        with self.assertRaises(ValueError):
            catalog.load('../other')
        selected = catalog.sample('cet4', 20)
        self.assertEqual(len(selected), 20)
        self.assertEqual(len(set(w.word.casefold() for w in selected)), 20)
        self.assertIs(catalog.load('cet4'), catalog.load('cet4'))


class SpellingTests(unittest.TestCase):
    def test_spelling_normalization_and_single_submission(self):
        from app.english.catalog import Word
        from app.english.session import SpellingSession
        session = SpellingSession([Word('Apple', '苹果'), Word('mother-in-law', '岳母')])
        result = session.submit(' APPLE ')
        self.assertTrue(result['correct'])
        self.assertTrue(result['independent'])
        self.assertFalse(session.submit('wrong')['accepted'])
        self.assertTrue(session.advance())
        self.assertFalse(session.submit('motherinlaw')['correct'])
        self.assertFalse(session.advance())
        self.assertTrue(session.finished)

    def test_hint_and_reveal_are_assisted(self):
        from app.english.catalog import Word
        from app.english.session import SpellingSession
        session = SpellingSession([Word('apple', '苹果'), Word('pear', '梨')])
        self.assertEqual(session.hint(), 'a')
        result = session.submit('apple')
        self.assertTrue(result['correct'])
        self.assertFalse(result['independent'])
        session.advance()
        self.assertEqual(session.reveal(), 'pear')
        self.assertTrue(session.result['assisted'])
        self.assertFalse(session.result['independent'])

    def test_empty_answer_does_not_finish_question(self):
        from app.english.catalog import Word
        from app.english.session import SpellingSession
        session = SpellingSession([Word('apple', '苹果')])
        self.assertFalse(session.submit('  ')['accepted'])
        self.assertFalse(session.finished)
        self.assertTrue(session.submit('apple')['correct'])


class EnglishStorageTests(unittest.TestCase):
    def test_failed_reveal_keeps_question_unconfirmed(self):
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        from app.english.service import EnglishService
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        init_schema(conn)
        service = EnglishService(Repository(conn))
        service.start('cet4', 1)
        conn.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON english_attempts BEGIN SELECT RAISE(FAIL, 'test write error'); END;")
        conn.commit()
        with self.assertRaises(Exception):
            service.reveal()
        self.assertIsNone(service.session.result)
        self.assertFalse(service.session.results)

    def test_failed_spelling_and_reveal_remain_retryable(self):
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        from app.english.service import EnglishService
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        init_schema(conn)
        repo = Repository(conn)
        service = EnglishService(repo)
        service.start('cet4', 2)
        word = service.session.current.word
        conn.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON english_attempts BEGIN SELECT RAISE(FAIL, 'test write error'); END;")
        conn.commit()
        try:
            service.submit(word)
        except Exception:
            pass
        self.assertIsNone(service.session.result, '存储失败不能锁定题目')
        self.assertFalse(service.session.results)
        conn.execute('DROP TRIGGER fail_attempt')
        conn.commit()
        self.assertTrue(service.submit(word)['accepted'])
        self.assertEqual(repo.english.summary('cet4')['attempts'], 1)
        service.advance()
        conn.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON english_attempts BEGIN SELECT RAISE(FAIL, 'test write error'); END;")
        conn.commit()
        try:
            service.reveal()
        except Exception:
            pass
        self.assertIsNone(service.session.result, '显示答案也必须先成功保存')
        self.assertEqual(len(service.session.results), 1)
        conn.execute('DROP TRIGGER fail_attempt')
        conn.commit()
        self.assertTrue(service.reveal())
        self.assertTrue(service.session.result['assisted'])
        self.assertEqual(repo.english.summary('cet4')['attempts'], 2)

    def test_capitalized_word_uses_stable_review_key(self):
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        from app.english.service import EnglishService
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        init_schema(conn)
        service = EnglishService(Repository(conn))
        word = next(w for w in service.catalog.load('cet4') if w.word != w.key)
        service.storage.record_attempt(dict(id='capital', deck='cet4', word=word.word,
            mode='spelling', correct=False, assisted=False, elapsed=1))
        self.assertEqual(service.storage.review_keys('cet4'), {word.key})
        self.assertEqual(service.start('cet4', 1, review=True).current.key, word.key)

    def test_review_and_progress_survive_reopen(self):
        from app.storage.db import init_schema
        from app.english.repository import EnglishRepository
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            init_schema(conn)
            repo = EnglishRepository(conn)
            event = dict(id='one', deck='cet4', word='apple', mode='spelling',
                         correct=False, assisted=False, elapsed=1.2)
            self.assertTrue(repo.record_attempt(event))
            self.assertFalse(repo.record_attempt(event))
            self.assertEqual(repo.review_keys('cet4'), {'apple'})
            self.assertFalse(repo.review_keys('cet6'))
            conn.close()
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            try:
                init_schema(conn)
                repo = EnglishRepository(conn)
                self.assertEqual(repo.summary('cet4')['attempts'], 1)
                repo.record_attempt(dict(event, id='two', correct=True))
                self.assertFalse(repo.review_keys('cet4'))
                self.assertEqual(repo.summary('cet4')['independent_correct'], 1)
                self.assertAlmostEqual(repo.summary('cet4')['accuracy'], .5)
            finally:
                conn.close()

    def test_old_database_and_backup_include_english(self):
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        from app.services.export_service import export_all
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        init_schema(conn)
        repo = Repository(conn)
        repo.set_setting('nickname', '原数据')
        init_schema(conn)
        self.assertEqual(repo.get_setting('nickname'), '原数据')
        repo.english.record_attempt(dict(id='backup', deck='cet4', word='apple',
                                        mode='spelling', correct=True, assisted=False, elapsed=2))
        with tempfile.TemporaryDirectory() as folder:
            backup = Path(export_all(repo, folder))
            data = json.loads((backup / 'data.json').read_text(encoding='utf-8'))
            self.assertEqual(len(data['english']['attempts']), 1)
            self.assertEqual(data['english']['attempts'][0]['word'], 'apple')
            self.assertNotIn('answer', data['english']['attempts'][0])


class EnglishAITests(unittest.TestCase):
    def test_sentence_json_and_keyword_validation(self):
        from app.english.ai import EnglishAI
        from app.services.ai_service import AIService
        api = AIService(config=dict(backend='openai', base_url='', api_key='', model='test'))
        generator = EnglishAI(api)
        valid = [{'text': 'The apple and pear are beside an orange.', 'translation': '苹果和梨在橙子旁边。'}]
        with patch.object(AIService, '_chat', return_value='```json\n' + json.dumps(valid) + '\n```'):
            ok, result = generator.generate(['apple', 'pear', 'orange'], '校园')
        self.assertTrue(ok)
        self.assertEqual(result, valid)
        with patch.object(AIService, '_chat', return_value=json.dumps(valid)):
            ok, error = generator.generate(['art'], '')
        self.assertFalse(ok, '词 art 不能被 orange 或 party 的片段冒充')
        self.assertIn('art', error)
        with patch.object(AIService, '_chat', side_effect=TimeoutError()):
            self.assertFalse(generator.generate(['apple'], '')[0])

    def test_ai_failure_does_not_spend_pass(self):
        from app.english.service import EnglishService
        from app.storage.db import init_schema
        from app.storage.repository import Repository
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        self.addCleanup(conn.close)
        init_schema(conn)
        repo = Repository(conn)
        repo.add_reward('ai_pass', 2, 'test')
        service = EnglishService(repo)
        balance = json.loads((ROOT / 'config/balance.json').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):
            service.save_generated('cet4', '', ['government'], [{'text': 'Invalid.', 'translation': '无效'}], balance)
        self.assertEqual(repo.count_ai_passes(), 2)
        valid = [{'text': 'The government supports a local school.', 'translation': '政府支持当地学校。'}]
        service.save_generated('cet4', '校园', ['government'], valid, balance)
        self.assertEqual(repo.count_ai_passes(), 1)
        self.assertEqual(len(repo.english.sentence_history('cet4')), 1)
        conn.execute("CREATE TRIGGER reject_sentence BEFORE INSERT ON english_sentences "
                     "BEGIN SELECT RAISE(FAIL, 'test write failure'); END;")
        conn.commit()
        with self.assertRaises(sqlite3.Error):
            service.save_generated('cet4', '校园', ['government'], valid, balance)
        self.assertEqual(repo.count_ai_passes(), 1, '保存失败应回滚扣券')


if __name__ == '__main__':
    unittest.main()
