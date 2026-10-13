"""Single application worker owns SQLite creation, use and close."""
from concurrent.futures import Future
import queue
import threading

class ApplicationWorker:
    def __init__(self, initialize, finalize):
        self._queue=queue.Queue()
        self._gate=threading.Lock()
        self._accepting=True
        self._initialize=initialize
        self._finalize=finalize
        self.ready=Future()
        self._thread=threading.Thread(target=self._run,name='sariana-application',daemon=False)
        self._thread.start()

    def submit(self, action):
        future=Future()
        with self._gate:
            if not self._accepting:
                future.set_exception(RuntimeError('应用正在退出，不再接受新任务。'))
            else:
                self._queue.put((future,action))
        return future

    def _run(self):
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
        with self._gate:
            self._accepting=False
            self._queue.put(None)
        self._thread.join()
