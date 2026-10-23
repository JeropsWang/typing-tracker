"""来信的不可变契约与当地日排期；不访问 Qt、数据库、网络或系统时钟。"""
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta
import hashlib
import json
import re
from typing import Mapping

from .agent import AgentConfig, AgentReport


def normalize_interests(text: str) -> tuple[str, ...]:
    """从换行／分隔符或设置 JSON 读取显式兴趣；规范空白、保序去重并验证上限。"""
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError('兴趣内容过长或格式不正确。')
    if text.lstrip().startswith('['):
        try:
            values = json.loads(text)
        except (ValueError, TypeError):
            raise ValueError('兴趣格式不正确，请每行填写一个兴趣。') from None
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError('兴趣必须是文字列表。')
    else:
        values = re.split(r'[\r\n,，;；]+', text)
    result, seen = [], set()
    for value in values:
        item = ' '.join(value.split())
        if not item:
            continue
        if len(item) > 40:
            raise ValueError('每个兴趣请控制在 40 字以内。')
        key = item.casefold()
        if key not in seen:
            result.append(item)
            seen.add(key)
    if len(result) > 5 or sum(map(len, result)) > 200:
        raise ValueError('最多填写 5 个兴趣，总计不超过 200 字。')
    return tuple(result)


def _time(value: str) -> wall_time:
    """严格读取 HH:MM 本地墙上时间，拒绝溢出、秒和隐式日期解析。"""
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('时间请使用 HH:MM 格式。')
    try:
        return wall_time.fromisoformat(value)
    except ValueError:
        raise ValueError('请输入有效的小时和分钟。') from None


@dataclass(frozen=True)
class NewsConfig:
    """已提交的来信偏好；关闭且无兴趣为合法初始态，开启后必须有明确兴趣。"""
    enabled: bool = False
    interests: tuple[str, ...] = ()
    time: str = '09:00'
    quiet_enabled: bool = True
    quiet_start: str = '22:00'
    quiet_end: str = '08:00'

    def __post_init__(self):
        """构造时执行同一套约束，避免直接构造绕过表单与存储校验。"""
        interests = normalize_interests(json.dumps(self.interests, ensure_ascii=False))
        object.__setattr__(self, 'interests', interests)
        _time(self.time)
        start, end = _time(self.quiet_start), _time(self.quiet_end)
        if start == end:
            raise ValueError('安静时段的开始与结束不能相同。')
        if self.enabled and not interests:
            raise ValueError('开启定时来信前，请至少填写一个兴趣。')

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> 'NewsConfig':
        """从完整设置快照解析来信字段，不读取其他画像或隐式持久化。"""
        get = lambda key, default: values.get('companion_news_' + key, default)
        return cls(enabled=get('enabled', '0') == '1',
                   interests=normalize_interests(get('interests', '[]')),
                   time=get('time', '09:00'), quiet_enabled=get('quiet_enabled', '1') != '0',
                   quiet_start=get('quiet_start', '22:00'), quiet_end=get('quiet_end', '08:00'))

    def settings_values(self) -> dict[str, str]:
        """返回待提交的来信配置，不包含由持久层生成的 revision 或更新时间。"""
        values = dict(enabled='1' if self.enabled else '0',
                      interests=json.dumps(self.interests, ensure_ascii=False), time=self.time,
                      quiet_enabled='1' if self.quiet_enabled else '0',
                      quiet_start=self.quiet_start, quiet_end=self.quiet_end)
        return {'companion_news_' + key: value for key, value in values.items()}


@dataclass(frozen=True)
class NewsPlan:
    """当前当地日的有效排期；稳定 ID 不因时间或兴趣修改而改变。"""
    task_id: str
    planned_date: str
    planned_time: str
    scheduled_at: datetime


@dataclass(frozen=True)
class NewsRequest:
    """一次图执行的主动兴趣与当地日期；不含 Key、统计或被动输入。"""
    interests: tuple[str, ...]
    local_day: str

    def __post_init__(self):
        """验证请求内容并固定兴趣元组，防止异步过程中外部修改列表。"""
        values = normalize_interests(json.dumps(self.interests, ensure_ascii=False))
        if not values:
            raise ValueError('请先填写想了解的兴趣。')
        object.__setattr__(self, 'interests', values)
        if date.fromisoformat(self.local_day).isoformat() != self.local_day:
            raise ValueError('来信日期格式不正确。')

    @property
    def topic(self) -> str:
        """提供有界展示标题，实际兴趣通过专用请求契约传入提示词。"""
        return f'{self.local_day} · 兴趣来信'


@dataclass(frozen=True)
class NewsClaim:
    """工作线程已提交的执行凭据；task_id／attempt 防止旧回调覆盖新尝试。"""
    task_id: str
    attempt: int
    config_fingerprint: str
    kind: str
    planned_date: str
    planned_time: str
    run_id: str


@dataclass(frozen=True)
class NewsTask:
    """脱离数据库的任务展示记录；报告只有成功提交后才出现在此快照中。"""
    task_id: str
    kind: str
    planned_date: str
    planned_time: str
    config_fingerprint: str
    state: str
    attempt: int
    run_id: str
    created_at: str
    started_at: str = ''
    finished_at: str = ''
    error_code: str = ''
    report: AgentReport | None = None
    notified_at: str = ''
    deleted_at: str = ''


def is_quiet(config: NewsConfig, now: datetime) -> bool:
    """判断当地时间是否位于安静区间，包含起点、排除终点并支持跨午夜。"""
    if not config.quiet_enabled:
        return False
    current = now.time().replace(tzinfo=None)
    start, end = _time(config.quiet_start), _time(config.quiet_end)
    return start <= current < end if start < end else current >= start or current < end


def scheduled_at(config: NewsConfig, day: date) -> datetime | None:
    """返回当日有效墙上时间；安静顺延跨日则跳过，不补发历史日报。"""
    target = datetime.combine(day, _time(config.time))
    if not is_quiet(config, target):
        return target
    end = datetime.combine(day, _time(config.quiet_end))
    return end if end > target else None


def due_plan(config: NewsConfig, now: datetime) -> NewsPlan | None:
    """只在当日有效时刻后的闭合两小时窗口返回计划；不负责数据库名额核准。"""
    if not config.enabled or is_quiet(config, now):
        return None
    target = scheduled_at(config, now.date())
    wall = now.replace(tzinfo=None)
    if target is None or not target <= wall <= target + timedelta(hours=2):
        return None
    day = now.date().isoformat()
    return NewsPlan('news:' + day, day, config.time, target.replace(tzinfo=now.tzinfo))


def next_news_at(config: NewsConfig, now: datetime) -> datetime | None:
    """按相同安静规则返回严格晚于当前时间的日排期；恒定跨日跳过时返回空。"""
    if not config.enabled:
        return None
    for offset in (0, 1):
        target = scheduled_at(config, now.date() + timedelta(days=offset))
        if target is not None and target > now.replace(tzinfo=None):
            return target.replace(tzinfo=now.tzinfo)
    return None


def configuration_fingerprint(agent: AgentConfig, news: NewsConfig, companion_enabled: bool) -> str:
    """仅用非凭据配置生成任务版本指纹，不将 Key 或完整配置保存到任务表。"""
    values = {key: getattr(agent, key) for key in
              ('enabled', 'provider', 'base_url', 'model', 'search_provider', 'search_url', 'thinking')}
    values.update(news=news.settings_values(), companion_enabled=bool(companion_enabled))
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
