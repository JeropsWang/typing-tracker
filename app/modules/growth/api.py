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
    level: int
    streak: int

class GrowthQueries(Protocol):
    def get_exp(self) -> int: ...
    def get_streak(self,day: str) -> int: ...
    def list_rewards(self,unused_only: bool=False) -> list: ...
    def get_setting(self,key: str,default=None): ...

class GrowthCommands(Protocol):
    def apply_makeup_card(self,missed_date: str,today_iso=None,*,operation_id=None): ...
    def claim(self,code: str,*,operation_id=None): ...
    def use_exp_boost(self,minutes: int=30,*,operation_id=None): ...
