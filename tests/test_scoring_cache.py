"""测试评分缓存"""

from services.scoring import cache_key, get_cache, invalidate_cache, set_cache


def test_cache_set_get():
    invalidate_cache()
    key = cache_key(12345, "mfg", "Jita", "test")
    assert key == "12345|mfg|Jita|test"
    set_cache(key, {"score": 50})
    result = get_cache(key)
    assert result is not None
    assert result["score"] == 50


def test_cache_expiry():
    invalidate_cache()
    key = cache_key(1, "trade", "Amarr", "test")
    set_cache(key, {"score": 80})
    # 强制过期（通过 invalidate）
    invalidate_cache()
    result = get_cache(key)
    assert result is None
