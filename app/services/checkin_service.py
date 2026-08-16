"""每日打卡：每天首次使用自动签到 + 连签奖励 + 里程碑礼包。"""
from __future__ import annotations

import json
from datetime import date, timedelta


class CheckinService:
    def __init__(self, repo, balance):
        self._repo = repo
        self._balance = balance

    def checkin_if_needed(self, day_iso=None):
        """若当日未打卡则自动签到；连签里程碑触发时发放礼包。

        返回 dict（含可选 milestone 字段）或 None。
        """
        day_iso = day_iso or date.today().isoformat()
        if self._repo.has_checkin(day_iso):
            return None
        yesterday = (date.fromisoformat(day_iso) - timedelta(days=1)).isoformat()
        streak = self._repo.get_streak(yesterday) + 1

        cfg = self._balance['checkin']
        base = cfg['base_exp']
        bonus = round(min(streak - 1, cfg['streak_bonus_cap']) * cfg['streak_bonus_factor'])
        total = base + bonus

        self._repo.add_checkin(day_iso, streak, base, bonus)
        self._repo.add_exp(total)
        self._repo.add_exp_to_daily(day_iso, total)

        result = {
            'date': day_iso,
            'streak': streak,
            'base_exp': base,
            'bonus_exp': bonus,
            'total_exp': total,
        }
        milestone = self._grant_milestone(day_iso, streak)
        if milestone:
            result['milestone'] = milestone
        return result

    def _grant_milestone(self, day_iso, streak):
        """连签里程碑礼包（每档只发一次）。返回里程碑天数或 None。"""
        cfg = self._balance['checkin']
        if streak not in cfg.get('milestones', []):
            return None
        granted = self._load_milestone_grants()
        if streak in granted:
            return None
        mw = cfg.get('milestone_rewards', {}).get(str(streak), {})
        for kind, qty in mw.items():
            if kind == 'exp':
                self._repo.add_exp(qty)
                self._repo.add_exp_to_daily(day_iso, qty)
            elif kind in ('makeup_card', 'exp_boost'):
                self._repo.add_reward(kind, qty, f'milestone:{streak}')
            elif kind == 'title':
                self._repo.add_reward('title', 1, f'milestone:{streak}', note=qty)
        granted.append(streak)
        self._repo.set_setting('milestone_granted', json.dumps(granted))
        return streak

    def _load_milestone_grants(self) -> list:
        raw = self._repo.get_setting('milestone_granted')
        if not raw:
            return []
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return []

    def apply_makeup_card(self, missed_date, today_iso=None):
        """补签卡补签：只允许补**昨天**（防止未来日期/任意历史刷连签）。

        返回 dict（含可选 milestone 字段）或 None。
        """
        today_iso = today_iso or date.today().isoformat()
        yesterday = (date.fromisoformat(today_iso) - timedelta(days=1)).isoformat()
        if missed_date != yesterday:
            return None  # 只允许补昨天（服务层强制，UI 亦如此限制）
        if self._repo.has_checkin(missed_date):
            return None
        prev = (date.fromisoformat(missed_date) - timedelta(days=1)).isoformat()
        streak = self._repo.get_streak(prev) + 1
        base = self._balance['checkin']['base_exp']
        self._repo.add_checkin(missed_date, streak, base, 0, card_used=1)
        self._repo.add_exp(base)
        self._repo.add_exp_to_daily(missed_date, base)
        result = {'date': missed_date, 'streak': streak, 'base_exp': base}
        # 补签把连签推进到里程碑数字时，里程碑礼包照发（曾漏发，v0.8.9 修复）
        milestone = self._grant_milestone(missed_date, streak)
        if milestone:
            result['milestone'] = milestone
        return result
