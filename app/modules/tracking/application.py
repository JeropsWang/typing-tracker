"""Synchronous composition for tools/tests. Desktop dispatches checkpoint writes to its worker."""
from .domain import TrackingCounter
from .clock import SystemClock

class TrackingService(TrackingCounter):
    def __init__(self, repo, get_setting, balance, *, clock=None):
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
        self.set_day_start(int(self._get_setting('day_start_hour',self._balance.get('day_start_hour',4))))
        return self.check_rollover()
