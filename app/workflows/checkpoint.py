"""Persist a tracking checkpoint and growth settlement in one transaction."""
from datetime import datetime, timedelta
from ..modules.growth.api import RewardLedger

class CheckpointWriter:
    """跨统计/成长模块的统一检查点写入流程，持久版本阻止重复结算。"""
    def __init__(self, repo, balance):
        """装配统一会话与参与同一事务的成长结算器。"""
        self.repo = repo
        self.ledger = RewardLedger(repo,balance)

    def save(self, checkpoint):
        """原子提交统计、成长和检查点版本；成功返回保存时间，失败保留计数器脏状态。"""
        repo = self.repo
        with repo.transaction():
            previous = repo._conn.execute('SELECT * FROM tracking_checkpoint WHERE id=1').fetchone()
            if previous and previous['version'] >= checkpoint.version:
                return previous['saved_at']
            fields=('date','typed_chars','deleted_chars','valid_chars','total_tw','active_minutes','avg_tw','accuracy')
            now = datetime.fromisoformat(checkpoint.captured_at)
            for values in checkpoint.days:
                daily = dict(zip(fields,values))
                repo.upsert_daily(daily)
                self.ledger.typing(daily['date'],daily['valid_chars'],now)
            repo.upsert_lifetime(dict(checkpoint.lifetime))
            if checkpoint.minutes:
                repo.upsert_minutes(checkpoint.minutes)
            cleanup = now.date().isoformat()
            if not previous or previous['cleanup_day'] != cleanup:
                repo.clean_minute_stats((now-timedelta(days=30)).date().isoformat())
            saved_at = datetime.now().isoformat(timespec='seconds')
            repo._conn.execute('INSERT INTO tracking_checkpoint VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,saved_at=excluded.saved_at,cleanup_day=excluded.cleanup_day',
                               (checkpoint.version,saved_at,cleanup))
            repo.uow.changed('tracking',dict(version=checkpoint.version,saved_at=saved_at))
            return saved_at
