"""拼写练习状态机；不依赖 Qt、数据库或网络。"""
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class SpellingView:
    """不可变拼写展示状态，分别保留首测、纠正和复测统计，避免辅助输入抬高正确率。"""
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
    """纯拼写学习会话，准备/确认作答分离，保存重试不会产生新 ID 或提前跳题。"""
    def __init__(self, words, *, learning=False, due_review=False, day_provider=None):
        """建立首测词序、复测队列及稳定会话 ID，注入应用日提供器用于结果归属。"""
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
        """判断词序是否全部完成，含首轮后追加的复测词。"""
        return self.index >= len(self.words)

    @property
    def current(self):
        """取得当前词条；会话结束后返回 None。"""
        return None if self.finished else self.words[self.index]

    @property
    def correcting(self):
        """判断学习模式下错误/辅助作答是否仍需纠正一次。"""
        return bool(self.learning and self.result and not self.result['independent']
                    and not self._correction_done)

    @property
    def phase(self):
        """返回首测、纠正、复测或完成阶段，不把纠正算成新的独立作答。"""
        if self.finished:
            return 'completed'
        if self.correcting:
            return 'correction'
        return 'retest' if self.index >= self.first_total else 'first'

    def view(self):
        """分别汇总首测独立正确、纠正与复测数据，生成只读展示快照。"""
        first = self.results[:self.first_total]
        retest = self.results[self.first_total:]
        return SpellingView(self.phase, self.index, len(self.words),
            sum(r['independent'] for r in first), self.first_total, self.corrected,
            self.correction_skipped, sum(r['independent'] for r in retest), len(self._retest_words))

    def correct(self, answer=None, *, skip=False):
        """当前纠正阶段只接受正确词或显式跳过；更新纠正状态，不改首测结果。"""
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
        """兼容纯会话入口：准备结果后立即确认；生产异步流程使用分开的两步。"""
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
        """冻结当前作答 ID、阶段、辅助标记、耗时与应用日，供保存失败重试复用。"""
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
        """准备查看答案的辅助失败事件，已有待保存结果时保持原 ID/结果。"""
        if self.finished or self.result is not None:
            return {'accepted': False}
        return dict(self._prepared) if self._prepared is not None else self._make_result(False, True)

    def confirm(self, result):
        """仅确认当前稳定题目 ID 的已保存结果，必要时将首测错词加入复测队列。"""
        if self.finished or self.result is not None or result.get('id') != f'{self._id}:{self.index}':
            return False
        self.result = dict(result)
        self.assisted = self.result['assisted']
        self.results.append(self.result)
        if self.learning and self.index < self.first_total and not self.result['independent']:
            self._retest_words.append(self.current)
        return True

    def hint(self):
        """提供首字母并在结果准备前标记辅助，不能用于刷独立正确率。"""
        if self.current is None:
            return ''
        if self.result is None and self._prepared is None:
            self.assisted = True
        return self.current.word[0]

    def reveal(self):
        """兼容同步入口：准备并确认查看答案事件，再返回单词全文。"""
        if self.current is None:
            return ''
        word = self.current.word
        result = self.prepare_reveal()
        if result.get('accepted'):
            self.confirm(result)
        return word

    def advance(self):
        """完成必要纠正后跳下一题，首轮结束时追加每个错词一次并清除本题临时状态。"""
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
