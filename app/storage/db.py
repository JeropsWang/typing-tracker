"""Versioned, atomic SQLite migrations with an online backup before upgrading."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from contextlib import closing
import sqlite3
import uuid

SCHEMA_PATH = Path(__file__).parent / 'schema.sql'
SCHEMA_VERSION = 2


def connect_db(db_path):
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=2)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=FULL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=2000')
    return conn


def _execute_schema(conn, source):
    # sqlite3.executescript implicitly commits, so do not use it in migrations.
    statement = ''
    for line in source.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ''
    if statement.strip() and not statement.lstrip().startswith('--'):
        conn.execute(statement)


def init_schema(conn):
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError('数据库版本高于当前程序，请使用更新版本。')
    if version == SCHEMA_VERSION:
        return
    if conn.in_transaction:
        raise RuntimeError('Schema migration requires an idle connection')
    path = conn.execute('PRAGMA database_list').fetchone()[2]
    existing = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone()
    if path and existing:
        directory = Path(path).parent / 'migration-backups'
        directory.mkdir(exist_ok=True)
        backup = directory / f'app-v{version}-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.db'
        with closing(sqlite3.connect(str(backup))) as target:
            conn.backup(target)
    conn.execute('BEGIN IMMEDIATE')
    try:
        if version < 1:
            _execute_schema(conn, SCHEMA_PATH.read_text(encoding='utf-8'))
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(rewards)')}
            if 'note' not in cols:
                conn.execute('ALTER TABLE rewards ADD COLUMN note TEXT')
            cols = {r['name'] for r in conn.execute('PRAGMA table_info(challenge_history)')}
            if 'score' not in cols:
                conn.execute('ALTER TABLE challenge_history ADD COLUMN score REAL NOT NULL DEFAULT 0')
            conn.execute('''CREATE TABLE IF NOT EXISTS keyboard_warrior_history (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                typed_chars INTEGER NOT NULL, tw REAL NOT NULL,
                elapsed_seconds REAL NOT NULL CHECK(elapsed_seconds = 15), speed REAL NOT NULL)''')
            from ..modules.english.repository import ensure_schema
            ensure_schema(conn)
            conn.execute('CREATE TABLE operations(kind TEXT NOT NULL, operation_id TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(kind,operation_id))')
            conn.execute('''CREATE TABLE growth_daily (
                date TEXT PRIMARY KEY, typing_blocks INTEGER NOT NULL DEFAULT 0,
                typing_exp INTEGER NOT NULL DEFAULT 0, challenge_exp INTEGER NOT NULL DEFAULT 0)''')
            settings = dict(conn.execute('SELECT key,value FROM settings'))
            for row in conn.execute('SELECT date,valid_chars FROM daily_stats').fetchall():
                blocks = row['valid_chars'] // 1000
                used = 0
                if settings.get('typing_exp_date') == row['date']:
                    blocks = max(blocks, int(settings.get('typing_exp_blocks', '0') or 0))
                    used = int(settings.get('typing_exp_today', '0') or 0)
                challenge = int(settings.get('challenge_exp_today', '0') or 0) if settings.get('challenge_exp_date') == row['date'] else 0
                conn.execute('INSERT INTO growth_daily VALUES(?,?,?,?)', (row['date'], blocks, used, challenge))
            # A reward may have been committed before the first statistics row in older versions.
            for key in ('typing_exp_date', 'challenge_exp_date'):
                day = settings.get(key)
                if day:
                    conn.execute('INSERT OR IGNORE INTO growth_daily(date) VALUES(?)', (day,))
                    if key == 'typing_exp_date':
                        conn.execute('UPDATE growth_daily SET typing_blocks=MAX(typing_blocks,?),typing_exp=MAX(typing_exp,?) WHERE date=?',
                                     (int(settings.get('typing_exp_blocks', '0') or 0), int(settings.get('typing_exp_today', '0') or 0), day))
                    else:
                        conn.execute('UPDATE growth_daily SET challenge_exp=MAX(challenge_exp,?) WHERE date=?',
                                     (int(settings.get('challenge_exp_today', '0') or 0), day))
            conn.execute('CREATE TABLE tracking_checkpoint(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, saved_at TEXT NOT NULL, cleanup_day TEXT)')
        if version < 2:
            from ..modules.english.repository import migrate_review_schema
            from ..modules.tracking.api import AppCalendar
            setting = conn.execute("SELECT value FROM settings WHERE key='day_start_hour'").fetchone()
            day = AppCalendar(int(setting[0]) if setting else 4).day(datetime.now())
            migrate_review_schema(conn, day)
        conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
