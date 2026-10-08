"""英语训练编排；UI 只调用此服务，不读写 SQLite。"""
from .catalog import VocabularyCatalog
from .session import SpellingSession
from .ai import validate_sentences
from ..core.challenge import compare
from ..services.exp_service import level_and_progress
from ..services.ai_access import AITestSession
import uuid
import sqlite3


class EnglishSaveError(RuntimeError):
    """可重试的学习记录保存失败，不向页面泄漏 SQL 细节。"""


class EnglishService:
    def __init__(self, repo, catalog=None, *, test_session=None):
        self.repo = repo
        self.storage = repo.english
        self.catalog = catalog or VocabularyCatalog()
        self.session = None
        self.deck = 'cet4'
        self.test_session = test_session or AITestSession()

    def start(self, deck, count=20, review=False):
        keys = self.storage.review_keys(deck) if review else None
        words = self.catalog.sample(deck, count, keys)
        if not words:
            raise ValueError('这套词库还没有待复习词；先开始一轮拼写吧。')
        self.deck = deck
        self.session = SpellingSession(words)
        return self.session

    def submit(self, answer):
        if self.session is None:
            return {'accepted': False}
        result = self.session.prepare(answer)
        if result.get('accepted'):
            self._save_attempt(dict(result, deck=self.deck))
            self.session.confirm(result)
        return result

    def hint(self):
        return self.session.hint() if self.session else ''

    def reveal(self):
        if self.session is None or self.session.finished:
            return ''
        result = self.session.prepare_reveal()
        if result.get('accepted'):
            self._save_attempt(dict(result, deck=self.deck))
            self.session.confirm(result)
        return self.session.current.word

    def _save_attempt(self, event):
        try:
            return self.storage.record_attempt(event)
        except sqlite3.Error as error:
            raise EnglishSaveError('本次成绩未保存，输入已保留，请重试。') from error

    def advance(self):
        return self.session.advance() if self.session else False

    def summary(self, deck):
        return self.storage.summary(deck)

    def ai_access(self, ai_service, balance):
        if ai_service is None or not ai_service.enabled():
            return False, 'AI 未启用，打开 AI 配置即可连接你的模型。'
        level, _, _ = level_and_progress(self.repo.get_exp(), balance)
        return self.test_session.access(level, self.repo.count_ai_passes(), balance.get('ai', {}).get('unlock_level', 45))

    def save_generated(self, deck, topic, words, sentences, balance, *, test_mode=False):
        valid = validate_sentences(sentences, words)
        known = {w.key for w in self.catalog.load(deck)}
        if any(w.casefold() not in known for w in words):
            raise ValueError('目标词不属于当前词库，请重新选词。')
        level, _, _ = level_and_progress(self.repo.get_exp(), balance)
        spend_pass = level < balance.get('ai', {}).get('unlock_level', 45) and not test_mode
        return self.storage.save_sentences(deck, topic[:80], words, valid, spend_pass=spend_pass)

    def sentence_history(self, deck):
        return self.storage.sentence_history(deck)

    def record_sentence(self, deck, reference, answer, elapsed, event_id=None):
        correct_chars, errors = compare(answer, reference)
        accuracy = correct_chars / max(len(reference), len(answer), 1)
        event = dict(id=event_id or uuid.uuid4().hex, deck=deck, word='', mode='sentence',
                     correct=not errors, assisted=False, elapsed=elapsed, accuracy=accuracy)
        saved = self._save_attempt(event)
        return dict(accuracy=accuracy, saved=saved, elapsed=elapsed)
