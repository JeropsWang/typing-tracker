"""开发者彩蛋的会话权限；不持久化等级、经验或训练券。"""
from dataclasses import dataclass
from ..core.challenge import ai_access_state


@dataclass
class AITestSession:
    enabled: bool = False

    def access(self, level, passes, unlock):
        if self.enabled:
            return True, '开发者彩蛋 · AI 测试临时解锁；请求仍消耗 API token'
        return ai_access_state(level, passes, unlock)
