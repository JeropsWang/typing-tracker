"""SQLite 数据访问（Repository）。"""
from __future__ import annotations

import sqlite3
from datetime import datetime


class Repository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @property
    def english(self):
        from ..english.repository import EnglishRepository
        return EnglishRepository(self._conn)

    def add_keyboard_warrior(self, result, created_at):
        with self._conn:
            cursor = self._conn.execute(
                'INSERT OR IGNORE INTO keyboard_warrior_history '
                '(id,created_at,typed_chars,tw,elapsed_seconds,speed) VALUES(?,?,?,?,?,?)',
                (result['id'], created_at, result['typed_chars'], result['tw'],
                 result['elapsed_seconds'], result['speed']))
        return cursor.rowcount > 0

    def keyboard_warrior_leaderboard(self, limit=10):
        rows = self._conn.execute(
            'SELECT * FROM keyboard_warrior_history ORDER BY speed DESC, created_at ASC, id ASC LIMIT ?',
            (max(1, min(int(limit), 100)),)).fetchall()
        return [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]

    # ---------- settings ----------
    def get_setting(self, key, default=None):
        row = self._conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value) -> None:
        self._conn.execute(
            'INSERT INTO settings(key,value) VALUES(?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, str(value)))
        self._conn.commit()

    # ---------- lifetime ----------
    def set_settings(self, values: dict) -> None:
        """同一次设置提交原子写入，失败时保留原值。"""
        with self._conn:
            self._conn.executemany(
                'INSERT INTO settings(key,value) VALUES(?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                [(key, str(value)) for key, value in values.items()])

    def get_lifetime(self):
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
        self._conn.commit()

    def add_exp(self, amount) -> None:
        self._conn.execute('UPDATE lifetime SET total_exp = total_exp + ? WHERE id=1', (int(amount),))
        self._conn.commit()

    def get_exp(self) -> int:
        row = self._conn.execute('SELECT total_exp FROM lifetime WHERE id=1').fetchone()
        return row['total_exp'] if row else 0

    # ---------- daily ----------
    def upsert_daily(self, d) -> None:
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
        self._conn.commit()

    def add_exp_to_daily(self, date, amount) -> None:
        """把经验累加进当日记录；当日行不存在时先建行（如启动即打卡、尚未打字）。"""
        self._conn.execute(
            'INSERT INTO daily_stats(date,typed_chars,deleted_chars,valid_chars,total_tw,'
            'active_minutes,avg_tw,accuracy,exp_gained) VALUES(?,0,0,0,0,0,NULL,NULL,?) '
            'ON CONFLICT(date) DO UPDATE SET exp_gained = exp_gained + excluded.exp_gained',
            (date, int(amount)))
        self._conn.commit()

    def get_daily(self, date):
        row = self._conn.execute('SELECT * FROM daily_stats WHERE date=?', (date,)).fetchone()
        return dict(row) if row else None

    def get_recent_days(self, n):
        rows = self._conn.execute(
            'SELECT * FROM daily_stats ORDER BY date DESC LIMIT ?', (n,)).fetchall()
        return [dict(r) for r in rows]

    # ---------- minute ----------
    def get_minutes(self, date):
        """读取指定应用日的分钟快照，供启动恢复和同分钟续写使用。"""
        rows = self._conn.execute(
            'SELECT * FROM minute_stats WHERE date=? ORDER BY minute', (date,)).fetchall()
        return [dict(r) for r in rows]

    def clean_minute_stats(self, before_date: str) -> None:
        """删除指定日期之前的分钟数据（滚动保留策略）。"""
        self._conn.execute(
            'DELETE FROM minute_stats WHERE date < ?', (before_date,))
        self._conn.commit()

    def upsert_minutes(self, rows) -> None:
        self._conn.executemany(
            'INSERT INTO minute_stats(date,minute,typed_chars,deleted_chars,total_tw) '
            'VALUES(?,?,?,?,?) '
            'ON CONFLICT(date,minute) DO UPDATE SET '
            'typed_chars=excluded.typed_chars, deleted_chars=excluded.deleted_chars, '
            'total_tw=excluded.total_tw',
            rows)
        self._conn.commit()

    # ---------- checkin ----------
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
        self._conn.commit()

    # ---------- 成就（M3） ----------
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
        self._conn.commit()

    def set_claimed(self, code) -> None:
        self._conn.execute(
            'UPDATE achievements SET claimed=1 WHERE code=?', (code,))
        self._conn.commit()

    def get_minute_quality(self, start, end, min_typed=30):
        """有效分钟样本：输入 ≥ min_typed 的分钟（用于每分钟正确率成就）。"""
        rows = self._conn.execute(
            'SELECT date, minute, typed_chars, deleted_chars FROM minute_stats '
            'WHERE date BETWEEN ? AND ? AND typed_chars >= ?',
            (start, end, min_typed)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 道具（M3） ----------
    def add_reward(self, kind, qty, source, note=None) -> None:
        self._conn.execute(
            'INSERT INTO rewards(kind,qty,source,note,created_at) VALUES(?,?,?,?,?)',
            (kind, int(qty), source, note,
             datetime.now().isoformat(timespec='seconds')))
        self._conn.commit()

    def list_rewards(self, unused_only=False):
        sql = ('SELECT * FROM rewards WHERE used_at IS NULL'
               if unused_only else 'SELECT * FROM rewards')
        rows = self._conn.execute(sql + ' ORDER BY id').fetchall()
        return [dict(r) for r in rows]

    def use_reward(self, kind) -> bool:
        """使用一张指定类型的未用道具；成功返回 True。"""
        row = self._conn.execute(
            'SELECT id FROM rewards WHERE kind=? AND used_at IS NULL '
            'ORDER BY id LIMIT 1', (kind,)).fetchone()
        if not row:
            return False
        self._conn.execute(
            'UPDATE rewards SET used_at=? WHERE id=?',
            (datetime.now().isoformat(timespec='seconds'), row['id']))
        self._conn.commit()
        return True

    def count_ai_passes(self) -> int:
        """AI 训练券数量（未使用，SQL 聚合而非全表扫描）。"""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(qty),0) AS n FROM rewards "
            "WHERE kind='ai_pass' AND used_at IS NULL").fetchone()
        return int(row['n'] or 0)

    # ---------- 打字竞速挑战（0.7） ----------
    def add_challenge(self, started_at, text_id, typed_chars, errors,
                      elapsed_seconds, tw, accuracy, best, score_points=0) -> None:
        self._conn.execute(
            'INSERT INTO challenge_history(started_at,text_id,typed_chars,errors,'
            'elapsed_seconds,tw,accuracy,best,score) VALUES(?,?,?,?,?,?,?,?,?)',
            (started_at, text_id, typed_chars, errors,
             elapsed_seconds, tw, accuracy, int(best), float(score_points)))
        self._conn.commit()

    def get_best_challenge(self, text_id):
        row = self._conn.execute(
            'SELECT * FROM challenge_history WHERE text_id=? '
            'ORDER BY best DESC, accuracy DESC LIMIT 1', (text_id,)).fetchone()
        return dict(row) if row else None

    def get_recent_challenges(self, n=10):
        rows = self._conn.execute(
            'SELECT * FROM challenge_history ORDER BY id DESC LIMIT ?',
            (n,)).fetchall()
        return [dict(r) for r in rows]

    def get_challenge_leaderboard(self, text_id, n=10):
        """同篇范文的完整计分记录；best 是累积纪录，不能用来排序单次成绩。"""
        limit = max(1, min(50, int(n)))
        rows = self._conn.execute(
            'SELECT * FROM challenge_history WHERE text_id=? AND score>0 '
            'AND elapsed_seconds>0 ORDER BY score DESC, accuracy DESC, '
            'elapsed_seconds ASC, id DESC LIMIT ?', (text_id, limit)).fetchall()
        return [dict(row) for row in rows]

    # ---------- AI 生成范文（0.8） ----------
    def add_ai_text(self, lang, topic, text) -> int:
        cur = self._conn.execute(
            'INSERT INTO ai_texts(created_at,lang,topic,text) VALUES(?,?,?,?)',
            (datetime.now().isoformat(timespec='seconds'), lang, topic, text))
        self._conn.commit()
        return cur.lastrowid

    def list_ai_texts(self):
        rows = self._conn.execute(
            'SELECT * FROM ai_texts ORDER BY id DESC').fetchall()
        return [dict(r) for r in rows]

    def delete_ai_text(self, text_id) -> None:
        self._conn.execute('DELETE FROM ai_texts WHERE id=?', (text_id,))
        self._conn.commit()

    # ---------- 报表查询（M2） ----------
    def get_daily_range(self, start, end):
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

    def close(self) -> None:
        self._conn.close()
