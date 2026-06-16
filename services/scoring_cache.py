"""
评分结果缓存 — 30 分钟内复用上次计算结果（线程安全）
"""
import threading
import time

_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()
CACHE_TTL = 1800  # 30 分钟


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


def get(key: str) -> dict | None:
    with _lock:
        entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def set(key: str, result: dict):
    with _lock:
        _cache[key] = (time.time(), result)


def invalidate():
    with _lock:
        _cache.clear()
