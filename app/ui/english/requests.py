"""可失效的造句请求；工作线程不访问数据库。"""
import threading
import uuid
from PySide6.QtCore import QObject, Signal
from ...modules.english.api import EnglishAI
from ..tasks import begin_network, cancel_network


class SentenceRequest(QObject):
    """英语造句的单次异步请求对象，固定词库/目标词/主题并按 ID 拒绝迟到结果。"""
    done = Signal(str, bool, object)

    def __init__(self, ai_service, deck, words, topic, parent=None, *, test_mode=False):
        """捕获独立模型配置及请求输入，初始化稳定 ID、用量和有效性标记。"""
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
        """只启动一次造句请求，经共享准入在网络线程生成，结果通过 Qt 信号回传。"""
        if self._thread is None:
            begin_network(self,self._generator.service,
                          lambda:self._generator.generate(self.words,self.topic),
                          lambda result:self.done.emit(self.id,result.ok,result.body if result.ok else result.error))

    def cancel(self):
        """标记造句结果失效，传输实际结束前不提前释放共享生成准入。"""
        cancel_network(self)
