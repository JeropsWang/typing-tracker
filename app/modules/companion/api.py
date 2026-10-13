from dataclasses import dataclass
from ..growth.api import level_and_progress, GrowthSummary
from .models import CompanionEvent, STATES, PLACEHOLDERS, format_line
from .runtime import Runtime, REACTIONS
from .packs import PackStore, LoadedPack, Sprite, DEFAULT_PACK, BUILTIN_DIR
from .validation import validate_manifest, safe_path, image_size, MAX_FILE, MAX_FILES, MAX_TOTAL

@dataclass(frozen=True)
class ActivityState:
    day: str
    typed: int
    practicing: bool

class ActivityProvider:
    def __init__(self,counter,queries,balance):
        self.counter,self.queries,self.balance=counter,queries,balance
        self._running=set()
    def set_practicing(self,source,running):
        if running:
            self._running.add(source)
        else:
            self._running.discard(source)
    def activity(self):
        snap=self.counter.snapshot()
        return ActivityState(snap['day'],snap['typed'],bool(self._running))
    def growth(self):
        day=self.counter.current_day()
        return GrowthSummary(level_and_progress(self.queries.get_exp(),self.balance)[0],self.queries.get_streak(day))
