"""键盘侠会话结算与本地历史业务，只保存计量成绩，不保存输入正文或发放训练奖励。"""
from ...storage.unit_of_work import transactional
"""Local keyboard-warrior history; no text or practice rewards are stored."""
from datetime import datetime


class KeyboardWarriorService:
    """十五秒键盘侠的记录与排行榜业务，按会话 ID 避免重复保存。"""
    def __init__(self, repo):
        """装配训练记录仓储能力。"""
        self._repo = repo

    @transactional
    def record(self, session):
        """只结算已结束且有输入的会话；空会话不保存，返回是否实际新增记录。"""
        result = session.result()
        if not result['typed_chars']:
            return False
        return self._repo.add_keyboard_warrior(result, datetime.now().isoformat(timespec='seconds'))

    def leaderboard(self, limit=10):
        """取得有界键盘侠速度排行，供只读展示。"""
        return self._repo.keyboard_warrior_leaderboard(limit)
