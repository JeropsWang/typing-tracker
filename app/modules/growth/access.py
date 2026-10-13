"""开发者彩蛋的会话权限；不持久化等级、经验或训练券。"""
from dataclasses import dataclass



def ai_access_state(level: int, ai_pass_count: int, unlock_level: int = 45):
    """AI 定制训练访问判定（纯逻辑，可无 GUI 测试）。

    返回 (是否可用, 提示文案)。
    """
    if level >= unlock_level:
        return True, f'AI 定制训练已解锁 ✓（Lv.{unlock_level}）'
    if ai_pass_count > 0:
        return True, f'AI 训练券可用（剩 {ai_pass_count} 张，Lv.{unlock_level} 后无限生成）'
    return False, (f'🔒 Lv.{unlock_level} 解锁 AI 定制训练'
                   f'（当前 Lv.{level}，速度跃升可获得 AI 训练券）')


@dataclass
class AITestSession:
    enabled: bool = False

    def access(self, level, passes, unlock):
        if self.enabled:
            return True, '开发者彩蛋 · AI 测试临时解锁；请求仍消耗 API token'
        return ai_access_state(level, passes, unlock)
