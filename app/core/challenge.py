"""Compatibility module alias."""
import sys
from ..modules.practice import domain as _implementation
sys.modules[__name__]=_implementation
