"""桌宠搜索的异步能力入口：单次准入、独立网络线程和稳定请求 ID。

取消只设置失效信号；在途网络真正结束后才能释放准入，不持有数据库或 QWidget。
"""
from concurrent.futures import Future
import threading
import uuid
from ...modules.companion.api import validate_topic
from .model import CompanionModel
from .search import WebSearch, AgentError
from .graph import run_search


class CompanionAgentService:
    """可由 UI 调用的线程安全服务；锁只保护准入状态，不在锁内执行网络。"""
    def __init__(self, *, model_factory=CompanionModel, search_factory=WebSearch):
        """装配可替换的模型/搜索工厂，初始化空闲与未关闭状态。"""
        self.model_factory, self.search_factory = model_factory, search_factory
        self._lock = threading.Lock()
        self._cancel = None
        self._closed = False

    def search(self, config, topic, progress):
        """校验配置、取得单次准入并异步执行图，立即返回请求 ID 与结果 Future。"""
        topic = validate_topic(topic)
        if not config.enabled:
            raise AgentError('先在桌宠自定义 → 智能体中开启并配置联网搜索吧。')
        model, search = self.model_factory(config), self.search_factory(config)
        model.validate()
        search.validate()
        with self._lock:
            if self._closed:
                raise AgentError('桌宠智能体已关闭。')
            if self._cancel is not None:
                raise AgentError('上一项任务还在结束，请稍等再试。')
            cancel = threading.Event()
            self._cancel = cancel
        future = Future()
        request_id = uuid.uuid4().hex
        def run():
            """在守护网络线程中执行图；结束后释放准入，再完成 Future 供 UI 桥接。"""
            try:
                result = run_search(request_id, topic, model, search, cancel, progress)
            except Exception as error:
                # 未知异常可能含上游 URL/密钥等信息，只向界面返回固定的脱敏提示。
                failure = error if isinstance(error, AgentError) else AgentError('搜索未完成，请检查服务配置后重试。')
                with self._lock:
                    self._cancel = None
                future.set_exception(failure)
            else:
                with self._lock:
                    self._cancel = None
                future.set_result(result)
        threading.Thread(target=run, name='sariana-companion-agent', daemon=True).start()
        return request_id, future

    def cancel(self):
        """标记当前任务取消；不提前清空 _cancel，否则未结束的网络会重叠运行。"""
        with self._lock:
            if self._cancel is not None:
                self._cancel.set()

    def close(self):
        """永久拒绝新任务并标记在途任务取消，供桌宠退出时调用。"""
        with self._lock:
            self._closed = True
            if self._cancel is not None:
                self._cancel.set()
