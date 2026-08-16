"""成就系统（M3）：37 项定义（config/achievements.json）的判定、解锁与手动领取。

判定时机：日切归档后（speed / min_acc）；累计值变化时（chars / total_acc）。
解锁后奖励在成就页手动领取（claimed 标记）。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


class AchievementService:
    def __init__(self, repo, balance, defs: dict):
        self._repo = repo
        self._balance = balance
        self._defs = defs

    # ---------- 查询 ----------
    def all_achievements(self) -> list:
        """合并定义与数据库状态，供 UI 展示。"""
        status = {r['code']: r for r in self._repo.get_achievements()}
        out = []
        for cat, items in self._defs.items():
            for it in items:
                st = status.get(it['code'], {})
                out.append({
                    **it,
                    'category': cat,
                    'unlocked_at': st.get('unlocked_at'),
                    'claimed': st.get('claimed', 0),
                })
        return out

    def find(self, code):
        for cat, items in self._defs.items():
            for it in items:
                if it['code'] == code:
                    return {**it, 'category': cat}
        return None

    # ---------- 判定 ----------
    def check_all(self, engine) -> list:
        """检查全部条件，返回本次新解锁的成就列表（已入库）。"""
        today = engine.current_day()
        start = (date.fromisoformat(today) - timedelta(days=6)).isoformat()
        days = self._repo.get_daily_range(start, today)

        vals = [d['avg_tw'] for d in days if d['avg_tw'] is not None]
        minutes = sum(d['active_minutes'] for d in days)
        avg = sum(vals) / len(vals) if len(vals) >= 3 else None

        life = self._repo.get_lifetime() or {}
        ltyped = life.get('total_typed', 0) or 0
        lvalid = max(0, ltyped - (life.get('total_deleted', 0) or 0))
        total_acc = lvalid / ltyped if ltyped else None

        mins = self._repo.get_minute_quality(start, today, min_typed=30)

        unlocked = []
        for cat, items in self._defs.items():
            for it in items:
                if self._repo.has_achievement(it['code']):
                    continue
                t = it['target']
                hit = False
                if cat == 'speed':
                    hit = avg is not None and minutes >= 30 and avg >= t
                elif cat == 'chars':
                    hit = lvalid >= t
                elif cat == 'min_acc':
                    hit = any((m['typed_chars'] - m['deleted_chars']) / m['typed_chars'] >= t
                              for m in mins)
                elif cat == 'total_acc':
                    hit = total_acc is not None and total_acc >= t
                if hit:
                    self._repo.unlock_achievement(
                        it['code'], datetime.now().isoformat(timespec='seconds'))
                    unlocked.append({**it, 'category': cat})
        return unlocked

    # ---------- 领取 ----------
    def claim(self, code):
        """手动领取奖励；返回发放明细列表，已领取/不存在返回 None。"""
        row = self._repo.get_achievement(code)
        if not row or row['claimed']:
            return None
        item = self.find(code)
        if not item:
            return None
        # 先发放奖励、成功后标记已领取（曾先标记后发放，异常时奖励永久丢失，
        # v0.8.9 修复）
        granted = []
        for rw in item.get('rewards', []):
            kind, qty = rw['kind'], rw.get('qty', 1)
            if kind == 'exp':
                self._repo.add_exp(qty)
                granted.append(('exp', qty))
            elif kind in ('makeup_card', 'exp_boost'):
                self._repo.add_reward(kind, qty, f'achievement:{code}')
                granted.append((kind, qty))
            elif kind == 'title':
                self._repo.add_reward('title', 1, f'achievement:{code}',
                                      note=rw.get('value', ''))
                granted.append(('title', rw.get('value', '')))
        self._repo.set_claimed(code)
        return granted
