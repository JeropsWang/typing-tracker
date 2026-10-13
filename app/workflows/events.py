"""Process-local notifications. Subscriber failures never undo committed work."""
from dataclasses import dataclass
import logging
import threading


@dataclass(frozen=True)
class Change:
    topic: str
    payload: object = None


class EventBus:
    def __init__(self):
        self._listeners = []
        self._lock = threading.Lock()

    def subscribe(self, callback):
        with self._lock:
            self._listeners.append(callback)
        def unsubscribe():
            with self._lock:
                if callback in self._listeners:
                    self._listeners.remove(callback)
        return unsubscribe

    def publish(self, event):
        with self._lock:
            callbacks = tuple(self._listeners)
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                logging.exception('Committed change subscriber failed: %s', event.topic)
