"""英语模块 SQLite 边界；学习结果、进度和生成材料独立存储。"""
from datetime import datetime
import json
from .catalog import DECKS
from .review import next_schedule, review_plan
from ..tracking.api import AppCalendar


def ensure_schema(conn):
    _schema = '''
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
    '''
    for statement in _schema.split(';'):
        if statement.strip():
            conn.execute(statement)


def migrate_review_schema(conn, day):
    """Version 2 only; preserve the version 1 schema and learning history."""
    from datetime import date, timedelta
    conn.execute('''CREATE TABLE english_review_schedule (
        deck TEXT NOT NULL, word TEXT NOT NULL, stage INTEGER NOT NULL CHECK(stage BETWEEN 0 AND 5),
        due_day TEXT NOT NULL, last_success_day TEXT, PRIMARY KEY(deck,word))''')
    conn.execute('CREATE INDEX english_review_due ON english_review_schedule(deck,due_day,word)')
    tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    conn.execute('''INSERT INTO english_review_schedule(deck,word,stage,due_day)
        SELECT deck,word,CASE WHEN needs_review=1 THEN 0 ELSE 1 END,
            CASE WHEN needs_review=1 THEN ? ELSE ? END FROM english_progress''', (day, tomorrow))


class EnglishRepository:
    def __init__(self, conn, uow=None):
        from ...storage.unit_of_work import UnitOfWork
        self._conn = conn
        self.uow = uow or UnitOfWork(conn)

    def record_attempt(self, event):
        if event['deck'] not in DECKS or event['mode'] not in ('spelling', 'sentence'):
            raise ValueError('练习记录类型无效。')
        correct, assisted = bool(event['correct']), bool(event['assisted'])
        word_key = event['word'].strip().casefold()
        now = datetime.now().isoformat(timespec='seconds')
        with self.uow.transaction():
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
                previous = self._conn.execute('SELECT * FROM english_review_schedule WHERE deck=? AND word=?',
                                              (event['deck'], word_key)).fetchone()
                day = event.get('app_day') or AppCalendar().day(datetime.now())
                schedule = next_schedule(dict(previous) if previous else None, day=day,
                    independent=bool(independent), due_review=event.get('due_review', False),
                    retest=event.get('retest', False))
                self._conn.execute('''INSERT INTO english_review_schedule VALUES(?,?,?,?,?)
                    ON CONFLICT(deck,word) DO UPDATE SET stage=excluded.stage,
                    due_day=excluded.due_day,last_success_day=excluded.last_success_day''',
                    (event['deck'], word_key, schedule['stage'], schedule['due_day'], schedule['last_success_day']))
        return True

    def review_keys(self, deck):
        return {r['word'] for r in self._conn.execute(
            'SELECT word FROM english_progress WHERE deck=? AND needs_review=1', (deck,))}

    def review_plan(self, deck, day):
        return review_plan(self._conn.execute('SELECT * FROM english_review_schedule WHERE deck=?',
                                             (deck,)), deck, day)

    def summary(self, deck):
        row = self._conn.execute('''SELECT COUNT(*) AS trained,
            COALESCE(SUM(attempts),0) AS attempts,
            COALESCE(SUM(independent_correct),0) AS independent_correct,
            COALESCE(SUM(needs_review),0) AS review_count
            FROM english_progress WHERE deck=?''', (deck,)).fetchone()
        result = dict(row)
        result['accuracy'] = result['independent_correct'] / result['attempts'] if result['attempts'] else None
        return result

    def save_sentences(self, deck, topic, words, sentences):
        now = datetime.now().isoformat(timespec='seconds')
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
                                   ('progress', 'english_progress'), ('sentences', 'english_sentences'),
                                   ('review_schedule', 'english_review_schedule'))}
