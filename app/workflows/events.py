"""Process-local notifications. Subscriber failures never undo committed work."""
from dataclasses import dataclass
import logging
import threading


@dataclass(frozen=True)
class Change:
    """已提交业务变化的进程内通知数据，topic 表示所属展示失效主题。"""
    topic: str
    payload: object = None


class EventBus:
    """带锁的进程内通知总线，调用订阅者时不持锁，订阅失败不撤销已提交工作。"""
    def __init__(self):
        """创建订阅列表和保护订阅状态的锁。"""
        self._listeners = []
        self._lock = threading.Lock()

    def subscribe(self, callback):
        """登记变化订阅者，返回可幂等解除订阅的函数。"""
        with self._lock:
            self._listeners.append(callback)
        def unsubscribe():
            """解除当前回调订阅，重复取消不报错。"""
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def publish(self, event):
        """复制订阅列表后依次通知，记录单个订阅异常并继续其他回调。"""
        with self._lock:
            callbacks = tuple(self._listeners)
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logging.exception('Committed change subscriber failed: %s', event.topic)
