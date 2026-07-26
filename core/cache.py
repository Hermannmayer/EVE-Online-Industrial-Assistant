"""
通用 LRU + TTL 缓存 — 线程安全，支持过期被动清理和 LRU 淘汰
"""

import threading
import time
from collections import OrderedDict
from typing import Any


class TtlLRUCache:
    """线程安全的有界缓存，过期被动清理 + LRU 淘汰"""

    def __init__(self, max_size: int = 500, ttl_seconds: int = 1800):
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
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

    def set(self, key: str, value: Any):
        with self._lock:
            self._evict_expired_locked()
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.time(), value)
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
