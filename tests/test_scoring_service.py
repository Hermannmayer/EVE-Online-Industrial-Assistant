"""评分服务精细化测试 — 覆盖 test_scoring.py 未触及的分支

覆盖目标:
  - 经纪人费率/改单折扣/销售税的独立单元测试（私有方法直接调用）
  - 贸易评分全路径（正利润分支，含 score/margin/profit_per_m3）
  - char_config=None / {} 时 ScoringService 的默认行为（技能用 fallback 值）
"""

from core.cache import TtlLRUCache
from services.scoring_service import ScoringService


class TestBrokerCalculations:
    """经纪人费率/改单折扣/销售税 独立计算"""

    def test_calc_broker_rate_default(self, temp_db):
        """默认声望(5.0/5.0) + 经纪人关系学 0级 → 0.5%"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        rate = svc._calc_broker_rate({}, {})
        # standing_factor = 2^(0.14*5 + 0.06*5) = 2^1 = 2
        # rate = (1.0 - 0.05*0) / 2 = 0.5
        assert rate == 0.5

    def test_calc_broker_rate_custom(self, temp_db):
        """高声望 + 满技能 → 费率明显低于默认（< 0.35%）"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        skills = {"经纪人关系学": 5}
        market_data = {"faction_standing": 9.0, "corp_standing": 8.0}
        rate = svc._calc_broker_rate(skills, market_data)
        # standing_factor = 2^(0.14*9 + 0.06*8) ≈ 3.34
        # rate = (1.0 - 0.05*5) / 3.34 = 0.75 / 3.34 ≈ 0.225
        assert 0.1 <= rate < 0.35

    def test_calc_relist_discount(self, temp_db):
        """改单折扣 = min(50 + 高级经纪人关系学*5, 100)"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        assert svc._calc_relist_discount({"高级经纪人关系学": 5}) == 75.0
        assert svc._calc_relist_discount({"高级经纪人关系学": 0}) == 50.0
        assert svc._calc_relist_discount({"高级经纪人关系学": 10}) == 100.0
        assert svc._calc_relist_discount({}) == 50.0

    def test_calc_sales_tax_rate(self, temp_db):
        """销售税 = 2% * (1 - 0.03 * 会计学)"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        assert svc._calc_sales_tax_rate({"会计学": 5}) == 1.7
        assert svc._calc_sales_tax_rate({"会计学": 0}) == 2.0
        assert svc._calc_sales_tax_rate({}) == 2.0


class TestManufacturingEdgeCases:
    """制造评分 — 缺省/空角色配置时的默认行为"""

    def test_manufacturing_empty_char_config(self, temp_db):
        """char_config={} 时全部技能缺省，但内部有 fallback → 仍能算出正利润"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config={},
            mat_source_hub="Jita",
            sell_hub="Jita",
        )
        assert result["status"] == ""
        assert result["score"] > 0
        assert result["profit_per_run"] > 0
        # 技能全部为 0 → broker_rate=0.5（经纪人关系学=0, 默认声望5/5）
        assert result["breakdown"]["broker_rate"] == 0.5
        # 会计学=0 → sales_tax_rate=2.0
        assert result["breakdown"]["sales_tax_rate"] == 2.0
        # 高级经纪人关系学=0 → relist_discount=50
        assert result["breakdown"]["relist_discount"] == 50.0

    def test_manufacturing_no_char_config(self, temp_db):
        """char_config=None 应等效于 {}，沿用全部默认值"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config=None,
            mat_source_hub="Jita",
            sell_hub="Jita",
        )
        assert result["status"] == ""
        assert result["score"] > 0
        assert result["profit_per_run"] > 0
        assert result["breakdown"]["broker_rate"] == 0.5
        assert result["breakdown"]["sales_tax_rate"] == 2.0
        assert result["breakdown"]["relist_discount"] == 50.0


class TestTradeScoreEdgeCases:
    """贸易评分 — 全路径 + 缺省/空角色配置"""

    def test_trade_full_path(self, temp_db):
        """贸易正利润全路径：score/margin/profit_per_m3 均应 >0"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        char_config = {
            "skills": {"经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5},
        }
        result = svc.calc_trade_score(
            type_id=2002,
            buy_hub="Jita",
            sell_hub="Jita",
            char_config=char_config,
        )
        assert result["status"] == ""
        assert result["score"] > 0
        assert result["gross_profit"] > 0
        assert result["buy_cost"] > 0
        assert result["sell_revenue"] > 0
        assert result["margin_pct"] > 0
        assert result["profit_per_m3"] > 0

    def test_trade_empty_char_config(self, temp_db):
        """char_config={} 时沿用默认值（技能全 0, 声望 5/5），利润仍为正"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_trade_score(
            type_id=2002,
            char_config={},
        )
        assert result["status"] == ""
        assert result["score"] > 0
        assert result["gross_profit"] > 0

    def test_trade_no_char_config(self, temp_db):
        """char_config=None 时应与 {} 行为一致"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_trade_score(
            type_id=2002,
            char_config=None,
        )
        assert result["status"] == ""
        assert result["score"] > 0
        assert result["gross_profit"] > 0
