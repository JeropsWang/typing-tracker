"""打字竞速挑战服务：记录成绩 / 查询最佳 / 经验奖励（挑战分 → 等级经验）。"""
from __future__ import annotations

from datetime import date, datetime, timedelta


class ChallengeService:
    def __init__(self, repo):
        self._repo = repo

    def _app_day(self) -> str:
        """按应用的日切起点归属日期（曾用 date.today()，00:00-04:00 窗口
        上限提前重置、经验归错日，v0.8.9 修复）。"""
        h = int(self._repo.get_setting('day_start_hour', '4') or 4)
        return (datetime.now() - timedelta(hours=h)).date().isoformat()

    def record(self, text_id: str, result: dict, balance=None) -> dict:
        """记录一次成绩；按基础分发放挑战经验（每日上限）。

        返回 (记录, 是否新纪录, 更新前最佳分, 本次经验)。
        """
        prev = self._repo.get_best_challenge(text_id)
        best = prev['best'] or 0 if prev else 0
        prev_best = best
        points = result.get('score_points', 0)
        is_best = points > best
        if is_best:
            best = int(points)
        self._repo.add_challenge(
            datetime.now().isoformat(timespec='seconds'),
            text_id, result['typed_chars'], result['errors'],
            result.get('elapsed_seconds', 0), result['tw'],
            result['accuracy'], best, points)

        # 挑战经验：基础分 × 系数，每日上限（按应用日）
        cfg = (balance or {}).get('challenge_exp', {})
        per = cfg.get('per_base_point', 1)
        cap = int(cfg.get('daily_cap', 200))
        exp = int(result.get('base', 0) * per)
        today = self._app_day()
        if self._repo.get_setting('challenge_exp_date') != today:
            self._repo.set_setting('challenge_exp_date', today)
            self._repo.set_setting('challenge_exp_today', '0')
        used = int(self._repo.get_setting('challenge_exp_today', '0') or 0)
        grant = max(0, min(exp, cap - used))
        if grant > 0:
            self._repo.add_exp(grant)
            self._repo.add_exp_to_daily(today, grant)
            self._repo.set_setting('challenge_exp_today', str(used + grant))

        return {'record': result, 'is_best': is_best,
                'prev_best': prev_best, 'exp_gained': grant}

    def best(self, text_id: str):
        return self._repo.get_best_challenge(text_id)

    def recent(self, n: int = 8):
        return self._repo.get_recent_challenges(n)

    def leaderboard(self, text_id: str, n: int = 10):
        """个人同篇练习榜：名次与 tw/分钟口径由服务给出，UI 不访问 SQL。"""
        rows = self._repo.get_challenge_leaderboard(text_id, n)
        for rank, row in enumerate(rows, 1):
            row['rank'] = rank
            row['speed'] = row['tw'] * 60 / row['elapsed_seconds']
        return rows
