"""Read-only reporting queries and bounded versioned in-process caching."""
from collections import OrderedDict
from copy import deepcopy

class QueryCache:
    def __init__(self,capacity=64):
        self.capacity=capacity
        self._values=OrderedDict()
    def get(self,key,load):
        if key not in self._values:
            self._values[key]=load()
            if len(self._values)>self.capacity:
                self._values.popitem(last=False)
        self._values.move_to_end(key)
        return deepcopy(self._values[key])
    def clear(self):
        self._values.clear()
