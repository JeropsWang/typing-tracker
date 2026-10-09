"""A fixed 15-second character sprint, independent of UI and storage."""
import time
import uuid
from .classifier import text_tw


class KeyboardSession:
    duration = 15.0

    def __init__(self, balance=None, *, clock=time.monotonic):
        self.id = uuid.uuid4().hex
        self._clock = clock
        self._started = clock()
        self._balance = balance
        self.tw = 0
        self.typed_chars = 0

    @property
    def remaining(self):
        return max(0, self.duration - (self._clock() - self._started))

    def add_text(self, text):
        if self.remaining <= 0:
            return
        self.tw += text_tw(text, self._balance)
        self.typed_chars += len(text)

    def result(self):
        if self.remaining > 0:
            raise ValueError('15 秒结束后才可结算。')
        return dict(id=self.id, tw=self.tw, typed_chars=self.typed_chars,
                    elapsed_seconds=self.duration, speed=self.tw * 4)
