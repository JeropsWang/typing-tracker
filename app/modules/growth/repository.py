"""Module-owned SQL; application UnitOfWork owns commit."""
from datetime import datetime
from ...storage.store import Store


class GrowthRepository(Store):
    def add_exp(self, amount) -> None:
        self._conn.execute('UPDATE lifetime SET total_exp = total_exp + ? WHERE id=1', (int(amount),))

    def get_exp(self) -> int:
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
        row = self._conn.execute('SELECT 1 FROM checkin_log WHERE date=?', (date,)).fetchone()
        return row is not None

    def get_streak(self, date) -> int:
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
        self._conn.execute(
            'INSERT INTO checkin_log(date,streak,base_exp,bonus_exp,card_used) '
            'VALUES(?,?,?,?,?) '
            'ON CONFLICT(date) DO UPDATE SET streak=excluded.streak',
            (date, streak, base_exp, bonus_exp, card_used))

    def get_achievements(self):
        rows = self._conn.execute('SELECT * FROM achievements').fetchall()
        return [dict(r) for r in rows]

    def get_achievement(self, code):
        row = self._conn.execute(
            'SELECT * FROM achievements WHERE code=?', (code,)).fetchone()
        return dict(row) if row else None

    def has_achievement(self, code) -> bool:
        row = self._conn.execute(
            'SELECT 1 FROM achievements WHERE code=?', (code,)).fetchone()
        return row is not None

    def unlock_achievement(self, code, unlocked_at) -> None:
        self._conn.execute(
            'INSERT OR IGNORE INTO achievements(code,unlocked_at,claimed) VALUES(?,?,0)',
            (code, unlocked_at))

    def set_claimed(self, code) -> None:
        self._conn.execute(
            'UPDATE achievements SET claimed=1 WHERE code=?', (code,))

    def add_reward(self, kind, qty, source, note=None) -> None:
        self._conn.execute(
            'INSERT INTO rewards(kind,qty,source,note,created_at) VALUES(?,?,?,?,?)',
            (kind, int(qty), source, note,
             datetime.now().isoformat(timespec='seconds')))

    def list_rewards(self, unused_only=False):
        sql = ('SELECT * FROM rewards WHERE used_at IS NULL'
               if unused_only else 'SELECT * FROM rewards')
        rows = self._conn.execute(sql + ' ORDER BY id').fetchall()
        return [dict(r) for r in rows]

    def use_reward(self, kind) -> bool:
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
        self._conn.executemany(
            'INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            [(key,str(value)) for key,value in values.items()])
