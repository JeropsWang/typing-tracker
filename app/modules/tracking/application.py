"""Synchronous composition for tools/tests. Desktop dispatches checkpoint writes to its worker."""
from .domain import TrackingCounter
from .clock import SystemClock

class TrackingService(TrackingCounter):
    """兼容统计应用入口，从仓储恢复内存计数并装配检查点写入工作流。"""
    def __init__(self, repo, get_setting, balance, *, clock=None):
        """读取近期日期/分钟、终身总量和持久版本，恢复计数器并装配保存能力。"""
        clock = clock or SystemClock()
        days = repo.get_recent_days(2)
        minutes = [row for d in days for row in repo.get_minutes(d['date'])]
        row = repo._conn.execute('SELECT version FROM tracking_checkpoint WHERE id=1').fetchone()
        super().__init__(balance,clock=clock,start_hour=int(get_setting('day_start_hour',balance.get('day_start_hour',4))),
                         lifetime=repo.get_lifetime(),days=days,minutes=minutes,version=row['version'] if row else 0)
        self._get_setting = get_setting
        from ...workflows.checkpoint import CheckpointWriter
        self._save = CheckpointWriter(repo,balance).save

    def update_day_start(self):
        """同步已保存日切设置并立即执行日切检查。"""
        self.set_day_start(int(self._get_setting('day_start_hour',self._balance.get('day_start_hour',4))))
        return self.check_rollover()
