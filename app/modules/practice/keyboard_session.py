"""A fixed 15-second character sprint, independent of UI and storage."""
import time
import uuid
from ..tracking.api import text_tw


class KeyboardSession:
    """可注入单调时钟的十五秒纯计数会话，保留数值而非输入正文。"""
    duration = 15.0

    def __init__(self, balance=None, *, clock=time.monotonic):
        """生成稳定会话 ID，记录开始时间和加权配置，初始化字数/tw。"""
        self.id = uuid.uuid4().hex
        self._clock = clock
        self._started = clock()
        self._balance = balance
        self.tw = 0
        self.typed_chars = 0

    @property
    def remaining(self):
        """返回非负剩余秒数，系统墙上时间变化不影响测试期限。"""
        return max(0, self.duration - (self._clock() - self._started))

    def add_text(self, text):
        """会话有效期内将主动上屏文字转换为字数/tw，结束后忽略新增输入。"""
        if self.remaining <= 0:
            return
        self.tw += text_tw(text, self._balance)
        self.typed_chars += len(text)

    def result(self):
        """只允许十五秒结束后返回稳定 ID 与数值结果；提前结算抛 ValueError。"""
        if self.remaining > 0:
            raise ValueError('15 秒结束后才可结算。')
        return dict(id=self.id, tw=self.tw, typed_chars=self.typed_chars,
                    elapsed_seconds=self.duration, speed=self.tw * 4)
