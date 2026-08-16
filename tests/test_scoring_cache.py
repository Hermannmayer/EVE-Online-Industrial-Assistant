"""测试评分缓存 — 现基于 core.cache.TtlLRUCache"""

from collections.abc import Callable

import pytest

import services.scoring_service as ss
from core.cache import TtlLRUCache

# 模块级 patch 的符号（测试桩替换后必须恢复，避免污染其他测试文件）
_PATCHED_SYMBOLS = ("get_price", "get_adjusted_price", "get_volume", "get_system_cost_index")


@pytest.fixture(autouse=True)
def _restore_module_symbols():
    """每个测试结束后恢复被桩替换的 scoring_service 模块级函数"""
    originals = {name: getattr(ss, name) for name in _PATCHED_SYMBOLS}
    yield
    for name, orig in originals.items():
        setattr(ss, name, orig)


def _patch_module_stubs(stubs: dict[str, Callable]):
    """用桩替换模块级函数（由 autouse fixture 负责恢复）"""
    for name, stub in stubs.items():
        setattr(ss, name, stub)


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


# ── ScoringService 缓存接线（审计发现：get_cache/set_cache 曾为零调用的死代码） ──


def _make_mfg_svc(cache):
    """构造 ScoringService 子类：桩掉数据访问，跑真实缓存逻辑"""
    import sqlite3

    import services.scoring_service as ss

    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER, quantity INTEGER);
        CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER);
        CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, material_type_id INTEGER, quantity INTEGER, wastefactor INTEGER DEFAULT 10);
        """
    )
    db.execute("INSERT INTO blueprint_products VALUES (1, 'manufacturing', 12345, 1)")
    db.execute("INSERT INTO blueprint_activities VALUES (1, 'manufacturing', 1000)")
    db.execute("INSERT INTO blueprint_materials VALUES (1, 'manufacturing', 34, 10, 10)")
    db.commit()

    class FakeConnMgr:
        def connect(self, *_names):
            return db

    class FakeSvc(ss.ScoringService):
        def __init__(self):
            super().__init__(db=FakeConnMgr(), cache=cache)  # type: ignore[arg-type]

    # 桩函数（模块级签名，patch 后由模块级 get_price(...) 直接调用）
    def _stub_get_price(type_id, price_type, hub=None, _db=None):
        # 产品(12345)高价 2000，材料(34)低价 100 → 正利润（覆盖安装费约 92 ISK）
        return 2000.0 if type_id == 12345 else 100.0

    def _stub_get_adjusted_price(type_id, _db=None):
        return 100.0

    def _stub_get_volume(type_id, vol_type="total", hub=None, _db=None):
        return 10000

    def _stub_get_sci(system_id, activity="manufacturing", _db=None, hub="Jita"):
        return 0.05

    for name, stub in (
        ("get_price", _stub_get_price),
        ("get_adjusted_price", _stub_get_adjusted_price),
        ("get_volume", _stub_get_volume),
        ("get_system_cost_index", _stub_get_sci),
    ):
        _patch_module_stubs({name: stub})

    return FakeSvc()


def test_manufacturing_score_caches_result():
    """calc_manufacturing_score 成功结果应写入缓存（二次调用命中，不重算）"""
    import services.scoring_service as ss

    cache = TtlLRUCache(max_size=100, ttl_seconds=3600)
    svc = _make_mfg_svc(cache)

    # 通过 get_blueprint_materials 调用计数验证真实方法是否重算
    orig_gbm = ss.get_blueprint_materials
    calls = {"n": 0}

    def _counting_gbm(conn, bp_id):
        calls["n"] += 1
        return orig_gbm(conn, bp_id)

    ss.get_blueprint_materials = _counting_gbm
    try:
        r1 = svc.calc_manufacturing_score(12345, {}, mat_source_hub="Jita", sell_hub="Jita", bp_me=0, bp_te=0)
        r2 = svc.calc_manufacturing_score(12345, {}, mat_source_hub="Jita", sell_hub="Jita", bp_me=0, bp_te=0)
    finally:
        ss.get_blueprint_materials = orig_gbm

    assert r1["score"] > 0
    assert r2["score"] > 0
    assert calls["n"] == 1, "第二次调用应命中缓存（不重算）"


def test_manufacturing_score_does_not_cache_failure():
    """失败结果（status=no_price）不应写入缓存"""
    import services.scoring_service as ss

    cache = TtlLRUCache(max_size=100, ttl_seconds=3600)
    svc = ss.ScoringService(db=None, cache=cache)  # type: ignore[arg-type]
    orig = ss.ScoringService.calc_manufacturing_score

    def _failed(self, *args, **kwargs):
        return {"score": 0.0, "status": "no_price"}

    ss.ScoringService.calc_manufacturing_score = _failed  # type: ignore[method-assign]
    try:
        svc.calc_manufacturing_score(1, {})
    finally:
        ss.ScoringService.calc_manufacturing_score = orig

    assert len(cache) == 0, "失败结果不应被缓存"


def test_invalidate_cache_clears_after_price_update():
    """价格更新后 invalidate_cache 应清空缓存（联动：main_window 回调）"""
    import services.scoring_service as ss

    cache = TtlLRUCache(max_size=100, ttl_seconds=3600)
    svc = ss.ScoringService(db=None, cache=cache)  # type: ignore[arg-type]
    cache.set("k1", {"score": 1.0})
    cache.set("k2", {"score": 2.0})

    svc.invalidate_cache()

    assert cache.get("k1") is None
    assert cache.get("k2") is None


def test_trade_score_caches_result():
    """calc_trade_score 成功结果应写入缓存（桩掉数据访问，跑真实方法）"""
    import sqlite3

    import services.scoring_service as ss

    cache = TtlLRUCache(max_size=100, ttl_seconds=3600)

    db = sqlite3.connect(":memory:")
    db.executescript(
        """
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, volume REAL);
        """
    )
    db.execute("INSERT INTO item VALUES (12345, 0.5)")
    db.commit()

    class FakeConnMgr:
        def connect(self, *_names):
            return db

    class FakeSvc(ss.ScoringService):
        def __init__(self):
            super().__init__(db=FakeConnMgr(), cache=cache)  # type: ignore[arg-type]

    calls = {"n": 0}

    # 桩函数（模块级签名）
    def _stub_get_price(type_id, price_type, hub=None, _db=None):
        calls["n"] += 1
        # 买入价 100（买），卖出价 200（卖）→ 正毛利
        return 100.0 if price_type == "buy" else 200.0

    def _stub_get_volume(type_id, vol_type="total", hub=None, _db=None):
        return 10000

    for name, stub in (("get_price", _stub_get_price), ("get_volume", _stub_get_volume)):
        _patch_module_stubs({name: stub})

    svc = FakeSvc()
    r1 = svc.calc_trade_score(12345, "Jita", "Jita", char_config={})
    calls_after_first = calls["n"]
    r2 = svc.calc_trade_score(12345, "Jita", "Jita", char_config={})
    assert r1["score"] > 0
    assert r2["score"] > 0
    # 成功结果应写入缓存；二次调用命中（不重新取价）
    assert len(cache) == 1, "成功结果应写入缓存"
    assert calls["n"] == calls_after_first, "二次调用应命中缓存（不重新取价）"
