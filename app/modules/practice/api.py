from .service import ChallengeService
from .keyboard import KeyboardWarriorService
from .domain import TEXTS, score, ai_access_state
from .keyboard_session import KeyboardSession

from typing import Protocol

class PracticeCommands(Protocol):
    def record(self,text_id: str,result: dict,balance=None,operation_id=None): ...

class PracticeQueries(Protocol):
    def leaderboard(self,text_id: str,n: int=10) -> list: ...
    def recent(self,n: int=8) -> list: ...
