"""Compatibility entry point for existing tools and clock-patching regression tests."""
from datetime import datetime
import time
from ..modules.tracking.api import TrackingService

class _LegacyClock:
    """保留旧入口可打补丁的墙上/单调时钟，供兼容工具和回归测试。"""
    def now(self):
        """读取旧入口的墙上时间，使历史测试的时间替换仍有效。"""
        return datetime.now()
    def monotonic(self):
        """读取单调秒数，供持续计时。"""
        return time.monotonic()

class StatsEngine(TrackingService):
    """旧统计入口的转发适配器，实际业务规则由 tracking 模块维护。"""
    def __init__(self, repo, get_setting, balance):
        """装配 tracking 服务并注入兼容时钟，不另建计数口径。"""
        super().__init__(repo,get_setting,balance,clock=_LegacyClock())
