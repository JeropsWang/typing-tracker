"""Deliver worker results on the receiver's Qt thread; direct fixtures remain synchronous."""
from concurrent.futures import Future
from PySide6.QtCore import QObject, Qt, Signal, Slot

class TaskBridge(QObject):
    completed=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.completed.connect(self._deliver,Qt.QueuedConnection)
    def resolve(self,value,success,error=None):
        if not isinstance(value,Future):
            success(value)
            return
        def finished(future):
            try:
                self.completed.emit((future,success,error))
            except RuntimeError:
                pass
        value.add_done_callback(finished)
    @Slot(object)
    def _deliver(self,item):
        future,success,error=item
        try:
            result=future.result()
        except Exception as exc:
            if error:
                error(exc)
            return
        success(result)


def begin_network(request,client,action,deliver):
    import threading
    from ..integrations.ai.requests import DEFAULT_GENERATION_GATE, capture_result
    gate=getattr(client,'generation_gate',DEFAULT_GENERATION_GATE)
    request._lease=gate.acquire(request.id)
    def run():
        try:
            result=capture_result(request.id,action,client)
            request.result=result
            request.usage=result.usage
            if request._valid:
                try:
                    deliver(result)
                except RuntimeError:
                    request._lease.result_finished()
            else:
                request._lease.result_finished()
        finally:
            request._lease.network_finished()
            finished=getattr(request,'finished',None)
            if finished is not None:
                try:
                    finished.emit()
                except RuntimeError:
                    pass
    request._thread=threading.Thread(target=run,name='sariana-ai',daemon=True)
    request._thread.start()


def finish_network_result(request):
    lease=getattr(request,'_lease',None)
    if lease is not None:
        lease.result_finished()


def cancel_network(request):
    request._valid=False
    finish_network_result(request)
