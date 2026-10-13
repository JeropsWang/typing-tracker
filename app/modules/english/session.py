"""拼写练习状态机；不依赖 Qt、数据库或网络。"""
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SpellingView:
    phase: str
    index: int
    total: int
    first_correct: int
    first_total: int
    corrected: int
    correction_skipped: int
    retest_correct: int
    retest_total: int


class SpellingSession:
    def __init__(self, words, *, learning=False, due_review=False, day_provider=None):
        if not words:
            raise ValueError('没有可练习的单词。')
        self.words = tuple(words)
        self.first_total = len(self.words)
        self.learning = learning
        self.due_review = due_review
        self.day_provider = day_provider
        self._retest_words = []
        self._correction_done = False
        self.corrected = 0
        self.correction_skipped = 0
        self._prepared = None
        self.index = 0
        self.results = []
        self.result = None
        self.assisted = False
        self._id = uuid.uuid4().hex
        self._started = time.monotonic()

    @property
    def finished(self):
        return self.index >= len(self.words)

    @property
    def current(self):
        return None if self.finished else self.words[self.index]

    @property
    def correcting(self):
        return bool(self.learning and self.result and not self.result['independent']
                    and not self._correction_done)

    @property
    def phase(self):
        if self.finished:
            return 'completed'
        if self.correcting:
            return 'correction'
        return 'retest' if self.index >= self.first_total else 'first'

    def view(self):
        first = self.results[:self.first_total]
        retest = self.results[self.first_total:]
        return SpellingView(self.phase, self.index, len(self.words),
            sum(r['independent'] for r in first), self.first_total, self.corrected,
            self.correction_skipped, sum(r['independent'] for r in retest), len(self._retest_words))

    def correct(self, answer=None, *, skip=False):
        if not self.correcting:
            return False
        if not skip and (answer or '').strip().casefold() != self.current.key:
            return False
        self._correction_done = True
        if skip:
            self.correction_skipped += 1
        else:
            self.corrected += 1
        return True

    def submit(self, answer):
        result = self.prepare(answer)
        if result.get('accepted'):
            self.confirm(result)
        return result

    def prepare(self, answer):
        """准备一次作答；由服务先保存，成功后再确认题目状态。"""
        if self.finished or self.result is not None:
            return {'accepted': False}
        if self._prepared is not None:
            return dict(self._prepared)
        if not answer.strip():
            return {'accepted': False, 'error': '先输入一个英文单词。'}
        correct = answer.strip().casefold() == self.current.key
        return self._make_result(correct, self.assisted)

    def _make_result(self, correct, assisted):
        self._prepared = dict(id=f'{self._id}:{self.index}', accepted=True,
                    word=self.current.key, mode='spelling', correct=correct,
                    assisted=assisted, independent=correct and not assisted,
                    due_review=self.due_review and self.index < self.first_total,
                    retest=self.index >= self.first_total,
                    elapsed=max(0, time.monotonic() - self._started))
        if self.day_provider is not None:
            self._prepared['app_day'] = self.day_provider()
        return dict(self._prepared)

    def prepare_reveal(self):
        if self.finished or self.result is not None:
            return {'accepted': False}
        return dict(self._prepared) if self._prepared is not None else self._make_result(False, True)

    def confirm(self, result):
        if self.finished or self.result is not None or result.get('id') != f'{self._id}:{self.index}':
            return False
        self.result = dict(result)
        self.assisted = self.result['assisted']
        self.results.append(self.result)
        if self.learning and self.index < self.first_total and not self.result['independent']:
            self._retest_words.append(self.current)
        return True

    def hint(self):
        if self.current is None:
            return ''
        if self.result is None and self._prepared is None:
            self.assisted = True
        return self.current.word[0]

    def reveal(self):
        if self.current is None:
            return ''
        word = self.current.word
        result = self.prepare_reveal()
        if result.get('accepted'):
            self.confirm(result)
        return word

    def advance(self):
        if self.result is None:
            return not self.finished
        if self.correcting:
            raise ValueError('先正确输入一次，或跳过纠正。')
        self.index += 1
        if self.learning and self.index == self.first_total:
            self.words += tuple(self._retest_words)
        self.result = None
        self._prepared = None
        self._correction_done = False
        self.assisted = False
        self._started = time.monotonic()
        return not self.finished
