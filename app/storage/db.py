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
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：老库补列。"""
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(rewards)')}
    if 'note' not in cols:
        conn.execute('ALTER TABLE rewards ADD COLUMN note TEXT')
