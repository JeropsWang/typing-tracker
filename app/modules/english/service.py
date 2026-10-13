"""英语训练编排；UI 只调用此服务，不读写 SQLite。"""
from .catalog import VocabularyCatalog
from .session import SpellingSession
from .ai import validate_sentences
from .scoring import sentence_accuracy
from ..tracking.api import AppCalendar, SystemClock
from ..growth.api import level_and_progress
from ..growth.api import AITestSession
import uuid
import sqlite3
from ...storage.unit_of_work import transactional


class EnglishSaveError(RuntimeError):
    """可重试的学习记录保存失败，不向页面泄漏 SQL 细节。"""


class EnglishService:
    def __init__(self, repo, catalog=None, *, test_session=None, clock=None):
        self.repo = repo
        self.storage = repo.english
        self.catalog = catalog or VocabularyCatalog()
        self.session = None
        self.deck = 'cet4'
        self.test_session = test_session or AITestSession()
        self.clock = clock or SystemClock()

    def application_day(self):
        hour = int(self.repo.get_setting('day_start_hour', '4'))
        return AppCalendar(hour).day(self.clock.now())

    def review_plan(self, deck):
        return self.storage.review_plan(deck, self.application_day())

    def start(self, deck, count=20, review=False, *, due=False):
        keys = self.storage.review_keys(deck) if review else None
        if due:
            plan = self.review_plan(deck)
            keys = plan['due_words'][:count]
            known = {w.key: w for w in self.catalog.load(deck)}
            words = tuple(known[key] for key in keys if key in known)
        else:
            words = self.catalog.sample(deck, count, keys)
        if not words:
            if due:
                next_day = plan['next_day'] or '暂无安排'
                raise ValueError(f'今日没有到期词；下次复习：{next_day}。也可以主动练习错词。')
            raise ValueError('这套词库还没有待复习词；先开始一轮拼写吧。')
        self.deck = deck
        self.session = SpellingSession(words, learning=True, due_review=due,
                                       day_provider=self.application_day)
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
        return self.record_attempt(event)

    def record_attempt(self, event):
        event = dict(event)
        event.setdefault('app_day', self.application_day())
        try:
            with self.repo.transaction():
                saved=self.storage.record_attempt(event)
                if saved:
                    self.repo.uow.changed('english')
                return saved
        except sqlite3.Error as error:
            raise EnglishSaveError('本次成绩未保存，输入已保留，请重试。') from error

    def advance(self):
        return self.session.advance() if self.session else False

    def correct(self, answer='', *, skip=False):
        return self.session.correct(answer, skip=skip) if self.session else False

    def spelling_view(self):
        return self.session.view() if self.session else None

    def summary(self, deck):
        return self.storage.summary(deck)

    def ai_access(self, ai_service, balance):
        if ai_service is None or not ai_service.enabled():
            return False, 'AI 未启用，打开 AI 配置即可连接你的模型。'
        level, _, _ = level_and_progress(self.repo.get_exp(), balance)
        return self.test_session.access(level, self.repo.count_ai_passes(), balance.get('ai', {}).get('unlock_level', 45))

    def save_generated(self, deck, topic, words, sentences, balance, *, test_mode=False, operation_id=None):
        valid = validate_sentences(sentences, words)
        known = {w.key for w in self.catalog.load(deck)}
        if any(w.casefold() not in known for w in words):
            raise ValueError('目标词不属于当前词库，请重新选词。')
        level, _, _ = level_and_progress(self.repo.get_exp(), balance)
        spend_pass = level < balance.get('ai', {}).get('unlock_level', 45) and not test_mode
        operation_id = operation_id or uuid.uuid4().hex
        def save():
            if spend_pass and not self.repo.use_reward('ai_pass'):
                raise ValueError('AI 训练券不足，生成内容未保存。')
            result = self.storage.save_sentences(deck,topic[:80],words,valid)
            self.repo.uow.changed('english')
            return result
        return self.repo.operation('english.material',operation_id,save)

    def sentence_history(self, deck):
        return self.storage.sentence_history(deck)

    def record_sentence(self, deck, reference, answer, elapsed, event_id=None):
        result = sentence_accuracy(answer, reference)
        accuracy = result['accuracy']
        event = dict(id=event_id or uuid.uuid4().hex, deck=deck, word='', mode='sentence',
                     correct=accuracy == 1, assisted=False, elapsed=elapsed, accuracy=accuracy)
        saved = self._save_attempt(event)
        return dict(result, saved=saved, elapsed=elapsed)

    def get_setting(self,key,default=None):
        return self.repo.get_setting(key,default)

    def set_font_size(self, size):
        if size not in ('standard', 'large', 'extra'):
            raise ValueError('请选择标准、大或特大字号。')
        return self.repo.set_setting('english_font_size', size)
