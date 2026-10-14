"""Single application worker owns SQLite creation, use and close."""
from concurrent.futures import Future
import queue
import threading

class ApplicationWorker:
    """拥有数据库连接的串行应用线程，接收异步命令并将结果写入 Future。"""
    def __init__(self, initialize, finalize):
        """建立命令队列和准入锁，启动非守护应用线程，ready 表示后台初始化结果。"""
        self._queue=queue.Queue()
        self._gate=threading.Lock()
        self._accepting=True
        self._initialize=initialize
        self._finalize=finalize
        self.ready=Future()
        self._thread=threading.Thread(target=self._run,name='sariana-application',daemon=False)
        self._thread.start()

    def submit(self, action):
        """原子检查准入并排队命令；关闭后返回失败 Future，不在调用线程执行数据库操作。"""
        future=Future()
        with self._gate:
            if not self._accepting:
                future.set_exception(RuntimeError('应用正在退出，不再接受新任务。'))
            else:
                self._queue.put((future,action))
        return future

    def _run(self):
        """在所属线程初始化上下文、串行执行命令并最终释放资源，单项失败不阻断后续命令。"""
        context=None
        try:
            context=self._initialize()
            self.ready.set_result(context)
            while True:
                item=self._queue.get()
                if item is None:
                    break
                future,action=item
                if future.set_running_or_notify_cancel():
                    try:
                        future.set_result(action(context))
                    except BaseException as error:
                        future.set_exception(error)
        except BaseException as error:
            if not self.ready.done():
                self.ready.set_exception(error)
        finally:
            if context is not None:
                self._finalize(context)

    def close(self):
        """停止接收新命令，排队结束哨兵并等待已接收任务和后台清理完成。"""
        with self._gate:
            self._accepting=False
            self._queue.put(None)
        self._thread.join()
