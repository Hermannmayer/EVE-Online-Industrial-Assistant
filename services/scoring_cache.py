"""
评分结果缓存 — 30 分钟 TTL，有界 LRU 淘汰（线程安全）
"""

import threading
import time
from collections import OrderedDict


class ScoringCache:
    """线程安全的有界评分缓存，过期被动清理 + LRU 淘汰"""

    def __init__(self, max_size: int = 500, ttl: int = 1800):
        self._cache: OrderedDict[str, tuple[float, dict]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            self._evict_expired_locked()
            entry = self._cache.get(key)
            if entry is None:
                return None
            timestamp, result = entry
            if time.time() - timestamp >= self._ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return result

    def set(self, key: str, result: dict):
        with self._lock:
            self._evict_expired_locked()
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), result)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def invalidate(self):
        with self._lock:
            self._cache.clear()

    def _evict_expired_locked(self):
        cutoff = time.time() - self._ttl
        expired = [k for k, (ts, _) in self._cache.items() if ts < cutoff]
        for k in expired:
            del self._cache[k]

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


# 兼容层：模块级函数委托给默认实例
_default = ScoringCache()


def get(key: str) -> dict | None:
    return _default.get(key)


def set(key: str, result: dict):
    _default.set(key, result)


def invalidate():
    _default.invalidate()
