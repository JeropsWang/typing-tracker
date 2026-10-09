"""Continuous, bounded pose motion; no timers, screen moves or business events."""
import math
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class MotionFrame:
    x: float = 0
    y: float = 0
    angle: float = 0
    scale_x: float = 1
    scale_y: float = 1


class CharacterMotion:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.state = 'idle'
        self.token = None
        self._started = clock()
        self._last = self._started
        self._landed = -100
        self._drag_at = -100
        self._drag_delta = 0
        self.dragging = False
        self.frame = MotionFrame()

    def set_state(self, state, token=None, now=None):
        if (state, token) != (self.state, self.token):
            self.state, self.token = state, token
            self._started = self.clock() if now is None else now

    def set_drag(self, dx, now=None):
        self.dragging = True
        self._drag_delta = max(-50, min(50, dx))
        self._drag_at = self.clock() if now is None else now

    def release(self, now=None):
        self.dragging = False
        self._landed = self.clock() if now is None else now

    def reset(self, now=None):
        self._last = self._started = self.clock() if now is None else now
        self._landed = self._drag_at = -100
        self.dragging = False
        self.frame = MotionFrame()

    def sample(self, now=None):
        now = self.clock() if now is None else now
        dt = max(0, min(.25, now - self._last))
        self._last = now
        if not dt:
            return self.frame
        t = max(0, now - self._started)
        s = math.sin
        x, y, angle, sx, sy = 0, s(t * 1.9) * .8, s(t * 1.1) * .6, 1, 1 + s(t * 1.9) * .009
        if self.state == 'focused':
            y, angle, sy = s(t * 1.8) * .35, s(t) * .25, 1 + s(t * 1.8) * .004
        elif self.state in ('happy', 'cheering', 'celebrating'):
            amplitude = {'happy': 4, 'cheering': 5.5, 'celebrating': 7}[self.state]
            hop = max(0, s(t * 4.8))
            y, angle = -amplitude * hop, s(t * 2.4) * 2.4
            sx, sy = 1 - hop * .016, 1 + hop * .025
        elif self.state == 'shy':
            x, angle = s(t * 1.6) * 1.7, s(t * 1.6) * 2.1
        elif self.state == 'proud':
            y, angle = -1 + s(t * 1.8), -1.8 + s(t * 1.3) * .8
        elif self.state == 'pout':
            shake = s(t * 8) * math.exp(-(t % 4) * 2)
            x, angle = shake * 2.6, shake * 2.6
        elif self.state == 'sleepy':
            nod = (1 - math.cos(t * 1.2)) / 2
            y, angle, sy = nod * 1.8, nod * 2.2, 1 - nod * .012
        elif self.state == 'surprised':
            recoil = math.exp(-t * 2.5)
            y, angle = -6 * abs(s(t * 7)) * recoil, s(t * 8) * 4 * recoil
            sx, sy = 1 - recoil * .025, 1 + recoil * .035
        if self.dragging:
            velocity = self._drag_delta * math.exp(-max(0, now - self._drag_at) * 5)
            x, y, angle, sx, sy = velocity * .04, -2, velocity * .14, 1.015, .99
        else:
            land = max(0, now - self._landed)
            bounce = math.sin(land * 13) * math.exp(-land * 6)
            y += bounce * 2.5
            sx += bounce * .018
            sy -= bounce * .022
        target = MotionFrame(x, y, angle, sx, sy)
        alpha = 1 - math.exp(-dt / .09)
        self.frame = MotionFrame(*(getattr(self.frame, key) +
                                   (getattr(target, key) - getattr(self.frame, key)) * alpha
                                   for key in ('x', 'y', 'angle', 'scale_x', 'scale_y')))
        return self.frame
