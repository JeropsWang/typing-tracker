"""Module-owned SQL; application UnitOfWork owns commit."""
from datetime import datetime
from ...storage.store import Store


class GrowthRepository(Store):
    """成长数据的工作线程 SQL 仓储，负责经验、打卡、成就和库存；外层事务统一提交。"""
    def add_exp(self, amount) -> None:
        """累加终身经验，不覆盖统计模块的计数字段。"""
        self._conn.execute('UPDATE lifetime SET total_exp = total_exp + ? WHERE id=1', (int(amount),))

    def get_exp(self) -> int:
        """读取终身经验，尚无终身行时返回零。"""
        row = self._conn.execute('SELECT total_exp FROM lifetime WHERE id=1').fetchone()
        return row['total_exp'] if row else 0

    def add_exp_to_daily(self, date, amount) -> None:
        """把经验累加进当日记录；当日行不存在时先建行（如启动即打卡、尚未打字）。"""
        self._conn.execute(
            'INSERT INTO daily_stats(date,typed_chars,deleted_chars,valid_chars,total_tw,'
            'active_minutes,avg_tw,accuracy,exp_gained) VALUES(?,0,0,0,0,0,NULL,NULL,?) '
            'ON CONFLICT(date) DO UPDATE SET exp_gained = exp_gained + excluded.exp_gained',
            (date, int(amount)))

    def has_checkin(self, date) -> bool:
        """查询指定应用日是否已有打卡记录。"""
        row = self._conn.execute('SELECT 1 FROM checkin_log WHERE date=?', (date,)).fetchone()
        return row is not None

    def get_streak(self, date) -> int:
        """读取指定日期记录的连续打卡天数，无记录时为零。"""
        row = self._conn.execute('SELECT streak FROM checkin_log WHERE date=?', (date,)).fetchone()
        return row['streak'] if row else 0

    def get_checkins(self, start, end):
        """打卡月历数据：{date: {streak, base_exp, bonus_exp, card_used}}。"""
        rows = self._conn.execute(
            'SELECT date, streak, base_exp, bonus_exp, card_used '
            'FROM checkin_log WHERE date BETWEEN ? AND ? ORDER BY date',
            (start, end)).fetchall()
        return {r['date']: dict(r) for r in rows}

    def add_checkin(self, date, streak, base_exp, bonus_exp, card_used=0) -> None:
        """新增打卡奖励记录；同日期重写只更新连签，不重复覆盖已发奖励。"""
        self._conn.execute(
            'INSERT INTO checkin_log(date,streak,base_exp,bonus_exp,card_used) '
            'VALUES(?,?,?,?,?) '
            'ON CONFLICT(date) DO UPDATE SET streak=excluded.streak',
            (date, streak, base_exp, bonus_exp, card_used))

    def get_achievements(self):
        """读取成就解锁/领取状态，返回独立行字典列表。"""
        rows = self._conn.execute('SELECT * FROM achievements').fetchall()
        return [dict(r) for r in rows]

    def get_achievement(self, code):
        """按成就代码取得状态，无记录返回 None。"""
        row = self._conn.execute(
            'SELECT * FROM achievements WHERE code=?', (code,)).fetchone()
        return dict(row) if row else None

    def has_achievement(self, code) -> bool:
        """判断成就代码是否已有解锁记录。"""
        row = self._conn.execute(
            'SELECT 1 FROM achievements WHERE code=?', (code,)).fetchone()
        return row is not None

    def unlock_achievement(self, code, unlocked_at) -> None:
        """幂等插入解锁记录，不覆盖已有领取状态。"""
        self._conn.execute(
            'INSERT OR IGNORE INTO achievements(code,unlocked_at,claimed) VALUES(?,?,0)',
            (code, unlocked_at))

    def set_claimed(self, code) -> None:
        """标记已领取成就；与奖励发放处于同一外层事务。"""
        self._conn.execute(
            'UPDATE achievements SET claimed=1 WHERE code=?', (code,))

    def add_reward(self, kind, qty, source, note=None) -> None:
        """追加有数量、来源和可选称号说明的奖励库存记录。"""
        self._conn.execute(
            'INSERT INTO rewards(kind,qty,source,note,created_at) VALUES(?,?,?,?,?)',
            (kind, int(qty), source, note,
             datetime.now().isoformat(timespec='seconds')))

    def list_rewards(self, unused_only=False):
        """按 ID 返回奖励库存，可仅筛选未使用记录。"""
        sql = ('SELECT * FROM rewards WHERE used_at IS NULL'
               if unused_only else 'SELECT * FROM rewards')
        rows = self._conn.execute(sql + ' ORDER BY id').fetchall()
        return [dict(r) for r in rows]

    def use_reward(self, kind) -> bool:
        """消费最早的一份指定奖励，多数量记录只减一，无库存返回 False。"""
        row = self._conn.execute(
            'SELECT id,qty FROM rewards WHERE kind=? AND used_at IS NULL AND qty>0 ORDER BY id LIMIT 1',
            (kind,)).fetchone()
        if not row:
            return False
        if row['qty'] > 1:
            self._conn.execute('UPDATE rewards SET qty=qty-1 WHERE id=?', (row['id'],))
        else:
            self._conn.execute('UPDATE rewards SET used_at=? WHERE id=?',
                               (datetime.now().isoformat(timespec='seconds'), row['id']))
        return True

    def count_ai_passes(self) -> int:
        """AI 训练券数量（未使用，SQL 聚合而非全表扫描）。"""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(qty),0) AS n FROM rewards "
            "WHERE kind='ai_pass' AND used_at IS NULL").fetchone()
        return int(row['n'] or 0)

    def set_state_settings(self,values):
        """批量更新成长状态兼容键，不在仓储内部提交事务。"""
        self._conn.executemany(
            'INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            [(key,str(value)) for key,value in values.items()])
