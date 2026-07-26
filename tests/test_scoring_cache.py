"""测试评分缓存 — 现基于 core.cache.TtlLRUCache"""

from core.cache import TtlLRUCache


def test_cache_set_get():
    cache = TtlLRUCache(max_size=500, ttl_seconds=3600)
    key = "12345|mfg|Jita|test"
    assert key == "12345|mfg|Jita|test"
    cache.set(key, {"score": 50})
    assert cache.get(key) == {"score": 50}


def test_cache_miss():
    cache = TtlLRUCache(max_size=500, ttl_seconds=3600)
    assert cache.get("nonexistent") is None


def test_cache_invalidate():
    cache = TtlLRUCache(max_size=500, ttl_seconds=3600)
    cache.set("k1", 1)
    cache.set("k2", 2)
    cache.invalidate()
    assert cache.get("k1") is None
    assert cache.get("k2") is None


def test_cache_lru_eviction():
    cache = TtlLRUCache(max_size=3, ttl_seconds=3600)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.set("c", 3)
    cache.set("d", 4)  # should evict "a"
    assert cache.get("a") is None  # evicted
    assert cache.get("b") == 2
    assert cache.get("d") == 4


def test_cache_len():
    cache = TtlLRUCache(max_size=100, ttl_seconds=3600)
    assert len(cache) == 0
    cache.set("a", 1)
    assert len(cache) == 1
    cache.set("b", 2)
    assert len(cache) == 2
