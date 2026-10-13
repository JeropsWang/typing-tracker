"""Compatibility module alias for existing tools."""
import sys
from ..integrations.ai import protocol as _implementation
sys.modules[__name__] = _implementation
