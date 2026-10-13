"""Thread-safe counters and immutable snapshots. No SQL, Qt, or network access."""
from dataclasses import dataclass
from datetime import timedelta
import threading
from ...core.classifier import text_tw
from .clock import AppCalendar, SystemClock

@dataclass(frozen=True)
class TrackingSnapshot:
    day: str
    version: int
    captured_at: str
    typed: int
    deleted: int
    tw: int
    minutes_series: tuple
    lifetime: tuple

    def as_dict(self):
        life = dict(self.lifetime)
        count = len(self.minutes_series)
        return dict(day=self.day, version=self.version, captured_at=self.captured_at,
                    typed=self.typed, deleted=self.deleted, valid=max(0,self.typed-self.deleted),
                    tw=self.tw, minutes=count, avg_tw=self.tw/count if count else None,
                    accuracy=max(0,self.typed-self.deleted)/self.typed if self.typed else None,
                    minutes_series=self.minutes_series,
                    lifetime_typed=life['total_typed'], lifetime_deleted=life['total_deleted'],
                    lifetime_valid=max(0,life['total_typed']-life['total_deleted']),
                    lifetime_tw=life['total_tw'], lifetime_minutes=life['total_active_minutes'])

@dataclass(frozen=True)
class Checkpoint:
    version: int
    captured_at: str
    days: tuple
    minutes: tuple
    lifetime: tuple


class TrackingCounter:
    def __init__(self, balance, *, clock=None, start_hour=4, lifetime=None,
                 days=(), minutes=(), version=0):
        self._balance = balance
        self.clock = clock or SystemClock()
        self.calendar = AppCalendar(start_hour)
        self._lock = threading.RLock()
        self._version = version
        self._saved_version = version
        self._day = self.current_day()
        self._days = {d['date']: [d['typed_chars'], d['deleted_chars'], d['total_tw']] for d in days}
        self._days.setdefault(self._day, [0,0,0])
        self._minutes = {(r['date'],r['minute']): [r['typed_chars'],r['deleted_chars'],r['total_tw']] for r in minutes}
        self._life = {k: (lifetime or {}).get(k,0) for k in ('total_typed','total_deleted','total_tw','total_active_minutes')}
        self._day_dirty = {}
        self._minute_dirty = {}
        self._known_minutes = set(self._minutes)
        self._snapshot_cache = None
        self._save = None
        self._rollover_pending = False

    def current_day(self):
        return self.calendar.day(self.clock.now())

    def _roll_locked(self, now):
        day = self.calendar.day(now)
        if day != self._day:
            self._day = day
            self._days.setdefault(day,[0,0,0])
            self._rollover_pending = True
            self._snapshot_cache = None

    def _input(self, typed, deleted, tw):
        with self._lock:
            now = self.clock.now()
            self._roll_locked(now)
            key = (self._day,now.strftime('%H:%M'))
            if key not in self._known_minutes:
                self._known_minutes.add(key)
                self._life['total_active_minutes'] += 1
            minute = self._minutes.setdefault(key,[0,0,0])
            daily = self._days[self._day]
            for i,amount in enumerate((typed,deleted,tw)):
                minute[i] += amount
                daily[i] += amount
            self._life['total_typed'] += typed
            self._life['total_deleted'] += deleted
            self._life['total_tw'] += tw
            self._version += 1
            self._day_dirty[self._day] = self._version
            self._minute_dirty[key] = self._version
            self._snapshot_cache = None

    def handle_char(self, kind):
        self._input(1,0,1)
    def handle_ime(self, text):
        self._input(len(text),0,text_tw(text,self._balance))
    def handle_delete(self):
        self._input(0,1,0)

    def immutable_snapshot(self):
        with self._lock:
            self._roll_locked(self.clock.now())
            if self._snapshot_cache is None:
                typed,deleted,tw = self._days[self._day]
                series = tuple(sorted((key[1],v[2]) for key,v in self._minutes.items() if key[0]==self._day))
                self._snapshot_cache = TrackingSnapshot(self._day,self._version,self.clock.now().isoformat(),
                                                       typed,deleted,tw,series,tuple(self._life.items()))
            return self._snapshot_cache

    def snapshot(self):
        return self.immutable_snapshot().as_dict()
    def minute_series(self):
        return list(self.immutable_snapshot().minutes_series)
    def valid_chars(self):
        return self.snapshot()['valid']
    def accuracy(self):
        return self.snapshot()['accuracy']
    def avg_tw(self):
        return self.snapshot()['avg_tw']
    def lifetime_valid(self):
        return self.snapshot()['lifetime_valid']

    def prepare_checkpoint(self):
        with self._lock:
            if self._version <= self._saved_version:
                return None
            days = []
            for day in sorted(self._day_dirty):
                typed,deleted,tw = self._days[day]
                count = sum(key[0]==day for key in self._minutes)
                days.append((day,typed,deleted,max(0,typed-deleted),tw,count,
                             tw/count if count else None,max(0,typed-deleted)/typed if typed else None))
            minutes = tuple((day,minute,*self._minutes[(day,minute)]) for day,minute in sorted(self._minute_dirty))
            return Checkpoint(self._version,self.clock.now().isoformat(),tuple(days),minutes,tuple(self._life.items()))

    def acknowledge(self, checkpoint):
        with self._lock:
            self._saved_version = max(self._saved_version,checkpoint.version)
            self._day_dirty = {k:v for k,v in self._day_dirty.items() if v>checkpoint.version}
            self._minute_dirty = {k:v for k,v in self._minute_dirty.items() if v>checkpoint.version}

    def flush(self):
        checkpoint = self.prepare_checkpoint()
        if checkpoint is not None:
            if self._save is None:
                raise RuntimeError('No checkpoint sink installed')
            self._save(checkpoint)
            self.acknowledge(checkpoint)
        return checkpoint

    def check_rollover(self):
        with self._lock:
            self._roll_locked(self.clock.now())
            changed,self._rollover_pending = self._rollover_pending,False
        if changed and self._save is not None:
            self.flush()
        return changed

    def set_day_start(self, hour):
        with self._lock:
            self.calendar = AppCalendar(int(hour))
            self._roll_locked(self.clock.now())
            self._snapshot_cache = None
