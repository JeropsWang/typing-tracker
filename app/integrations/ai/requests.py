"""Shared generation admission and immutable per-request outcomes."""
from dataclasses import dataclass
import threading

class AIBusyError(RuntimeError):
    pass

@dataclass(frozen=True)
class AIResult:
    request_id: str
    body: object = None
    usage: object = None
    error: str = ''
    @property
    def ok(self):
        return not self.error

class GenerationGate:
    def __init__(self):
        self._lock=threading.Lock()
        self._active=None
    @property
    def busy(self):
        with self._lock:
            return self._active is not None
    def acquire(self,request_id):
        with self._lock:
            if self._active is not None:
                raise AIBusyError('已有 AI 内容正在生成或等待保存，请完成或取消后重试。')
            lease=GenerationLease(self,request_id)
            self._active=lease
            return lease
    def _release(self,lease):
        with self._lock:
            if self._active is lease:
                self._active=None

class GenerationLease:
    def __init__(self,gate,request_id):
        self.gate,self.request_id=gate,request_id
        self._network_done=False
        self._result_done=False
        self._lock=threading.Lock()
    def _finish(self,network):
        with self._lock:
            if network:
                self._network_done=True
            else:
                self._result_done=True
            if self._network_done and self._result_done:
                self.gate._release(self)
    def network_finished(self):
        self._finish(True)
    def result_finished(self):
        self._finish(False)

DEFAULT_GENERATION_GATE=GenerationGate()

def capture_result(request_id,action,client):
    try:
        ok,value=action()
        return AIResult(request_id,value if ok else None,getattr(client,'last_usage',None),'' if ok else str(value))
    except Exception as error:
        return AIResult(request_id,usage=getattr(client,'last_usage',None),error=str(error))
