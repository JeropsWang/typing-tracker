"""记忆页面的只读／异步能力门面，不持有数据库或原始模型配置。"""
from datetime import datetime, timezone
from dataclasses import replace
from ...modules.companion.api import normalize_interests


class MemoryPresenter:
    """两个界面视角共享唯一快照与稳定记录 ID，写入交给工作线程。"""
    def __init__(self, queries, news_commands, *, now_utc=None):
        """注入读模型、异步命令和测试时钟，避免页面自行访问 SQLite。"""
        self.queries, self.commands = queries, news_commands
        self.now_utc = now_utc or (lambda: datetime.now(timezone.utc).isoformat(timespec='seconds'))

    def snapshot(self):
        """返回已提交的冻结记忆，网络内存结果不冒充已保存历史。"""
        return self.queries.news_snapshot()

    def forget(self, task_id, operation_id):
        """以调用方保持的操作 ID 删除正文，确认提交前不移除界面卡片。"""
        return self.commands.forget(task_id, operation_id=operation_id, now_utc=self.now_utc())

    def save_interests(self, text, operation_id):
        """显式保存兴趣；清空兴趣也关闭排期，网页内容永不自动写为画像。"""
        interests = normalize_interests(text)
        config = replace(self.snapshot().config, enabled=False, interests=interests)
        values = {'companion_news_interests': config.settings_values()['companion_news_interests']}
        if not interests:
            values['companion_news_enabled'] = '0'
        return self.commands.save_settings(values, operation_id=operation_id, now_utc=self.now_utc())
