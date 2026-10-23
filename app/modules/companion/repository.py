"""来信模块的 SQLite 边界；连接归 ApplicationWorker，所有方法均不自行提交。"""
from datetime import date, timedelta

from ...storage.store import Store


def migrate_news_schema(conn):
    """在外层迁移事务内建立任务表与历史查询索引，不修改旧版本迁移。"""
    conn.execute('''CREATE TABLE companion_news_tasks (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('auto','manual')),
        planned_date TEXT NOT NULL, planned_time TEXT NOT NULL,
        config_fingerprint TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('waiting','running','completed','failed','cancelled','interrupted')),
        attempt INTEGER NOT NULL CHECK(attempt > 0), run_id TEXT NOT NULL,
        created_at TEXT NOT NULL, started_at TEXT NOT NULL DEFAULT '',
        finished_at TEXT NOT NULL DEFAULT '', error_code TEXT NOT NULL DEFAULT '',
        report_json TEXT NOT NULL DEFAULT '', notified_at TEXT NOT NULL DEFAULT '',
        deleted_at TEXT NOT NULL DEFAULT '',
        CHECK(state != 'completed' OR report_json != '' OR deleted_at != ''))''')
    conn.execute('CREATE INDEX companion_news_recent ON companion_news_tasks(created_at DESC,id DESC)')


class CompanionRepository(Store):
    """保存稳定任务 ID 和 attempt 条件更新，SQL 层不处理网络或 QWidget。"""
    def get_task(self, task_id):
        """读取一个独立行字典，供服务在事务内核准任务状态。"""
        row = self._conn.execute('SELECT * FROM companion_news_tasks WHERE id=?', (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit=200):
        """有界读取最近任务，避免历史内容无上限装入跨线程展示模型。"""
        limit = max(1, min(int(limit), 200))
        return [dict(row) for row in self._conn.execute(
            'SELECT * FROM companion_news_tasks ORDER BY created_at DESC,id DESC LIMIT ?', (limit,))]

    def insert_task(self, task_id, kind, fingerprint, day, at, run_id, now):
        """首次领取直接记录运行意图；进程意外结束后可保守识别为上次中断。"""
        self._conn.execute('''INSERT INTO companion_news_tasks
            (id,kind,planned_date,planned_time,config_fingerprint,state,attempt,run_id,created_at,started_at)
            VALUES(?,?,?,?,?,'running',1,?,?,?)''', (task_id, kind, day, at, fingerprint, run_id, now, now))

    def start_attempt(self, row, fingerprint, run_id, now):
        """从已核准的 waiting／显式重试终态进入新 attempt，保留原创建时间与任务 ID。"""
        return self._conn.execute('''UPDATE companion_news_tasks SET state='running', attempt=attempt+1,
            config_fingerprint=?,run_id=?,started_at=?,finished_at='',error_code='',report_json='',notified_at=''
            WHERE id=? AND attempt=? AND state=? AND deleted_at='' ''',
            (fingerprint, run_id, now, row['id'], row['attempt'], row['state'])).rowcount == 1

    def finish_attempt(self, claim, state, *, report_json='', error_code='', finished_at=''):
        """以 ID、attempt、进程与运行状态做 CAS，拒绝所有迟到或错误所有者回调。"""
        return self._conn.execute('''UPDATE companion_news_tasks SET state=?,report_json=?,error_code=?,finished_at=?
            WHERE id=? AND attempt=? AND run_id=? AND state='running' AND deleted_at='' ''',
            (state, report_json, error_code, finished_at, claim.task_id, claim.attempt, claim.run_id)).rowcount == 1

    def release_unstarted(self, claim):
        """仅对调用方已证明未启动网络的当前 claim 退让，旧 attempt 不再拥有更新资格。"""
        return self._conn.execute('''UPDATE companion_news_tasks SET state='waiting',started_at=''
            WHERE id=? AND attempt=? AND run_id=? AND state='running' AND deleted_at='' ''',
            (claim.task_id, claim.attempt, claim.run_id)).rowcount == 1

    def accept_notice(self, task_id, now):
        """为已完成且未删除的报告原子受理一次通知，屏幕展示由提交后的 UI 处理。"""
        return self._conn.execute('''UPDATE companion_news_tasks SET notified_at=?
            WHERE id=? AND state='completed' AND report_json!='' AND notified_at='' AND deleted_at='' ''',
            (now, task_id)).rowcount == 1

    def forget(self, task_id, now):
        """清除终态报告内容但保留墓碑，避免同日自动名额因删除被重新获得。"""
        return self._conn.execute('''UPDATE companion_news_tasks SET report_json='',deleted_at=?,notified_at=?
            WHERE id=? AND state IN ('completed','failed','cancelled','interrupted') AND deleted_at='' ''',
            (now, now, task_id)).rowcount == 1

    def recover(self, run_id, now):
        """把其他进程遗留的运行意图标为中断，不自动重放可能已产生费用的请求。"""
        return self._conn.execute('''UPDATE companion_news_tasks SET state='interrupted',
            error_code='interrupted',finished_at=? WHERE state='running' AND run_id!=?''', (now, run_id)).rowcount

    def prune(self, local_day, keep_task_id=''):
        """限制终态历史为最近三十日且最多百条，始终保留当日自动墓碑和在途任务。"""
        cutoff = (date.fromisoformat(local_day) - timedelta(days=29)).isoformat()
        terminal = "state IN ('completed','failed','cancelled','interrupted')"
        # waiting 仅表示未启动的准入退让，旧日已不可能自动执行，转换为可清理终态。
        changed = self._conn.execute("UPDATE companion_news_tasks SET state='cancelled',error_code='expired' WHERE state='waiting' AND planned_date<?", (local_day,)).rowcount
        changed += self._conn.execute(f'DELETE FROM companion_news_tasks WHERE {terminal} AND planned_date<? AND id!=?', (cutoff, keep_task_id)).rowcount
        protected = self._conn.execute(f"SELECT COUNT(*) FROM companion_news_tasks WHERE {terminal} AND ((kind='auto' AND planned_date=?) OR id=?)", (local_day, keep_task_id)).fetchone()[0]
        changed += self._conn.execute(f'''DELETE FROM companion_news_tasks WHERE id IN (
            SELECT id FROM companion_news_tasks WHERE {terminal} AND NOT(kind='auto' AND planned_date=?) AND id!=?
            ORDER BY created_at DESC,id DESC LIMIT -1 OFFSET ?)''', (local_day, keep_task_id, max(0, 100 - protected))).rowcount
        return changed
