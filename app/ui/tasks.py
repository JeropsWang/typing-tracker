"""Deliver worker results on the receiver's Qt thread; direct fixtures remain synchronous."""
from concurrent.futures import Future
from PySide6.QtCore import QObject, Qt, Signal, Slot

class TaskBridge(QObject):
    """Qt 主线程 Future 回传桥；后台只发排队信号，控件回调在所属 Qt 线程执行。"""
    completed=Signal(object)
    def __init__(self,parent=None):
        """创建排队完成信号连接，生命周期随所属 UI 对象结束。"""
        super().__init__(parent)
        self.completed.connect(self._deliver,Qt.QueuedConnection)
    def resolve(self,value,success,error=None):
        """同步值立即回调，Future 则登记完成通知而不在 UI 阻塞等待。"""
        if not isinstance(value,Future):
            success(value)
            return
        def finished(future):
            """后台完成时只发排队信号；UI 已销毁则忽略失效对象回调。"""
            try:
                self.completed.emit((future,success,error))
            except RuntimeError:
                pass
        value.add_done_callback(finished)
    @Slot(object)
    def _deliver(self,item):
        """在 Qt 线程读取已完成 Future 并分流成功/错误回调。"""
        future,success,error=item
        try:
            result=future.result()
        except Exception as exc:
            if error:
                error(exc)
            return
        success(result)


def begin_network(request,client,action,deliver):
    """取得共享生成租约并启动配置快照的网络线程，不把 QWidget 或数据库交给后台。"""
    import threading
    from ..integrations.ai.requests import DEFAULT_GENERATION_GATE, capture_result
    gate=getattr(client,'generation_gate',DEFAULT_GENERATION_GATE)
    request._lease=gate.acquire(request.id)
    def run():
        """捕获完整 AIResult 并拒绝取消后结果；最终确认传输结束，等待保存/丢弃阶段释放准入。"""
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
    """标记结果已保存或丢弃，仅两阶段都结束时共享准入才释放。"""
    lease=getattr(request,'_lease',None)
    if lease is not None:
        lease.result_finished()


def cancel_network(request):
    """立即使结果无效并结束结果处理阶段，未结束的网络仍持有租约。"""
    request._valid=False
    finish_network_result(request)
