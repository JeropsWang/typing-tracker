"""Module-owned SQL; application UnitOfWork owns commit."""
from datetime import datetime
from ...storage.store import Store


class ProfileRepository(Store):
    def get_setting(self, key, default=None):
        row = self._conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_setting(self, key, value) -> None:
        self._conn.execute(
            'INSERT INTO settings(key,value) VALUES(?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            (key, str(value)))

    def set_settings(self, values: dict) -> None:
        """同一次设置提交原子写入，失败时保留原值。"""
        self._conn.executemany(
            'INSERT INTO settings(key,value) VALUES(?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            [(key, str(value)) for key, value in values.items()])

    def settings(self):
        return dict(self._conn.execute("SELECT key,value FROM settings"))
