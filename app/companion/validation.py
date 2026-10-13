"""Compatibility module alias; implementation belongs to companion."""
import sys
from ..modules.companion import validation as _implementation
sys.modules[__name__]=_implementation
