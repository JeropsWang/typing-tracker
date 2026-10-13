"""Compatibility module alias; implementation belongs to english."""
import sys
from ..modules.english import scoring as _implementation
sys.modules[__name__]=_implementation
