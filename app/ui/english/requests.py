"""可失效的造句请求；工作线程不访问数据库。"""
import threading
import uuid
from PySide6.QtCore import QObject, Signal
from ...modules.english.api import EnglishAI
from ..tasks import begin_network, cancel_network


class SentenceRequest(QObject):
    done = Signal(str, bool, object)

    def __init__(self, ai_service, deck, words, topic, parent=None, *, test_mode=False):
        super().__init__(parent)
        self.id = uuid.uuid4().hex
        self.deck = deck
        self.words = tuple(words)
        self.topic = topic
        self.test_mode = test_mode
        self.usage = None
        self._generator = EnglishAI(ai_service)
        self._valid = True
        self._thread = None

    def start(self):
        if self._thread is None:
            begin_network(self,self._generator.service,
                          lambda:self._generator.generate(self.words,self.topic),
                          lambda result:self.done.emit(self.id,result.ok,result.body if result.ok else result.error))

    def cancel(self):
        cancel_network(self)
