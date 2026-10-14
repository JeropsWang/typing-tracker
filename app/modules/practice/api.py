"""普通训练与键盘侠的公开业务接口，导出纯评分及异步查询/提交契约。"""
from .service import ChallengeService
from .keyboard import KeyboardWarriorService
from .domain import TEXTS, score, ai_access_state
from .keyboard_session import KeyboardSession

from typing import Protocol

class PracticeCommands(Protocol):
    """训练成绩提交契约，写入交给应用线程并以稳定操作 ID 重试。"""
    def record(self,text_id: str,result: dict,balance=None,operation_id=None):
        """原子记录评分、纪录及奖励，重复操作返回原已提交结果。"""
        ...

class PracticeQueries(Protocol):
    """训练排行榜与历史的只读查询契约。"""
    def leaderboard(self,text_id: str,n: int=10) -> list:
        """查询同一范文有界单次成绩排行榜。"""
        ...
    def recent(self,n: int=8) -> list:
        """查询最近训练历史，不修改纪录或奖励。"""
        ...
