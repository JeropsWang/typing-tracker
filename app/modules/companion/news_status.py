"""来信只读展示规则；由已提交快照和注入时钟推导排期、最近失败和重试资格。"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from .news import due_plan, next_news_at, is_quiet, scheduled_at
from .failures import failure_message


@dataclass(frozen=True)
class NewsStatus:
    """跨界面复用的只读来信状态，不持有数据库、计时器或可变控件。"""
    schedule: str
    current: str
    last_failure: str = ''
    retry_task_id: str = ''


def retryable_news_task(task, now):
    """仅未删除终态可显式重试；自动任务还必须属于当前本机自然日。"""
    return (not task.deleted_at and task.state in ('failed', 'cancelled', 'interrupted')
            and (task.kind != 'auto' or task.planned_date == now.date().isoformat()))


def news_status(snapshot, now, *, agent_enabled=True, companion_enabled=True):
    """同一排期规则推导展示；终态保留当日名额，历史失败不伪装为未开启。"""
    config = snapshot.config
    tasks = tuple(item for item in snapshot.tasks if not item.deleted_at)
    today = next((item for item in snapshot.tasks if item.task_id == 'news:' + now.date().isoformat()), None)
    retry = next((item.task_id for item in tasks if retryable_news_task(item, now)), '')
    failed = next((item for item in sorted(tasks, key=lambda item: item.finished_at or item.created_at, reverse=True)
                   if item.state in ('failed', 'interrupted')), None)
    failure = ''
    if failed:
        try:
            stamp = datetime.fromisoformat(failed.finished_at or failed.created_at).astimezone().strftime('%m-%d %H:%M')
        except (ValueError, TypeError):
            stamp = failed.planned_date
        failure = '最近失败 · ' + stamp + '：' + failure_message(failed.error_code or 'interrupted')
        if failed.kind == 'auto' and failed.planned_date != now.date().isoformat():
            failure += ' 该自动任务已过期，请点击“现在联网准备一封”。'
    if not agent_enabled or not companion_enabled:
        return NewsStatus('排期暂停', '请先开启桌宠和桌宠智能体。', failure, retry)
    if not config.enabled:
        return NewsStatus('自动来信已关闭', '定时来信尚未开启；仍可明确准备一封。', failure, retry)
    if not config.interests:
        return NewsStatus('等待保存兴趣', '请先填写并保存至少一个兴趣。', failure, retry)
    planned = next_news_at(config, now)
    due = due_plan(config, now)
    target = scheduled_at(config, now.date())
    if today is not None and today.state != 'waiting':
        # 当日名额已用，修改时间也不能显示今天还会自动再发。
        planned = next_news_at(config, now.replace(hour=23, minute=59, second=59))
        current = {'running': '当日来信正在处理。', 'completed': '当日来信已保存，可到记忆页查看。',
                   'failed': '当日自动来信未完成，请明确重试；不会自动重复联网。',
                   'interrupted': '上次来信中断，请明确重试。',
                   'cancelled': '当日自动来信已取消，可明确准备一封。'}.get(today.state, '当日来信已有安排。')
        if today.deleted_at:
            current = '当日来信已删除，今日不会自动重新准备。'
    elif due:
        planned, current = target, '已到来信时间，等待空闲后开始。'
    elif is_quiet(config, now):
        current = '安静时段中，自动准备和提醒暂缓。'
    elif target and now.replace(tzinfo=None) > target + timedelta(hours=2):
        current = '今日补做窗口已过，可现在准备一封。'
    else:
        current = '定时来信已开启，等待下次安排。'
    schedule = ('下次安排：' + planned.strftime('%m-%d %H:%M')) if planned else '当前排期被安静时段跳过，请调整时间。'
    return NewsStatus(schedule, current, failure, retry)
