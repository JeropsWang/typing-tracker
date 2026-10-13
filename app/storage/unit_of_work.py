"""One application operation owns commit. Nested work uses savepoints, never commits."""
from contextlib import contextmanager
from functools import wraps
import inspect
import json
import uuid

from ..workflows.events import Change, EventBus


class UnitOfWork:
    def __init__(self, conn, events=None):
        self.conn = conn
        self.events = events or EventBus()
        self._depth = 0
        self._pending = []

    @contextmanager
    def transaction(self):
        nested = self.conn.in_transaction
        name = 'op_' + uuid.uuid4().hex
        offset = len(self._pending)
        self.conn.execute(f'SAVEPOINT {name}' if nested else 'BEGIN IMMEDIATE')
        self._depth += 1
        try:
            yield self
            if nested:
                self.conn.execute(f'RELEASE SAVEPOINT {name}')
            else:
                self.conn.commit()
        except BaseException:
            del self._pending[offset:]
            if nested:
                self.conn.execute(f'ROLLBACK TO SAVEPOINT {name}')
                self.conn.execute(f'RELEASE SAVEPOINT {name}')
            else:
                self.conn.rollback()
            raise
        finally:
            self._depth -= 1
        if not nested:
            pending, self._pending = self._pending, []
            changes = {event.topic: event for event in pending}
            if changes:
                self.events.publish(Change('commit',tuple(changes.values())))

    def changed(self, topic, payload=None):
        if not self._depth:
            raise RuntimeError('Changes must be registered inside a transaction')
        self._pending.append(Change(topic, payload))

    def operation(self, kind, operation_id, action):
        """Return the original result on retry, including after process restart."""
        with self.transaction():
            row = self.conn.execute(
                'SELECT result FROM operations WHERE kind=? AND operation_id=?',
                (kind, operation_id)).fetchone()
            if row:
                return json.loads(row[0])
            result = action()
            if result is None or result is False:
                return result
            self.conn.execute('INSERT INTO operations(kind,operation_id,result) VALUES(?,?,?)',
                              (kind, operation_id, json.dumps(result, ensure_ascii=False)))
            return result


def transactional(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        operation_id=kwargs.get('operation_id')
        if operation_id is not None and 'operation_id' not in inspect.signature(method).parameters:
            kwargs=dict(kwargs)
            del kwargs['operation_id']
            return self._repo.operation(f'{type(self).__name__}.{method.__name__}',operation_id,
                                        lambda:method(self,*args,**kwargs))
        with self._repo.transaction():
            return method(self, *args, **kwargs)
    return wrapped
