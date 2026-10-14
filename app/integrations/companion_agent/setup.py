"""智能体配置草稿的异步连接检查；只请求网络，不把草稿写入数据库。"""
from concurrent.futures import Future
import threading
import time
from ...modules.companion.api import AgentConnectionResult
from .model import CompanionModel
from .search import WebSearch, AgentError, check_cancel


class AgentSetupService:
    """草稿检查的线程安全能力入口；与正式搜索独立准入，取消后等待实际结束。"""
    def __init__(self, *, model_factory=CompanionModel, search_factory=WebSearch):
        """装配检查所用网络工厂，创建独立的准入锁与关闭状态。"""
        self.model_factory, self.search_factory = model_factory, search_factory
        self._lock = threading.Lock()
        self._cancel = None
        self._closed = False

    def _run(self, action):
        """以独立后台线程执行检查 action(cancel)，返回 Future，不阻塞 Qt 主线程。"""
        with self._lock:
            if self._closed or self._cancel is not None:
                raise AgentError('上一项检查还在结束，请稍后再试。')
            cancel = threading.Event()
            self._cancel = cancel
        future = Future()
        def run():
            """执行检查并拒绝取消后的成功结果；结束后释放准入并完成 Future。"""
            try:
                result = action(cancel)
                check_cancel(cancel)
            except Exception as error:
                failure = error if isinstance(error, AgentError) else AgentError('检查未完成，请检查配置后重试。')
                with self._lock:
                    self._cancel = None
                future.set_exception(failure)
            else:
                with self._lock:
                    self._cancel = None
                future.set_result(result)
        threading.Thread(target=run, name='sariana-agent-setup', daemon=True).start()
        return future

    def test_model(self, config):
        """使用未保存配置发送短模型请求；验证连接，但不保存草稿或验证工具能力。"""
        def check(cancel):
            """计量模型连接耗时，以秒为单位返回脱敏的可见连接结果。"""
            started = time.monotonic()
            model = self.model_factory(config)
            model.test_connection(cancel)
            elapsed = time.monotonic() - started
            return AgentConnectionResult(f'模型连接成功 · {config.model_settings()["model"]} · {elapsed:.2f} 秒', elapsed)
        return self._run(check)

    def test_search(self, config, progress=lambda _: None):
        """异步检查草稿搜索配置是否返回真实来源；保留进度参数作为能力契约。"""
        return self._run(lambda cancel:self._search_check(config, cancel, progress))

    def _search_check(self, config, cancel, progress):
        """检索固定的 Python 话题并返回来源数量与秒级耗时，不调用模型整理。"""
        started = time.monotonic()
        sources = self.search_factory(config).search('Python', cancel)
        elapsed = time.monotonic() - started
        return AgentConnectionResult(f'搜索连接成功 · {len(sources)} 条来源 · {elapsed:.2f} 秒', elapsed, len(sources))

    def cancel(self):
        """标记检查取消；在途 action 结束前保持准入，避免重复请求。"""
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()

    def close(self):
        """永久停止新检查并标记在途检查取消；由界面销毁流程调用。"""
        with self._lock:
            self._closed = True
            if self._cancel is not None:
                self._cancel.set()
