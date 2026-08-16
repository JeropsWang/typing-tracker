"""实时统计引擎。

层级：
- 当日（今日计数，日切后重置）
- 分钟（minute_stats，供每分钟正确率成就）
- 终身（lifetime，只有总量，无平均速度/正确率）

经验：每日打卡/连签由 CheckinService 结算；打字经验（每 1000 有效字）在
flush 时按千字块结算，受每日上限与经验加成卡（×2）影响。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta

from .classifier import text_tw


class StatsEngine:
    def __init__(self, repo, get_setting, balance):
        self.repo = repo
        self._get_setting = get_setting
        self._balance = balance
        self._lock = threading.Lock()
        # 日切起点在构造时读一次并缓存：钩子线程的回调只碰内存，
        # 绝不访问 SQLite（连接是主线程创建的，跨线程使用会抛异常）
        self._day_start_hour = int(get_setting(
            'day_start_hour', balance.get('day_start_hour', 4)))

        life = repo.get_lifetime() or {}
        self._lifetime = {
            'total_typed': life.get('total_typed', 0),
            'total_deleted': life.get('total_deleted', 0),
            'total_tw': life.get('total_tw', 0),
            'total_active_minutes': life.get('total_active_minutes', 0),
        }
        self._reset_day()

    # ---------- 日界 ----------
    def current_day(self) -> str:
        """按"新的一天起点"（默认凌晨 4 点）归属日期。

        纯内存计算：可在钩子线程安全调用（不触碰 SQLite）。
        """
        return (datetime.now() - timedelta(hours=self._day_start_hour)).date().isoformat()

    def update_day_start(self):
        """设置中修改日切起点后调用（主线程），刷新缓存并按需日切。"""
        self._day_start_hour = int(self._get_setting(
            'day_start_hour', self._balance.get('day_start_hour', 4)))
        self.check_rollover()

    def _reset_day(self):
        """主线程日常重置（flush 后调用，独立取锁）。"""
        with self._lock:
            self._reset_day_locked(self.current_day())

    def _reset_day_locked(self, day_iso):
        """持锁重置当日计数（钩子线程阻塞至多毫秒级，可接受）。"""
        self._day = day_iso
        self._typed = 0
        self._deleted = 0
        self._tw = 0
        self._minutes = {}          # (date, 'HH:MM') -> [typed, deleted, tw]
        self._min_flushed = set()
        self._exp_baseline = 0      # 当日已结算的千字块数
        self._daily_typing_exp = 0  # 当日已发打字经验（受每日上限约束）
        # 每日上限持久化到 settings：重启后从上次计数继续（曾仅存内存，
        # 重启 N 次可刷 N 倍经验，v0.8.9 修复）
        if self.repo.get_setting('typing_exp_date') != self._day:
            self.repo.set_setting('typing_exp_date', self._day)
            self.repo.set_setting('typing_exp_today', '0')
        else:
            self._daily_typing_exp = int(
                self.repo.get_setting('typing_exp_today', '0') or 0)

    # ---------- 事件入口（来自钩子线程） ----------
    def handle_char(self, kind):
        """非 IME 键：字母/数字/符号/空格，各计 1 字符、1 tw。"""
        with self._lock:
            self._typed += 1
            self._tw += 1
            self._lifetime['total_typed'] += 1
            self._lifetime['total_tw'] += 1
            self._mark_minute(1, 0, 1)

    def handle_ime(self, text):
        """IME 上屏文本：按字符实际换算（汉字 2tw、字母 1tw…）。"""
        tw = text_tw(text, self._balance)
        n = len(text)
        with self._lock:
            self._typed += n
            self._tw += tw
            self._lifetime['total_typed'] += n
            self._lifetime['total_tw'] += tw
            self._mark_minute(n, 0, tw)

    def handle_delete(self):
        with self._lock:
            self._deleted += 1
            self._lifetime['total_deleted'] += 1
            self._mark_minute(0, 1, 0)

    def _mark_minute(self, typed, deleted, tw):
        # 日期归属用 self._day（与当日计数器一致）：曾用 current_day()，
        # 日切轮询（30s）之前新日分钟键会与旧日计数器错位（v0.8.9 修复）；
        # 单次取 now，避免跨日/时钟跳变时日期与 HH:MM 不匹配
        now = datetime.now()
        key = (self._day, now.strftime('%H:%M'))
        rec = self._minutes.setdefault(key, [0, 0, 0])
        rec[0] += typed
        rec[1] += deleted
        rec[2] += tw

    # ---------- 派生指标 ----------
    def valid_chars(self) -> int:
        return max(0, self._typed - self._deleted)

    def accuracy(self):
        """日正确率 = 有效/输入；无输入返回 None。"""
        return self.valid_chars() / self._typed if self._typed else None

    def avg_tw(self):
        """日平均速度 tw/分 = 当日 tw / 有输入的分钟数。"""
        return self._tw / len(self._minutes) if self._minutes else None

    def lifetime_valid(self) -> int:
        return max(0, self._lifetime['total_typed'] - self._lifetime['total_deleted'])

    def minute_series(self):
        """今日逐分钟 tw 序列：[(HH:MM, tw), ...] 按时间排序（含未落盘数据）。"""
        with self._lock:
            items = [(k[1], v[2]) for k, v in self._minutes.items()]
        items.sort(key=lambda x: x[0])
        return items

    def snapshot(self) -> dict:
        with self._lock:
            return {
                'day': self._day,
                'typed': self._typed,
                'deleted': self._deleted,
                'valid': self.valid_chars(),
                'tw': self._tw,
                'minutes': len(self._minutes),
                'avg_tw': self.avg_tw(),
                'accuracy': self.accuracy(),
                'minutes_series': [(k[1], v[2]) for k, v in self._minutes.items()],
                'lifetime_typed': self._lifetime['total_typed'],
                'lifetime_deleted': self._lifetime['total_deleted'],
                'lifetime_valid': self.lifetime_valid(),
                'lifetime_tw': self._lifetime['total_tw'],
                'lifetime_minutes': self._lifetime['total_active_minutes'],
            }

    # ---------- 落盘 ----------
    def flush(self):
        """把未落盘的分钟/日/终身数据写入 SQLite（主线程定时调用）。

        分钟行每次全量 upsert（含进行中的分钟）：曾用 _min_flushed 跳过
        已写分钟，导致分钟内后续输入永不落库（欠计 ~90%，min_acc 成就
        与时段报表失真，v0.8.9 修复）。
        """
        with self._lock:
            daily, life, rows, new_minutes = self._flush_snapshot_locked()
        self._write_flush(daily, life, rows, new_minutes)

    def _flush_snapshot_locked(self):
        """持锁构建落盘快照；返回 (daily, life, minute_rows, 新增活跃分钟数)。"""
        rows = []
        new_minutes = 0
        for key, rec in self._minutes.items():
            rows.append((key[0], key[1], rec[0], rec[1], rec[2]))
            if key not in self._min_flushed:
                new_minutes += 1
        self._min_flushed.update(self._minutes.keys())
        self._lifetime['total_active_minutes'] += new_minutes
        daily = {
            'date': self._day,
            'typed_chars': self._typed,
            'deleted_chars': self._deleted,
            'valid_chars': self.valid_chars(),
            'total_tw': self._tw,
            'active_minutes': len(self._minutes),
            'avg_tw': self.avg_tw(),
            'accuracy': self.accuracy(),
        }
        life = dict(self._lifetime)
        typing_exp = self._grant_typing_exp_locked()
        return daily, life, rows, new_minutes

    def _write_flush(self, daily, life, rows, new_minutes):
        self.repo.upsert_daily(daily)
        self.repo.upsert_lifetime(life)
        if rows:
            self.repo.upsert_minutes(rows)
        # 分钟表滚动清理：只保留近 30 天（成就窗口只需 7 天；曾无限增长，
        # 一年 ~10 万行拖慢时段查询，v0.8.9 加入）
        try:
            cutoff = (datetime.now() - timedelta(days=30)).date().isoformat()
            self.repo.clean_minute_stats(cutoff)
        except Exception:
            pass

    def _grant_typing_exp_locked(self) -> int:
        """打字经验：每 1000 有效字 +per（每日上限 cap；经验加成卡生效 ×2）。

        必须在持锁状态下调用；返回本次发放的经验。
        """
        cfg = self._balance.get('typing_exp', {})
        per = cfg.get('per_1000_valid', 0)
        cap = cfg.get('daily_cap', 0)
        if per <= 0:
            return 0
        blocks = self.valid_chars() // 1000
        gained = (blocks - self._exp_baseline) * per
        if gained <= 0:
            return 0
        self._exp_baseline = blocks
        boost = self._boost_active()
        if boost:
            gained *= 2
        granted = min(gained, max(0, cap - self._daily_typing_exp))
        if granted > 0:
            self._daily_typing_exp += granted
            self.repo.add_exp(granted)
            self.repo.add_exp_to_daily(self._day, granted)
            self.repo.set_setting('typing_exp_today', str(self._daily_typing_exp))
        return granted

    def _boost_active(self) -> bool:
        raw = self._get_setting('exp_boost_until', '')
        if not raw:
            return False
        try:
            return datetime.fromisoformat(raw) > datetime.now()
        except ValueError:
            return False

    def check_rollover(self) -> bool:
        """日切：日期归属变化时归档并重置当日计数。

        归档与重置在同一把锁内完成：曾先释放锁写库再重新取锁重置，
        窗口期击键会计入旧日计数器后被清空（4 点附近丢键，v0.8.9 修复）。
        """
        d = self.current_day()
        if d != self._day:
            with self._lock:
                daily, life, rows, new_minutes = self._flush_snapshot_locked()
                self._reset_day_locked(d)
            self._write_flush(daily, life, rows, new_minutes)
            return True
        return False
