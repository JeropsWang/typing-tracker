"""桌宠公开业务入口，导出活动、作品与智能体契约，供跨模块装配和 UI 使用。"""
from dataclasses import dataclass
from ..growth.api import level_and_progress, GrowthSummary
from .models import CompanionEvent, STATES, PLACEHOLDERS, format_line
from .runtime import Runtime, REACTIONS
from .packs import PackStore, LoadedPack, Sprite, DEFAULT_PACK, BUILTIN_DIR
from .validation import validate_manifest, safe_path, image_size, MAX_FILE, MAX_FILES, MAX_TOTAL
from .agent import (AgentConfig, AgentReport, AgentProgress, SearchSource, AgentTool,
                    AgentToolCall, AgentTurn, AgentRunLimits,
                    CompanionAgent, MODEL_PRESETS,
                    AgentConnectionResult, AgentBusyError, validate_topic)
from .persona import search_system_prompt, summary_system_prompt, news_system_prompt
from .news import (NewsConfig, NewsPlan, NewsRequest, NewsClaim, NewsTask,
                   normalize_interests, is_quiet, scheduled_at, due_plan,
                   next_news_at, configuration_fingerprint)
from .news_codec import encode_report, decode_report
from .memory import MemorySnapshot
from .failures import (FAILURE_CODES, normalize_failure_code, agent_failure_code, failure_message)
from .news_status import NewsStatus, news_status, retryable_news_task
from .news_service import CompanionNewsService, task_from_row, validate_utc as validate_news_utc

@dataclass(frozen=True)
class ActivityState:
    """供桌宠使用的只读活动快照：应用日、当日计数和是否有练习在进行。"""
    day: str
    typed: int
    practicing: bool

class ActivityProvider:
    """从内存计数器/查询能力组合桌宠公共活动数据，按来源聚合练习状态。"""
    def __init__(self,counter,queries,balance):
        """装配计数器、只读查询与等级配置，初始化练习来源集合。"""
        self.counter,self.queries,self.balance=counter,queries,balance
        self._running=set()
    def set_practicing(self,source,running):
        """按调用来源登记或移除练习状态，避免一个页面结束清除其他页面的练习。"""
        if running:
            self._running.add(source)
        else:
            self._running.discard(source)
    def activity(self):
        """组合当前内存统计与练习集合为不可变快照，不包含输入正文。"""
        snap=self.counter.snapshot()
        return ActivityState(snap['day'],snap['typed'],bool(self._running))
    def growth(self):
        """按当前应用日返回等级和连续打卡的只读成长摘要。"""
        day=self.counter.current_day()
        return GrowthSummary(level_and_progress(self.queries.get_exp(),self.balance)[0],self.queries.get_streak(day))
