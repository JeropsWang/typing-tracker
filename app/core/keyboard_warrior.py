"""Compatibility module alias."""
import sys
from ..modules.practice import keyboard_session as _implementation
sys.modules[__name__]=_implementation
