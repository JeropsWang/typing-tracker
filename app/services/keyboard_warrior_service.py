"""Local keyboard-warrior history; no text or practice rewards are stored."""
from datetime import datetime


class KeyboardWarriorService:
    def __init__(self, repo):
        self._repo = repo

    def record(self, session):
        result = session.result()
        if not result['typed_chars']:
            return False
        return self._repo.add_keyboard_warrior(result, datetime.now().isoformat(timespec='seconds'))

    def leaderboard(self, limit=10):
        return self._repo.keyboard_warrior_leaderboard(limit)
