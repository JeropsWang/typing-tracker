"""Module-owned SQL; application UnitOfWork owns commit."""
from datetime import datetime
from ...storage.store import Store


class TrackingRepository(Store):
    """统计模块拥有的数值 SQL 仓储；仅使用应用线程连接，不覆盖成长统计列。"""
    def get_lifetime(self):
        """读取终身统计行并转为独立字典，不存在时返回 None。"""
        row = self._conn.execute('SELECT * FROM lifetime WHERE id=1').fetchone()
        return dict(row) if row else None

    def upsert_lifetime(self, life) -> None:
        """只更新总量类字段，total_exp 由 add_exp 单独维护。"""
        self._conn.execute(
            'INSERT INTO lifetime(id,total_typed,total_deleted,total_tw,total_active_minutes,total_exp) '
            'VALUES(1,?,?,?,?,0) '
            'ON CONFLICT(id) DO UPDATE SET '
            'total_typed=excluded.total_typed, total_deleted=excluded.total_deleted, '
            'total_tw=excluded.total_tw, total_active_minutes=excluded.total_active_minutes',
            (life['total_typed'], life['total_deleted'],
             life['total_tw'], life['total_active_minutes']))

    def upsert_daily(self, d) -> None:
        """写入当日计数列，保留成长模块拥有的 exp_gained。"""
        self._conn.execute(
            'INSERT INTO daily_stats(date,typed_chars,deleted_chars,valid_chars,total_tw,'
            'active_minutes,avg_tw,accuracy,exp_gained) '
            'VALUES(:date,:typed_chars,:deleted_chars,:valid_chars,:total_tw,'
            ':active_minutes,:avg_tw,:accuracy,0) '
            'ON CONFLICT(date) DO UPDATE SET '
            'typed_chars=excluded.typed_chars, deleted_chars=excluded.deleted_chars, '
            'valid_chars=excluded.valid_chars, total_tw=excluded.total_tw, '
            'active_minutes=excluded.active_minutes, avg_tw=excluded.avg_tw, '
            'accuracy=excluded.accuracy',
            d)

    def get_daily(self, date):
        """按应用日期读取日统计副本，不存在时返回 None。"""
        row = self._conn.execute('SELECT * FROM daily_stats WHERE date=?', (date,)).fetchone()
        return dict(row) if row else None

    def get_recent_days(self, n):
        """按日期倒序读取有界日统计，供恢复和报表使用。"""
        rows = self._conn.execute(
            'SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?', (n,)).fetchall()
        return [dict(r) for r in rows]

    def get_minutes(self, date):
        """读取指定应用日的分钟快照，供启动恢复和同分钟续写使用。"""
        rows = self._conn.execute(
            'SELECT * FROM minute_stats WHERE date=? ORDER BY minute', (date,)).fetchall()
        return [dict(r) for r in rows]

    def clean_minute_stats(self, before_date: str) -> None:
        """删除指定日期之前的分钟数据（滚动保留策略）。"""
        self._conn.execute(
            'DELETE FROM minute_stats WHERE date < ?', (before_date,))

    def upsert_minutes(self, rows) -> None:
        """批量写入日期/分钟检查点数值，事务由外层 UnitOfWork 统一提交。"""
        self._conn.executemany(
            'INSERT INTO minute_stats(date,minute,typed_chars,deleted_chars,total_tw) '
            'VALUES(?,?,?,?,?) '
            'ON CONFLICT(date,minute) DO UPDATE SET '
            'typed_chars=excluded.typed_chars, deleted_chars=excluded.deleted_chars, '
            'total_tw=excluded.total_tw',
            rows)
