"""
评分结果缓存 — 30 分钟内复用上次计算结果
"""
import time

_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 1800  # 30 分钟


def cache_key(type_id: int, mode: str, hub: str, char_name: str) -> str:
    return f"{type_id}|{mode}|{hub}|{char_name}"


def get(key: str) -> dict | None:
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < CACHE_TTL:
        return entry[1]
    return None


def set(key: str, result: dict):
    _cache[key] = (time.time(), result)


def invalidate():
    _cache.clear()
