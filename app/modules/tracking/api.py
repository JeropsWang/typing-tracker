"""统计模块公开入口，导出可注入时钟、计数快照、检查点及服务，统一 text_tw 计量。"""
from .clock import Clock, SystemClock, AppCalendar
from .domain import TrackingCounter, TrackingSnapshot, Checkpoint
from .application import TrackingService

from ...core.classifier import text_tw
