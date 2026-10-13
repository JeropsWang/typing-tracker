"""Wall time determines application dates; monotonic time measures duration."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Protocol

class Clock(Protocol):
    def now(self) -> datetime: ...
    def monotonic(self) -> float: ...

class SystemClock:
    def now(self):
        return datetime.now()
    def monotonic(self):
        return time.monotonic()

@dataclass(frozen=True)
class AppCalendar:
    start_hour: int = 4
    def __post_init__(self):
        if not 0 <= self.start_hour <= 23:
            raise ValueError('日切时间必须为 0 到 23 点。')
    def day(self, now):
        return (now - timedelta(hours=self.start_hour)).date().isoformat()
