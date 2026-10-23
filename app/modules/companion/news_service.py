"""工作线程中的来信事务服务；稳定任务和 attempt 决定是否允许提交，不执行网络。"""
from datetime import date, datetime, timedelta
import re

from .news import NewsClaim, NewsTask
from .news_codec import encode_report, decode_report
from .failures import normalize_failure_code


def task_from_row(row) -> NewsTask:
    """将数据库脱离行投影为不可变记录；损坏报告只标错误，不使整页记忆读取失败。"""
    report, error = None, row['error_code']
    if row['report_json'] and not row['deleted_at']:
        try:
            report = decode_report(row['report_json'])
        except ValueError:
            error = 'invalid_report'
    return NewsTask(row['id'], row['kind'], row['planned_date'], row['planned_time'],
                    row['config_fingerprint'], row['state'], row['attempt'], row['run_id'],
                    row['created_at'], row['started_at'], row['finished_at'], error, report,
                    row['notified_at'], row['deleted_at'])


def validate_utc(value):
    """仅接受带 UTC 时区的有界时间文本，持久化时间不依赖界面格式化结果。"""
    try:
        if not isinstance(value, str) or len(value) > 40:
            raise ValueError
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('来信记录时间必须是 UTC 时间。') from None
    return value


class CompanionNewsService:
    """只在 ApplicationWorker 使用的来信服务，统一事务后才发布 companion 变更。"""
    def __init__(self, store, uow, *, run_id):
        """注入同一连接的仓储与工作单元，以及本次进程的唯一运行标识。"""
        self.store, self.uow, self.run_id = store, uow, run_id

    def task(self, task_id):
        """读取指定任务的安全展示值，不向调用方泄漏 report_json。"""
        row = self.store.get_task(task_id)
        return task_from_row(row) if row else None

    def claim(self, task_id, kind, config_fingerprint, planned_date, planned_time, *, now_utc, retry=False):
        """首次领取或显式重试；失败／取消／中断不因普通定时检查重放。"""
        validate_utc(now_utc)
        day = date.fromisoformat(planned_date).isoformat()
        if (day != planned_date or kind not in ('auto', 'manual')
                or (kind == 'auto' and task_id != 'news:' + day)
                or (kind == 'manual' and not re.fullmatch(r'manual:[0-9a-f]{32}', task_id))
                or not re.fullmatch(r'[0-9a-f]{64}', config_fingerprint)
                or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', planned_time)):
            raise ValueError('来信领取参数不正确。')
        with self.uow.transaction():
            row = self.store.get_task(task_id)
            if row:
                if (row['deleted_at'] or row['kind'] != kind or row['planned_date'] != day
                        or row['state'] in ('running', 'completed')
                        or (row['state'] != 'waiting' and not retry)):
                    return None
                if not self.store.start_attempt(row, config_fingerprint, self.run_id, now_utc):
                    return None
            else:
                self.store.insert_task(task_id, kind, config_fingerprint, day, planned_time, self.run_id, now_utc)
            self.uow.changed('companion')
            row = self.store.get_task(task_id)
            return NewsClaim(task_id, row['attempt'], config_fingerprint, kind, day, row['planned_time'], self.run_id)

    def release_unstarted(self, claim):
        """网络服务明确忙碌且尚未发起 I/O 时退还等待状态，不减少单调 attempt。"""
        with self.uow.transaction():
            changed = self.store.release_unstarted(claim)
            if changed:
                self.uow.changed('companion')
            return changed

    def complete(self, claim, report, *, now_utc):
        """以同一 claim 原子保存报告与完成状态；重复完成返回原提交，旧 attempt 拒绝。"""
        validate_utc(now_utc)
        encoded = encode_report(report)
        with self.uow.transaction():
            row = self.store.get_task(claim.task_id)
            if (row and row['state'] == 'completed' and row['attempt'] == claim.attempt
                    and row['run_id'] == claim.run_id and not row['deleted_at']):
                return task_from_row(row)
            if not self.store.finish_attempt(claim, 'completed', report_json=encoded, finished_at=now_utc):
                raise ValueError('这次来信尝试已失效，未覆盖新的记录。')
            self.uow.changed('companion')
            return self.task(claim.task_id)

    def fail(self, claim, error_code, *, now_utc):
        """只保存固定错误类别；未知上游异常不能把 URL、Key 或原始消息写入数据库。"""
        validate_utc(now_utc)
        code = normalize_failure_code(error_code)
        state = 'cancelled' if code in ('cancelled', 'configuration_changed') else 'failed'
        with self.uow.transaction():
            changed = self.store.finish_attempt(claim, state, error_code=code, finished_at=now_utc)
            if changed:
                self.uow.changed('companion')
            return changed

    def accept_notice(self, task_id, *, now_utc):
        """校验真实可读报告后受理一次通知；提交失败时 UI 不能展示完成卡片。"""
        validate_utc(now_utc)
        with self.uow.transaction():
            task = self.task(task_id)
            if not task or task.report is None or task.error_code == 'invalid_report':
                return False
            changed = self.store.accept_notice(task_id, now_utc)
            if changed:
                self.uow.changed('companion')
            return changed

    def forget(self, task_id, *, operation_id, now_utc):
        """以稳定删除操作 ID 清内容并保留墓碑，失败回滚后原记忆继续可读。"""
        validate_utc(now_utc)
        def action():
            """在外层幂等事务内删除内容并登记提交后的刷新主题。"""
            changed = self.store.forget(task_id, now_utc)
            if changed:
                self.uow.changed('companion')
            return changed
        return self.uow.operation('companion.forget', operation_id, action)

    def recover(self, *, now_utc):
        """启动时转换其他进程的在途任务，绝不在恢复事务中启动网络。"""
        validate_utc(now_utc)
        with self.uow.transaction():
            changed = self.store.recover(self.run_id, now_utc)
            if changed:
                self.uow.changed('companion')
            return changed

    def prune(self, *, local_day, now_utc, keep_task_id=''):
        """在工作线程有界清理终态历史，不影响任何在途 claim 和今日自动名额。"""
        validate_utc(now_utc)
        with self.uow.transaction():
            changed = self.store.prune(local_day, keep_task_id)
            if changed:
                self.uow.changed('companion')
            return changed
