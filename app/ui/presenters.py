"""UI-facing capabilities and session presentation state. No SQL adapters."""
from dataclasses import dataclass
from enum import Enum
import uuid

class PracticeState(Enum):
    IDLE='idle'
    RUNNING='running'
    SAVING='saving'
    COMPLETED='completed'
    SAVE_FAILED='save_failed'

@dataclass
class PracticePresenter:
    queries: object
    service: object
    state: PracticeState = PracticeState.IDLE
    operation_id: str = ''
    pending: object = None

    def start(self):
        self.operation_id=uuid.uuid4().hex
        self.pending=None
        self.state=PracticeState.RUNNING
    def evaluate(self,typed,reference,elapsed,balance):
        from ..modules.practice.api import score
        return dict(score(typed,reference,elapsed,balance),elapsed_seconds=elapsed)

    def complete(self,text_id,result,balance):
        if self.state not in (PracticeState.RUNNING,PracticeState.SAVE_FAILED):
            raise RuntimeError('当前练习不能结算。')
        if self.pending is None:
            self.pending=(text_id,dict(result),balance)
        self.state=PracticeState.SAVING
        text_id,result,balance=self.pending
        try:
            return self.service.record(text_id,result,balance,operation_id=self.operation_id)
        except Exception:
            self.state=PracticeState.SAVE_FAILED
            raise
    def saved(self):
        self.state=PracticeState.COMPLETED
    def failed(self):
        self.state=PracticeState.SAVE_FAILED
    def __getattr__(self,name):
        return getattr(self.queries,name)

class QueryPresenter:
    def __init__(self,queries):
        self._queries=queries
    def __getattr__(self,name):
        return getattr(self._queries,name)
