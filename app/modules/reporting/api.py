"""Read-only reporting queries and bounded versioned in-process caching."""
from collections import OrderedDict
from copy import deepcopy

class QueryCache:
    """进程内有界 LRU 查询缓存，返回深拷贝以防 UI 修改污染后续查询。"""
    def __init__(self,capacity=64):
        """设置缓存容量并建立按访问顺序淘汰的结果集合。"""
        self.capacity=capacity
        self._values=OrderedDict()
    def get(self,key,load):
        """命中时更新访问顺序，未命中调用 load；超过容量淘汰最旧项并返回独立副本。"""
        if key not in self._values:
            self._values[key]=load()
            if len(self._values)>self.capacity:
                self._values.popitem(last=False)
        self._values.move_to_end(key)
        return deepcopy(self._values[key])
    def clear(self):
        """清空缓存，供统计表版本改变后的失效处理。"""
        self._values.clear()
