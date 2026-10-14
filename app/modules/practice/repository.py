"""Module-owned SQL; application UnitOfWork owns commit."""
from datetime import datetime
from ...storage.store import Store


class PracticeRepository(Store):
    """工作线程中的训练记录/材料 SQL 仓储，提交权属于外层 UnitOfWork。"""
    def add_keyboard_warrior(self, result, created_at):
        """按会话 ID 幂等插入键盘侠记录，返回是否新增。"""
        cursor = self._conn.execute(
            'INSERT OR IGNORE INTO keyboard_warrior_history '
            '(id,created_at,typed_chars,tw,elapsed_seconds,speed) VALUES(?,?,?,?,?,?)',
            (result['id'], created_at, result['typed_chars'], result['tw'],
             result['elapsed_seconds'], result['speed']))
        return cursor.rowcount > 0

    def keyboard_warrior_leaderboard(self, limit=10):
        """按速度及稳定时间/ID 顺序查询有界排行榜，并附一开始的名次。"""
        rows = self._conn.execute(
            'SELECT * FROM keyboard_warrior_history ORDER BY speed DESC, created_at ASC, id ASC LIMIT ?',
            (max(1, min(int(limit), 100)),)).fetchall()
        return [dict(row, rank=rank) for rank, row in enumerate(rows, 1)]

    def add_challenge(self, started_at, text_id, typed_chars, errors,
                      elapsed_seconds, tw, accuracy, best, score_points=0) -> None:
        """写入单次训练数值及纪录/评分标记，不保存被动输入正文。"""
        self._conn.execute(
            'INSERT INTO challenge_history(started_at,text_id,typed_chars,errors,'
            'elapsed_seconds,tw,accuracy,best,score) VALUES(?,?,?,?,?,?,?,?,?)',
            (started_at, text_id, typed_chars, errors,
             elapsed_seconds, tw, accuracy, int(best), float(score_points)))

    def get_best_challenge(self, text_id):
        """查询同范文的最佳纪录比较基线，无记录返回 None。"""
        row = self._conn.execute(
            'SELECT * FROM challenge_history WHERE text_id=? '
            'ORDER BY best DESC, accuracy DESC LIMIT 1', (text_id,)).fetchone()
        return dict(row) if row else None

    def get_recent_challenges(self, n=10):
        """按记录 ID 倒序读取最近训练历史。"""
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

    def add_ai_text(self, lang, topic, text) -> int:
        """保存用户主动生成的训练材料及主题，返回新材料 ID。"""
        cur = self._conn.execute(
            'INSERT INTO ai_texts(created_at,lang,topic,text) VALUES(?,?,?,?)',
            (datetime.now().isoformat(timespec='seconds'), lang, topic, text))
        return cur.lastrowid

    def list_ai_texts(self):
        """按 ID 倒序读取已保存 AI 训练材料。"""
        rows = self._conn.execute(
            'SELECT * FROM ai_texts ORDER BY id DESC').fetchall()
        return [dict(r) for r in rows]

    def delete_ai_text(self, text_id) -> None:
        """删除指定主动生成的材料，事务提交由调用方负责。"""
        self._conn.execute('DELETE FROM ai_texts WHERE id=?', (text_id,))
