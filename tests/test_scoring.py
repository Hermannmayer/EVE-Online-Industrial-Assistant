"""评分服务集成测试 — 使用临时数据库"""

from services.scoring_cache import ScoringCache
from services.scoring_service import ScoringService

DEFAULT_SKILLS = {"工业理论": 5, "高级工业理论": 5, "经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5}


class TestManufacturingScore:
    def test_profitable_item(self, temp_db):
        """渡鸦级应产出正利润"""
        cache = ScoringCache(max_size=10)
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
        cache = ScoringCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=99999,
            char_config={"skills": DEFAULT_SKILLS},
        )
        assert result["status"] == "no_blueprint"
        assert result["score"] == 0.0

    def test_me_reduces_waste(self, temp_db):
        """ME 10 应消除材料浪费 (waste_factor=1.0)"""
        cache = ScoringCache(max_size=10)
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
        # ME10 材料用量应为 base_qty（浪费因子 1.0）
        assert me0_qty > me10_qty
        assert result_me10["breakdown"]["waste_factor"] == 1.0

    def test_unprofitable_scores_zero(self, temp_db):
        """材料成本超成品售价时 score 为 0"""
        # 把渡鸦级卖价压到极低，但材料价保持高位 → 必然亏本
        mkt = temp_db.direct_connect("mkt")
        mkt.execute("UPDATE market_prices SET sell_price = 1 WHERE type_id = 2001 AND region_id = 10000002")
        mkt.commit()
        mkt.close()

        cache = ScoringCache(max_size=10)
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
        cache = ScoringCache(max_size=10)
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
        cache = ScoringCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_trade_score(
            type_id=99999,
            char_config={"skills": DEFAULT_SKILLS},
        )
        assert result["status"] == "no_price"


class TestCache:
    def test_get_set_and_ttl(self):
        """缓存写入和读取"""
        cache = ScoringCache(max_size=10, ttl=3600)
        cache.set("key1", {"a": 1})
        assert cache.get("key1") == {"a": 1}

    def test_expired_returns_none(self):
        """过期缓存返回 None"""
        cache = ScoringCache(max_size=10, ttl=-1)  # 立即过期
        cache.set("key1", {"a": 1})
        assert cache.get("key1") is None

    def test_max_size_eviction(self):
        """超 max_size 淘汰最旧条目"""
        cache = ScoringCache(max_size=3, ttl=3600)
        for i in range(5):
            cache.set(f"key{i}", {"i": i})
        assert cache.get("key0") is None  # 最旧被淘汰
        assert cache.get("key4") == {"i": 4}
        assert len(cache) <= 3

    def test_invalidate(self):
        """清空缓存"""
        cache = ScoringCache(max_size=10)
        cache.set("k", {"v": 1})
        cache.invalidate()
        assert cache.get("k") is None
