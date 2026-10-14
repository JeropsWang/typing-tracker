"""Wall time determines application dates; monotonic time measures duration."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Protocol

class Clock(Protocol):
    """纯规则使用的可注入时钟契约，墙上时间用于日切，单调时间用于持续计时。"""
    def now(self) -> datetime:
        """取得当前墙上 datetime，供应用日期与时间展示使用。"""
        ...
    def monotonic(self) -> float:
        """取得只前进的秒级计时值，避免系统时间调整影响持续时间。"""
        ...

class SystemClock:
    """系统墙上时间与单调计时的默认适配器。"""
    def now(self):
        """读取本机墙上时间，返回 datetime。"""
        return datetime.now()
    def monotonic(self):
        """读取系统单调秒数，不能当作日历时间。"""
        return time.monotonic()

@dataclass(frozen=True)
class AppCalendar:
    """由日切小时定义的纯应用日历，默认凌晨四点归入新应用日。"""
    start_hour: int = 4
    def __post_init__(self):
        """校验日切小时处于 0–23，非法配置抛 ValueError。"""
        if not 0 <= self.start_hour <= 23:
            raise ValueError('日切时间必须为 0 到 23 点。')
    def day(self, now):
        """将墙上时间减去日切偏移，返回 ISO 格式应用日期。"""
        return (now - timedelta(hours=self.start_hour)).date().isoformat()
