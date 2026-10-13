"""Stable vocabulary shared by the runtime, rendering and workshop."""
from dataclasses import dataclass, field

STATES = {
    'idle': '待机', 'focused': '专注', 'happy': '开心', 'proud': '得意',
    'shy': '害羞', 'pout': '委屈', 'sleepy': '困困', 'surprised': '震惊',
    'cheering': '鼓励', 'celebrating': '庆祝',
}
FREQUENCIES = {'quiet': (480, 720), 'normal': (240, 420), 'lively': (120, 240)}
PLACEHOLDERS = frozenset(('nickname', 'level', 'speed', 'accuracy', 'streak'))


@dataclass(frozen=True)
class CompanionEvent:
    kind: str
    payload: dict = field(default_factory=dict)
    event_id: str = ''


@dataclass(frozen=True)
class Pose:
    state: str
    kind: str = 'base'
    token: int = 0
    bubble: bool = False
    payload: dict = field(default_factory=dict)


def format_line(line: str, values: dict) -> str:
    """Only literal, validated field names; no attribute access or expressions."""
    import re
    return re.sub(r'\{([a-z]+)\}', lambda m: str(
        values[m[1]] if values.get(m[1]) is not None else '暂无数据'), line)
