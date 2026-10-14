"""Shared generation admission and immutable per-request outcomes."""
from dataclasses import dataclass
import threading

class AIBusyError(RuntimeError):
    """已有生成或待处理结果占用共享准入时的可见业务异常。"""
    pass

@dataclass(frozen=True)
class AIResult:
    """携带请求 ID、生成内容、用量和错误的不可变请求结果，用于异步回传。"""
    request_id: str
    body: object = None
    usage: object = None
    error: str = ''
    @property
    def ok(self):
        """判断本次结果是否无错误，不以空字符串猜测网络状态。"""
        return not self.error

class GenerationGate:
    """配置快照共享的线程安全生成准入门，直到网络和结果处理都结束才放行。"""
    def __init__(self):
        """创建准入锁及空闲租约状态。"""
        self._lock=threading.Lock()
        self._active=None
    @property
    def busy(self):
        """持锁检查是否仍有在途网络或待保存结果占用准入。"""
        with self._lock:
            return self._active is not None
    def acquire(self,request_id):
        """按请求 ID 取得唯一租约，已有活动请求时抛 AIBusyError。"""
        with self._lock:
            if self._active is not None:
                raise AIBusyError('已有 AI 内容正在生成或等待保存，请完成或取消后重试。')
            lease=GenerationLease(self,request_id)
            self._active=lease
            return lease
    def _release(self,lease):
        """只释放仍匹配的租约，旧回调不能清空新请求准入。"""
        with self._lock:
            if self._active is lease:
                self._active=None

class GenerationLease:
    """单次生成的双阶段租约，分别跟踪网络完成和结果保存/丢弃完成。"""
    def __init__(self,gate,request_id):
        """绑定门与请求标识，初始化两个尚未完成标记和锁。"""
        self.gate,self.request_id=gate,request_id
        self._network_done=False
        self._result_done=False
        self._lock=threading.Lock()
    def _finish(self,network):
        """标记网络或结果阶段结束，两者都完成时才释放共享门。"""
        with self._lock:
            if network:
                self._network_done=True
            else:
                self._result_done=True
            if self._network_done and self._result_done:
                self.gate._release(self)
    def network_finished(self):
        """仅确认传输结束，尚待保存的结果继续占用准入。"""
        self._finish(True)
    def result_finished(self):
        """确认结果已保存或丢弃；仍在传输的取消请求继续占用准入。"""
        self._finish(False)

DEFAULT_GENERATION_GATE=GenerationGate()

def capture_result(request_id,action,client):
    """把生成回调的成功/失败/异常和本次用量组合为带稳定 ID 的 AIResult。"""
    try:
        ok,value=action()
        return AIResult(request_id,value if ok else None,getattr(client,'last_usage',None),'' if ok else str(value))
    except Exception as error:
        return AIResult(request_id,usage=getattr(client,'last_usage',None),error=str(error))
