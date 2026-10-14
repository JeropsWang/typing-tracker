"""打字竞速挑战服务：记录成绩 / 查询最佳 / 经验奖励（挑战分 → 等级经验）。"""
from __future__ import annotations
from ...storage.unit_of_work import transactional

from datetime import date, datetime, timedelta
import uuid
from ..growth.api import RewardLedger
from ..tracking.api import AppCalendar, SystemClock


class ChallengeService:
    """普通训练的成绩/纪录业务服务，写入与经验结算参与同一事务。"""
    def __init__(self, repo, clock=None):
        """装配训练查询与提交所需的仓储能力。"""
        self._repo = repo
        self.clock = clock or SystemClock()

    def _app_day(self) -> str:
        """按应用的日切起点归属日期（曾用 date.today()，00:00-04:00 窗口
        上限提前重置、经验归错日，v0.8.9 修复）。"""
        return AppCalendar(int(self._repo.get_setting('day_start_hour','4') or 4)).day(self.clock.now())

    @transactional
    def record(self, text_id: str, result: dict, balance=None, operation_id=None) -> dict:
        """记录一次成绩；按基础分发放挑战经验（每日上限）。

        返回 (记录, 是否新纪录, 更新前最佳分, 本次经验)。
        """
        operation_id = operation_id or result.get('id') or uuid.uuid4().hex
        return self._repo.operation('practice.complete',operation_id,
            lambda: self._record(text_id,result,balance))

    def _record(self,text_id,result,balance):
        """在已开启事务中比较旧纪录、写成绩并结算日上限经验，返回提交结果数据。"""
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

        grant = RewardLedger(self._repo,balance or {}).challenge(self._app_day(),result.get('base',0))

        return {'record': result, 'is_best': is_best,
                'prev_best': prev_best, 'exp_gained': grant}

    def best(self, text_id: str):
        """读取指定范文的历史最佳比较基线，无记录返回 None。"""
        return self._repo.get_best_challenge(text_id)

    def recent(self, n: int = 8):
        """返回有界最近训练记录，供历史展示。"""
        return self._repo.get_recent_challenges(n)

    def leaderboard(self, text_id: str, n: int = 10):
        """个人同篇练习榜：名次与 tw/分钟口径由服务给出，UI 不访问 SQL。"""
        rows = self._repo.get_challenge_leaderboard(text_id, n)
        for rank, row in enumerate(rows, 1):
            row['rank'] = rank
            row['speed'] = row['tw'] * 60 / row['elapsed_seconds']
        return rows
