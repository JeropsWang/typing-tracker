"""UI-facing capabilities and session presentation state. No SQL adapters."""
from dataclasses import dataclass
from enum import Enum
import uuid

class PracticeState(Enum):
    """练习展示状态枚举，区分进行、保存、失败和已提交完成。"""
    IDLE='idle'
    RUNNING='running'
    SAVING='saving'
    COMPLETED='completed'
    SAVE_FAILED='save_failed'

@dataclass
class PracticePresenter:
    """训练的展示/命令适配器，持有稳定操作 ID 和待保存结果，失败重试不重新结算。"""
    queries: object
    service: object
    state: PracticeState = PracticeState.IDLE
    operation_id: str = ''
    pending: object = None

    def start(self):
        """开始新练习并生成操作 ID，清除上一轮待保存结果。"""
        self.operation_id=uuid.uuid4().hex
        self.pending=None
        self.state=PracticeState.RUNNING
    def evaluate(self,typed,reference,elapsed,balance):
        """调用纯评分规则并补秒级用时，不写记录或发奖励。"""
        from ..modules.practice.api import score
        return dict(score(typed,reference,elapsed,balance),elapsed_seconds=elapsed)

    def complete(self,text_id,result,balance):
        """首次冻结结算结果，之后重试复用原值/操作 ID，交业务命令提交。"""
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
        """提交成功后标记练习完成，供 UI 后续庆祝。"""
        self.state=PracticeState.COMPLETED
    def failed(self):
        """将展示状态切为保存失败，保留原结算结果供重试。"""
        self.state=PracticeState.SAVE_FAILED
    def __getattr__(self,name):
        """把展示查询转发只读能力，不从 Presenter 创建数据库会话。"""
        return getattr(self.queries,name)

class QueryPresenter:
    """UI 的查询能力转发器，隔离具体模型实现与页面。"""
    def __init__(self,queries):
        """持有外部装配的查询能力，不持有 SQLite 连接。"""
        self._queries=queries
    def __getattr__(self,name):
        """将请求转交已装配的查询/异步能力门面。"""
        return getattr(self._queries,name)
