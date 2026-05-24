"""测试评分缓存"""
from services.scoring_cache import cache_key, get, invalidate, set


def test_cache_set_get():
    invalidate()
    key = cache_key(12345, "mfg", "Jita", "test")
    assert key == "12345|mfg|Jita|test"
    set(key, {"score": 50})
    result = get(key)
    assert result is not None
    assert result["score"] == 50


def test_cache_expiry():
    invalidate()
    key = cache_key(1, "trade", "Amarr", "test")
    set(key, {"score": 80})
    # 强制过期（通过 invalidate）
    invalidate()
    result = get(key)
    assert result is None
