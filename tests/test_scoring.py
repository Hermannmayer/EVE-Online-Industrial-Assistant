"""评分服务集成测试 — 使用临时数据库"""

import pytest

from core.cache import TtlLRUCache
from services.scoring_service import ScoringService

DEFAULT_SKILLS = {"工业理论": 5, "高级工业理论": 5, "经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5}


class TestManufacturingScore:
    def test_profitable_item(self, temp_db):
        """渡鸦级应产出正利润"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config={"skills": DEFAULT_SKILLS},
            mat_source_hub="Jita",
            sell_hub="Jita",
            price_type_mat="sell",
            price_type_prod="sell",
        )
        assert result["status"] == ""
        assert result["score"] > 0
        assert result["profit_per_run"] > 0
        assert result["margin_pct"] > 0
        assert "materials" in result
        assert len(result["materials"]) == 2

    def test_no_blueprint_returns_status(self, temp_db):
        """无蓝图的物品返回 'no_blueprint'"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=99999,
            char_config={"skills": DEFAULT_SKILLS},
        )
        assert result["status"] == "no_blueprint"
        assert result["score"] == 0.0

    def test_me_reduces_waste(self, temp_db):
        """ME 10 材料用量应少于 ME 0"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result_me0 = svc.calc_manufacturing_score(
            type_id=2002,
            char_config={"skills": DEFAULT_SKILLS},
            bp_me=0,
            mat_source_hub="Jita",
            sell_hub="Jita",
        )
        result_me10 = svc.calc_manufacturing_score(
            type_id=2002,
            char_config={"skills": DEFAULT_SKILLS},
            bp_me=10,
            mat_source_hub="Jita",
            sell_hub="Jita",
        )
        me0_qty = result_me0["materials"][0]["qty"]
        me10_qty = result_me10["materials"][0]["qty"]
        # ME10 材料用量应少于 ME0
        assert me0_qty > me10_qty
        # waste_factor 在材料列表中，不在 breakdown 中
        assert "wastefactor" in result_me10["materials"][0]

    def test_unprofitable_scores_zero(self, temp_db):
        """材料成本超成品售价时 score 为 0"""
        # 把渡鸦级卖价压到极低，但材料价保持高位 → 必然亏本
        mkt = temp_db.direct_connect("mkt")
        mkt.execute("UPDATE market_prices SET sell_price = 1 WHERE type_id = 2001 AND region_id = 10000002")
        mkt.commit()
        mkt.close()

        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config={"skills": DEFAULT_SKILLS},
            mat_source_hub="Jita",
            sell_hub="Jita",
            price_type_mat="sell",
            price_type_prod="sell",
        )
        assert result["status"] == ""
        assert result["score"] == 0.0
        assert result["profit_per_run"] <= 0


class TestTradeScore:
    def test_basic_trade(self, temp_db):
        """基本贸易评分计算"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_trade_score(
            type_id=2002,
            buy_hub="Jita",
            sell_hub="Jita",
            char_config={"skills": DEFAULT_SKILLS},
        )
        assert result["status"] == ""
        assert result["score"] >= 0
        assert result["buy_cost"] > 0
        assert result["sell_revenue"] > 0

    def test_no_price_returns_status(self, temp_db):
        """无价格的物品返回 'no_price'"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_trade_score(
            type_id=99999,
            char_config={"skills": DEFAULT_SKILLS},
        )
        assert result["status"] == "no_price"


class TestCache:
    def test_get_set_and_ttl(self):
        """缓存写入和读取"""
        cache = TtlLRUCache(max_size=10, ttl_seconds=3600)
        cache.set("key1", {"a": 1})
        assert cache.get("key1") == {"a": 1}

    def test_expired_returns_none(self):
        """过期缓存返回 None"""
        cache = TtlLRUCache(max_size=10, ttl_seconds=-1)  # 立即过期
        cache.set("key1", {"a": 1})
        assert cache.get("key1") is None

    def test_max_size_eviction(self):
        """超 max_size 淘汰最旧条目"""
        cache = TtlLRUCache(max_size=3, ttl_seconds=3600)
        for i in range(5):
            cache.set(f"key{i}", {"i": i})
        assert cache.get("key0") is None  # 最旧被淘汰
        assert cache.get("key4") == {"i": 4}
        assert len(cache) <= 3

    def test_invalidate(self):
        """清空缓存"""
        cache = TtlLRUCache(max_size=10)
        cache.set("k", {"v": 1})
        cache.invalidate()
        assert cache.get("k") is None


@pytest.mark.parametrize("me,te,expected_min_score", [(0, 0, 50), (5, 5, 60), (10, 20, 70)])
def test_manufacturing_me_te_param(temp_db, me, te, expected_min_score):
    """ME/TE 越高，综合评分下限越高"""
    cache = TtlLRUCache(max_size=10)
    svc = ScoringService(temp_db, cache)
    result = svc.calc_manufacturing_score(
        type_id=2001,
        char_config={"skills": DEFAULT_SKILLS},
        bp_me=me,
        bp_te=te,
        mat_source_hub="Jita",
        sell_hub="Jita",
    )
    assert result["status"] == ""
    assert result["score"] >= expected_min_score


def test_profitable_trade_score_above_min(temp_db):
    """有利可图的贸易评分应大于 0，且 sell_revenue > buy_cost"""
    cache = TtlLRUCache(max_size=10)
    svc = ScoringService(temp_db, cache)
    result = svc.calc_trade_score(
        type_id=2002,
        buy_hub="Jita",
        sell_hub="Jita",
        char_config={"skills": DEFAULT_SKILLS},
    )
    assert result["score"] >= 0
    assert result["buy_cost"] > 0
    assert result["sell_revenue"] > result["buy_cost"]


def test_manufacturing_breakdown_keys(temp_db):
    """制造评分 breakdown 应包含所有关键子项"""
    cache = TtlLRUCache(max_size=10)
    svc = ScoringService(temp_db, cache)
    result = svc.calc_manufacturing_score(
        type_id=2001,
        char_config={"skills": DEFAULT_SKILLS},
        mat_source_hub="Jita",
        sell_hub="Jita",
    )
    assert "profit_score" in result["breakdown"]
    assert "volume_score" in result["breakdown"]
    assert "efficiency_score" in result["breakdown"]
    assert "material_cost" in result["breakdown"]


@pytest.mark.parametrize("invalid_price_type", ["nonexistent", "invalid", ""])
def test_price_type_nonexistent(temp_db, invalid_price_type):
    """不存在的价格类型应返回 no_price 状态（score=0, status='no_price'）"""
    cache = TtlLRUCache(max_size=10)
    svc = ScoringService(temp_db, cache)
    result = svc.calc_manufacturing_score(
        type_id=2001,
        char_config={"skills": DEFAULT_SKILLS},
        mat_source_hub="Jita",
        sell_hub="Jita",
        price_type_mat="sell",
        price_type_prod=invalid_price_type,
    )
    # 产品价格使用无效类型 → get_price 返回 None → 标记 no_price
    assert result["status"] == "no_price", f"expected no_price for price_type={invalid_price_type!r}"
    assert result["score"] == 0.0
    assert result["profit_per_run"] == 0.0


def test_price_type_nonexistent_trade(temp_db):
    """贸易评分中不存在的价格类型应返回 no_price 状态"""
    cache = TtlLRUCache(max_size=10)
    svc = ScoringService(temp_db, cache)
    result = svc.calc_trade_score(
        type_id=2002,
        buy_hub="Jita",
        sell_hub="Jita",
        buy_price_type="nonexistent",
        sell_price_type="sell",
        char_config={"skills": DEFAULT_SKILLS},
    )
    assert result["status"] == "no_price"
    assert result["score"] == 0.0
    assert result["buy_cost"] == 0.0
