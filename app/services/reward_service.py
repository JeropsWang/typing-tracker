"""道具系统（M3）：补签卡 / 经验加成卡 / 称号的库存与使用。"""
from __future__ import annotations

from datetime import datetime, timedelta


class RewardService:
    def __init__(self, repo, balance):
        self._repo = repo
        self._balance = balance

    # ---------- 库存 ----------
    def count(self, kind) -> int:
        return sum(r['qty'] for r in self._repo.list_rewards(unused_only=True)
                   if r['kind'] == kind)

    def titles(self) -> list:
        return [r['note'] for r in self._repo.list_rewards(unused_only=True)
                if r['kind'] == 'title' and r['note']]

    # ---------- 经验加成卡 ----------
    def activate_exp_boost(self, minutes=30):
        until = datetime.now() + timedelta(minutes=minutes)
        # 已有生效中的加成时不缩短剩余时长（曾直接覆盖，前卡余时作废，
        # v0.8.9 修复）
        raw = self._repo.get_setting('exp_boost_until')
        if raw:
            try:
                existing = datetime.fromisoformat(raw)
                if existing > until:
                    until = existing
            except ValueError:
                pass
        self._repo.set_setting('exp_boost_until', until.isoformat(timespec='seconds'))
        return until

    def boost_active(self) -> bool:
        raw = self._repo.get_setting('exp_boost_until')
        if not raw:
            return False
        try:
            return datetime.fromisoformat(raw) > datetime.now()
        except ValueError:
            return False

    def use_exp_boost(self, minutes=30) -> bool:
        """使用一张经验加成卡（×2 打字经验，默认 30 分钟）。"""
        if not self._repo.use_reward('exp_boost'):
            return False
        self.activate_exp_boost(minutes)
        return True
