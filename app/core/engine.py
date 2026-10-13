"""Compatibility entry point for existing tools and clock-patching regression tests."""
from datetime import datetime
import time
from ..modules.tracking.api import TrackingService

class _LegacyClock:
    def now(self):
        return datetime.now()
    def monotonic(self):
        return time.monotonic()

class StatsEngine(TrackingService):
    def __init__(self, repo, get_setting, balance):
        super().__init__(repo,get_setting,balance,clock=_LegacyClock())
