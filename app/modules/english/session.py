"""拼写练习状态机；不依赖 Qt、数据库或网络。"""
import time
import uuid


class SpellingSession:
    def __init__(self, words):
        if not words:
            raise ValueError('没有可练习的单词。')
        self.words = tuple(words)
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

    def submit(self, answer):
        result = self.prepare(answer)
        if result.get('accepted'):
            self.confirm(result)
        return result

    def prepare(self, answer):
        """准备一次作答；由服务先保存，成功后再确认题目状态。"""
        if self.finished or self.result is not None:
            return {'accepted': False}
        if not answer.strip():
            return {'accepted': False, 'error': '先输入一个英文单词。'}
        correct = answer.strip().casefold() == self.current.key
        return self._make_result(correct, self.assisted)

    def _make_result(self, correct, assisted):
        return dict(id=f'{self._id}:{self.index}', accepted=True,
                    word=self.current.key, mode='spelling', correct=correct,
                    assisted=assisted, independent=correct and not assisted,
                    elapsed=max(0, time.monotonic() - self._started))

    def prepare_reveal(self):
        if self.finished or self.result is not None:
            return {'accepted': False}
        return self._make_result(False, True)

    def confirm(self, result):
        if self.finished or self.result is not None or result.get('id') != f'{self._id}:{self.index}':
            return False
        self.result = dict(result)
        self.assisted = self.result['assisted']
        self.results.append(self.result)
        return True

    def hint(self):
        if self.current is None:
            return ''
        if self.result is None:
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
        self.index += 1
        self.result = None
        self.assisted = False
        self._started = time.monotonic()
        return not self.finished
