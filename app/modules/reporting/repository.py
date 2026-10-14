"""Module-owned SQL; application UnitOfWork owns commit."""
from datetime import datetime
from ...storage.store import Store


class ReportingRepository(Store):
    """仅查询统计数据的工作线程仓储，不发奖励或修改业务记录。"""
    def get_daily_range(self, start, end):
        """读取包含起止日期的日统计范围，按日期升序返回行副本。"""
        rows = self._conn.execute(
            'SELECT * FROM daily_stats WHERE date BETWEEN ? AND ? ORDER BY date ASC',
            (start, end)).fetchall()
        return [dict(r) for r in rows]

    def get_heatmap(self, start, end):
        """打卡热力图数据：{date: total_tw}。"""
        rows = self._conn.execute(
            'SELECT date, total_tw FROM daily_stats WHERE date BETWEEN ? AND ?',
            (start, end)).fetchall()
        return {r['date']: r['total_tw'] for r in rows}

    def get_hourly_stats(self, start, end):
        """时段分布：按小时聚合 minute_stats。"""
        rows = self._conn.execute(
            'SELECT substr(minute,1,2) AS hour, SUM(typed_chars) AS typed, '
            'SUM(deleted_chars) AS deleted, SUM(total_tw) AS tw '
            'FROM minute_stats WHERE date BETWEEN ? AND ? '
            'GROUP BY hour ORDER BY hour',
            (start, end)).fetchall()
        return [dict(r) for r in rows]

    def get_summary(self, start, end):
        """区间汇总：总量 + 期间均速（tw/活跃分钟）+ 期间正确率。"""
        row = self._conn.execute(
            'SELECT COALESCE(SUM(typed_chars),0) AS typed, '
            'COALESCE(SUM(deleted_chars),0) AS deleted, '
            'COALESCE(SUM(valid_chars),0) AS valid, '
            'COALESCE(SUM(total_tw),0) AS tw, '
            'COALESCE(SUM(active_minutes),0) AS minutes, '
            'COALESCE(SUM(total_tw),0) * 1.0 / NULLIF(SUM(active_minutes),0) AS avg_speed, '
            'COALESCE(SUM(valid_chars),0) * 1.0 / NULLIF(SUM(typed_chars),0) AS accuracy '
            'FROM daily_stats WHERE date BETWEEN ? AND ?',
            (start, end)).fetchone()
        return dict(row) if row else None

    def get_minute_quality(self, start, end, min_typed=30):
        """有效分钟样本：输入 ≥ min_typed 的分钟（用于每分钟正确率成就）。"""
        rows = self._conn.execute(
            'SELECT date, minute, typed_chars, deleted_chars FROM minute_stats '
            'WHERE date BETWEEN ? AND ? AND typed_chars >= ?',
            (start, end, min_typed)).fetchall()
        return [dict(r) for r in rows]
