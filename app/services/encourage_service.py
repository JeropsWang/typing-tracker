"""鼓励机制（M3）：近 7 日速度较前 7 日明显上升（≥ ratio）→ 发奖励。

- 样本要求：近 7 日活跃 ≥ min_minutes_7d 分钟
- 冷却：cooldown_hours（默认 72h），记录在 settings.last_encourage_at
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta


class EncourageService:
    def __init__(self, repo, balance):
        self._repo = repo
        self._balance = balance

    def check(self, engine):
        """在日切后调用；触发时发放奖励并返回事件 dict，否则返回 None。"""
        cfg = self._balance['encourage']
        last = self._repo.get_setting('last_encourage_at')
        if last:
            try:
                dt = datetime.fromisoformat(last)
                if (datetime.now() - dt).total_seconds() < cfg['cooldown_hours'] * 3600:
                    return None
            except ValueError:
                pass

        today = date.fromisoformat(engine.current_day())
        start = today - timedelta(days=13)
        days = self._repo.get_daily_range(start.isoformat(), today.isoformat())

        def seg_mean(offset):
            """offset=0 → 近 7 日 [today-6, today]；offset=7 → 前 7 日 [today-13, today-7]。"""
            lo = today - timedelta(days=offset + 6)
            hi = today - timedelta(days=offset)
            seg = [d for d in days
                   if lo.isoformat() <= d['date'] <= hi.isoformat()]
            vals = [d['avg_tw'] for d in seg if d['avg_tw'] is not None]
            minutes = sum(d['active_minutes'] for d in seg)
            return (sum(vals) / len(vals) if vals else None, minutes)

        cur, cur_min = seg_mean(0)
        prev, _ = seg_mean(7)
        if cur is None or prev is None or prev <= 0:
            return None
        if cur_min < cfg['min_minutes_7d']:
            return None
        if cur < prev * cfg['ratio']:
            return None

        pool = [
            ('makeup_card', 1),
            ('exp_boost', 1),
            ('exp', random.randint(20, 80)),
        ]
        kind, qty = random.choice(pool)
        self._repo.add_reward(kind, qty, 'encourage')
        self._repo.set_setting('last_encourage_at',
                               datetime.now().isoformat(timespec='seconds'))
        return {
            'cur_avg': cur,
            'prev_avg': prev,
            'ratio': cur / prev,
            'reward': (kind, qty),
        }
