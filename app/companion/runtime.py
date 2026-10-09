"""Monotonic, deterministic decisions; never touches Qt, disk or the keyboard."""
import random
import time
from collections import deque

from .models import CompanionEvent, FREQUENCIES, Pose

REACTIONS = {
    'pet': ('shy', 5), 'poke': ('pout', 5), 'double_click': ('surprised', 5),
    'level': ('celebrating', 4), 'achievement': ('celebrating', 4),
    'record': ('proud', 3), 'finished': ('happy', 2),
    'encourage': ('cheering', 2), 'checkin': ('happy', 2), 'meme': ('surprised', 0),
}


class Runtime:
    def __init__(self, clock=time.monotonic, rng=None):
        self.clock = clock
        self.rng = rng or random.Random()
        self.visible = False
        self.practicing = False
        self.frequency = 'normal'
        self._baseline = None
        self._last_input = clock()
        self._has_input = False
        self._pose = None
        self._priority = -1
        self._expires = 0
        self._reaction_started = 0
        self._bubble_until = 0
        self._token = 0
        self._seen = deque(maxlen=128)
        self._schedule()

    def _schedule(self):
        bounds = FREQUENCIES.get(self.frequency)
        self.next_random = self.clock() + self.rng.uniform(*bounds) if bounds else float('inf')

    def set_frequency(self, value):
        self.frequency = value if value in (*FREQUENCIES, 'off') else 'normal'
        self._schedule()

    def set_visible(self, visible):
        if self.visible != visible:
            self.visible = visible
            self._schedule()
            if not visible:
                self._pose = None

    def update_activity(self, day, typed, practicing):
        now = self.clock()
        if self.practicing != practicing:
            self.practicing = practicing
            self._schedule()
            if practicing and self._priority < 5:
                self._pose = None
        previous = self._baseline
        if previous and day == previous[0] and typed > previous[1]:
            self._last_input = now
            self._has_input = True
        elif previous and (day != previous[0] or typed < previous[1]):
            self._has_input = False
            self._last_input = now
        self._baseline = (day, typed)

    def react(self, event: CompanionEvent, duration=6):
        if event.kind not in REACTIONS:
            return False
        if event.event_id:
            if event.event_id in self._seen:
                return False
            self._seen.append(event.event_id)
        if not self.visible:
            return False
        state, priority = REACTIONS[event.kind]
        if self.practicing and priority < 5:
            return False
        now = self.clock()
        if self._pose and now < self._expires and priority < self._priority:
            return False
        # Collapse simultaneous reward notifications into the existing celebration.
        if (self._pose and self._pose.state == state == 'celebrating'
                and now < self._expires):
            return False
        self._token += 1
        self._priority = priority
        self._reaction_started = now
        self._expires = now + duration
        self._bubble_until = now + min(duration, 5)
        self._pose = Pose(state, event.kind, self._token, True, dict(event.payload))
        return True

    def set_reaction_duration(self, duration):
        if self._pose:
            duration = max(1, min(30, duration))
            self._expires = self._reaction_started + duration
            self._bubble_until = self._reaction_started + min(duration, 5)

    def sample(self):
        now = self.clock()
        if self._pose and now >= self._expires:
            self._pose = None
        if self.visible and not self.practicing and not self._pose and now >= self.next_random:
            self.react(CompanionEvent('meme'))
            self._schedule()
        if self._pose:
            p = self._pose
            return Pose(p.state, p.kind, p.token, now < self._bubble_until, p.payload)
        elapsed = now - self._last_input
        state = ('focused' if self.practicing or (self._has_input and elapsed < 3)
                 else 'sleepy' if elapsed >= 300 else 'idle')
        return Pose(state, token=self._token)
