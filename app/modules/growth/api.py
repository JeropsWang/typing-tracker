"""Public growth capabilities."""
from .checkin import CheckinService
from .rewards import RewardService
from .achievements import AchievementService
from .encourage import EncourageService
from .experience import *
from .settlement import RewardLedger

from .access import AITestSession

from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class GrowthSummary:
    """供跨模块/UI 使用的不可变等级和连续打卡摘要。"""
    level: int
    streak: int

class GrowthQueries(Protocol):
    """成长的只读查询契约，允许使用脱离连接的展示模型实现。"""
    def get_exp(self) -> int:
        """查询终身经验，不改变成长状态。"""
        ...
    def get_streak(self,day: str) -> int:
        """查询指定应用日连续打卡天数。"""
        ...
    def list_rewards(self,unused_only: bool=False) -> list:
        """查询库存记录，可只返回尚未使用的奖励。"""
        ...
    def get_setting(self,key: str,default=None):
        """读取成长相关配置键，缺失时采用默认值。"""
        ...

class GrowthCommands(Protocol):
    """成长的事务写能力契约；重试使用稳定操作 ID。"""
    def apply_makeup_card(self,missed_date: str,today_iso=None,*,operation_id=None):
        """在统一事务内消费补签卡并补昨天记录，失败不丢卡，重试按操作 ID 去重。"""
        ...
    def claim(self,code: str,*,operation_id=None):
        """以稳定操作 ID 原子领取已解锁成就奖励。"""
        ...
    def use_exp_boost(self,minutes: int=30,*,operation_id=None):
        """原子消费一张加成卡并设置分钟级有效期限。"""
        ...
