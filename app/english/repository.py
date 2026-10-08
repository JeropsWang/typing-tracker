"""英语模块 SQLite 边界；学习结果、进度和生成材料独立存储。"""
from datetime import datetime
import json
from .catalog import DECKS


def ensure_schema(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS english_attempts (
          id TEXT PRIMARY KEY, deck TEXT NOT NULL, word TEXT NOT NULL,
          mode TEXT NOT NULL, correct INTEGER NOT NULL, assisted INTEGER NOT NULL,
          accuracy REAL NOT NULL, elapsed REAL NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS english_attempts_deck ON english_attempts(deck,mode,created_at);
        CREATE TABLE IF NOT EXISTS english_progress (
          deck TEXT NOT NULL, word TEXT NOT NULL, attempts INTEGER NOT NULL,
          independent_correct INTEGER NOT NULL, wrong INTEGER NOT NULL,
          needs_review INTEGER NOT NULL, last_at TEXT NOT NULL,
          PRIMARY KEY(deck,word)
        );
        CREATE TABLE IF NOT EXISTS english_sentences (
          id INTEGER PRIMARY KEY AUTOINCREMENT, deck TEXT NOT NULL,
          topic TEXT NOT NULL, words_json TEXT NOT NULL, sentences_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
    ''')


class EnglishRepository:
    def __init__(self, conn):
        self._conn = conn

    def record_attempt(self, event):
        if event['deck'] not in DECKS or event['mode'] not in ('spelling', 'sentence'):
            raise ValueError('练习记录类型无效。')
        correct, assisted = bool(event['correct']), bool(event['assisted'])
        word_key = event['word'].strip().casefold()
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn:
            cursor = self._conn.execute(
                'INSERT OR IGNORE INTO english_attempts VALUES(?,?,?,?,?,?,?,?,?)',
                (event['id'], event['deck'], word_key, event['mode'], int(correct),
                 int(assisted), float(event.get('accuracy', correct)),
                 max(0, float(event['elapsed'])), now))
            if not cursor.rowcount:
                return False
            if event['mode'] == 'spelling':
                independent = int(correct and not assisted)
                self._conn.execute('''
                    INSERT INTO english_progress VALUES(?,?,1,?,?,?,?)
                    ON CONFLICT(deck,word) DO UPDATE SET
                    attempts=attempts+1, independent_correct=independent_correct+excluded.independent_correct,
                    wrong=wrong+excluded.wrong, needs_review=excluded.needs_review, last_at=excluded.last_at
                ''', (event['deck'], word_key, independent, int(not correct), 1-independent, now))
        return True

    def review_keys(self, deck):
        return {r['word'] for r in self._conn.execute(
            'SELECT word FROM english_progress WHERE deck=? AND needs_review=1', (deck,))}

    def summary(self, deck):
        row = self._conn.execute('''SELECT COUNT(*) AS trained,
            COALESCE(SUM(attempts),0) AS attempts,
            COALESCE(SUM(independent_correct),0) AS independent_correct,
            COALESCE(SUM(needs_review),0) AS review_count
            FROM english_progress WHERE deck=?''', (deck,)).fetchone()
        result = dict(row)
        result['accuracy'] = result['independent_correct'] / result['attempts'] if result['attempts'] else None
        return result

    def save_sentences(self, deck, topic, words, sentences, *, spend_pass=False):
        now = datetime.now().isoformat(timespec='seconds')
        with self._conn:
            if spend_pass:
                reward = self._conn.execute("SELECT id,qty FROM rewards WHERE kind='ai_pass' "
                    'AND used_at IS NULL AND qty>0 ORDER BY id LIMIT 1').fetchone()
                if reward is None:
                    raise ValueError('AI 训练券不足，生成内容未保存。')
                if reward['qty'] > 1:
                    self._conn.execute('UPDATE rewards SET qty=qty-1 WHERE id=?', (reward['id'],))
                else:
                    self._conn.execute('UPDATE rewards SET used_at=? WHERE id=?', (now, reward['id']))
            cursor = self._conn.execute('INSERT INTO english_sentences '
                '(deck,topic,words_json,sentences_json,created_at) VALUES(?,?,?,?,?)',
                (deck, topic, json.dumps(words, ensure_ascii=False),
                 json.dumps(sentences, ensure_ascii=False), now))
            return cursor.lastrowid

    def sentence_history(self, deck, limit=20):
        rows = self._conn.execute('SELECT * FROM english_sentences WHERE deck=? '
            'ORDER BY id DESC LIMIT ?', (deck, max(1, min(100, int(limit))))).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['words'] = json.loads(item.pop('words_json'))
            item['sentences'] = json.loads(item.pop('sentences_json'))
            result.append(item)
        return result

    def export(self):
        return {key: [dict(r) for r in self._conn.execute(f'SELECT * FROM {table}')]
                for key, table in (('attempts', 'english_attempts'),
                                   ('progress', 'english_progress'), ('sentences', 'english_sentences'))}
