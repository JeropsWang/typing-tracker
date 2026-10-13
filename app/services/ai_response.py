"""Compatibility module alias for existing tools."""
import sys
from ..integrations.ai import response as _implementation
sys.modules[__name__] = _implementation
