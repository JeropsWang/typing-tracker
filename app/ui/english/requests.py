"""可失效的造句请求；工作线程不访问数据库。"""
import threading
import uuid
from PySide6.QtCore import QObject, Signal
from ...english.ai import EnglishAI


class SentenceRequest(QObject):
    done = Signal(str, bool, object)

    def __init__(self, ai_service, deck, words, topic, parent=None):
        super().__init__(parent)
        self.id = uuid.uuid4().hex
        self.deck = deck
        self.words = tuple(words)
        self.topic = topic
        self._generator = EnglishAI(ai_service)
        self._valid = True
        self._thread = None

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def cancel(self):
        self._valid = False

    def _run(self):
        try:
            ok, result = self._generator.generate(self.words, self.topic)
        except Exception:
            ok, result = False, '生成失败，请检查 AI 服务或重试。'
        if self._valid:
            try:
                self.done.emit(self.id, ok, result)
            except RuntimeError:
                pass  # 应用退出后丢弃结果；守护线程不阻碍关闭。
