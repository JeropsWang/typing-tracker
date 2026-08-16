"""打字竞速挑战服务：记录成绩 / 查询最佳 / 近期历史。"""
from __future__ import annotations

from datetime import datetime


class ChallengeService:
    def __init__(self, repo):
        self._repo = repo

    def record(self, text_id: str, result: dict, balance=None) -> dict:
        """记录一次成绩，返回 (记录, 是否新纪录, 更新前最佳)。"""
        prev = self._repo.get_best_challenge(text_id)
        best = prev['best'] or 0 if prev else 0
        prev_best = best
        is_best = result['tw'] > best
        if is_best:
            best = int(result['tw'])
        self._repo.add_challenge(
            datetime.now().isoformat(timespec='seconds'),
            text_id, result['typed_chars'], result['errors'],
            result.get('elapsed_seconds', 0), result['tw'],
            result['accuracy'], best)
        return {'record': result, 'is_best': is_best, 'prev_best': prev_best}

    def best(self, text_id: str):
        return self._repo.get_best_challenge(text_id)

    def recent(self, n: int = 8):
        return self._repo.get_recent_challenges(n)
