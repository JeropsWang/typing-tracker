"""SQLite 连接与初始化。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / 'schema.sql'


def connect_db(db_path) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding='utf-8'))
    _migrate(conn)
    conn.execute('''CREATE TABLE IF NOT EXISTS keyboard_warrior_history (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
        typed_chars INTEGER NOT NULL, tw REAL NOT NULL,
        elapsed_seconds REAL NOT NULL CHECK(elapsed_seconds = 15), speed REAL NOT NULL
    )''')
    from ..english.repository import ensure_schema
    ensure_schema(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：老库补列/补表。"""
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(rewards)')}
    if 'note' not in cols:
        conn.execute('ALTER TABLE rewards ADD COLUMN note TEXT')
    tables = {r['name'] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if 'challenge_history' not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS challenge_history (
              id              INTEGER PRIMARY KEY AUTOINCREMENT,
              started_at      TEXT NOT NULL,
              text_id         TEXT NOT NULL,
              typed_chars     INTEGER NOT NULL DEFAULT 0,
              errors          INTEGER NOT NULL DEFAULT 0,
              elapsed_seconds REAL NOT NULL DEFAULT 0,
              tw              REAL NOT NULL DEFAULT 0,
              accuracy        REAL NOT NULL DEFAULT 0,
              best            INTEGER NOT NULL DEFAULT 0
            );""")
    if 'ai_texts' not in tables:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS ai_texts (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at TEXT NOT NULL,
              lang       TEXT NOT NULL,
              topic      TEXT NOT NULL,
              text       TEXT NOT NULL
            );""")
    if 'challenge_history' in tables:
        cols = {r['name'] for r in conn.execute('PRAGMA table_info(challenge_history)')}
        if 'score' not in cols:
            conn.execute('ALTER TABLE challenge_history ADD COLUMN score REAL NOT NULL DEFAULT 0')
