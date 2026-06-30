"""评分核心逻辑单元测试 — 测试 ScoringService 的关键计算路径"""

from services.scoring_cache import ScoringCache
from services.scoring_service import ScoringService

# ── 默认满级角色配置 ──
DEFAULT_SKILLS = {
    "工业理论": 5,
    "高级工业理论": 5,
    "经纪人关系学": 5,
    "高级经纪人关系学": 5,
    "会计学": 5,
}
DEFAULT_CHAR = {"skills": DEFAULT_SKILLS}


# ════════════════════════════════════════════════════════════════
#  制造评分
# ════════════════════════════════════════════════════════════════

class TestCalcManufacturingScore:
    """calc_manufacturing_score 返回结构验证"""

    def test_valid_data_returns_correct_keys(self, temp_db):
        """正常数据应返回完整的结果字典"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config=DEFAULT_CHAR,
            mat_source_hub="Jita",
            sell_hub="Jita",
        )
        # 必须包含的顶层 key
        expected_keys = {
            "score", "profit_per_run", "margin_pct", "isk_per_hour",
            "cost_per_unit", "revenue_per_unit", "hours_per_run",
            "status", "breakdown", "materials",
        }
        assert expected_keys.issubset(result.keys())
        assert result["score"] > 0
        assert result["profit_per_run"] > 0
        assert result["materials"]  # 非空

    def test_breakdown_contains_waste_and_te(self, temp_db):
        """breakdown 应包含 waste_factor 和 te_modifier"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=5,
            bp_te=10,
        )
        assert "waste_factor" in result["breakdown"]
        assert "te_modifier" in result["breakdown"]

    def test_no_blueprint_returns_status(self, temp_db):
        """无蓝图的物品返回 status=no_blueprint"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(type_id=99999, char_config=DEFAULT_CHAR)
        assert result["status"] == "no_blueprint"
        assert result["score"] == 0.0

    def test_no_price_returns_status(self, temp_db):
        """成品无市场价格时返回 status=no_price"""
        from unittest.mock import patch

        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        # Mock get_price 以模拟无价格场景（避免连接缓存导致的可见性问题）
        with patch("services.scoring_service.get_price", return_value=None):
            result = svc.calc_manufacturing_score(type_id=2001, char_config=DEFAULT_CHAR)
        assert result["status"] == "no_price"
        assert result["score"] == 0.0


# ════════════════════════════════════════════════════════════════
#  ME 浪费因子
# ════════════════════════════════════════════════════════════════

class TestMEWasteFactor:
    """验证 ME 对材料浪费的影响"""

    def test_me0_gives_10_percent_waste(self, temp_db):
        """ME 0 → waste_factor = 1.1（10% 浪费）"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=0,
        )
        assert result["breakdown"]["waste_factor"] == 1.1

    def test_me10_gives_zero_waste(self, temp_db):
        """ME 10 → waste_factor = 1.0（无浪费）"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=10,
        )
        assert result["breakdown"]["waste_factor"] == 1.0

    def test_me5_gives_half_waste(self, temp_db):
        """ME 5 → waste_factor = 1.05（5% 浪费）"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=5,
        )
        assert result["breakdown"]["waste_factor"] == 1.05

    def test_higher_me_reduces_material_cost(self, temp_db):
        """ME 10 的材料成本应低于 ME 0"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        r0 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=0)
        r10 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=10)
        # ME10 材料总成本应更低
        mat_cost_0 = sum(m["subtotal"] for m in r0["materials"])
        mat_cost_10 = sum(m["subtotal"] for m in r10["materials"])
        assert mat_cost_10 < mat_cost_0


# ════════════════════════════════════════════════════════════════
#  TE 时间因子
# ════════════════════════════════════════════════════════════════

class TestTEFactor:
    """验证 TE 对制造时间的影响"""

    def test_te0_no_time_reduction(self, temp_db):
        """TE 0 → te_modifier = 1.0（不加速）"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_te=0,
        )
        assert result["breakdown"]["te_modifier"] == 1.0

    def test_te20_gives_20_percent_reduction(self, temp_db):
        """TE 20 → te_modifier = 0.8（20% 时间缩减）"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_te=20,
        )
        assert result["breakdown"]["te_modifier"] == 0.8

    def test_te10_gives_10_percent_reduction(self, temp_db):
        """TE 10 → te_modifier = 0.9"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_te=10,
        )
        assert result["breakdown"]["te_modifier"] == 0.9

    def test_higher_te_reduces_hours(self, temp_db):
        """TE 20 的小时数应少于 TE 0"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        r0 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_te=0)
        r20 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_te=20)
        assert r20["hours_per_run"] < r0["hours_per_run"]


# ════════════════════════════════════════════════════════════════
#  贸易评分
# ════════════════════════════════════════════════════════════════

class TestTradeScoreBasic:
    """calc_trade_score 基本逻辑"""

    def test_basic_trade_returns_structure(self, temp_db):
        """有价格的物品应返回完整结构"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_trade_score(
            type_id=2002,
            buy_hub="Jita",
            sell_hub="Jita",
            char_config=DEFAULT_CHAR,
        )
        assert result["status"] == ""
        assert result["score"] >= 0
        assert result["buy_cost"] > 0
        assert result["sell_revenue"] > 0
        assert result["gross_profit"] != 0  # 可正可负

    def test_no_price_returns_status(self, temp_db):
        """无价格返回 status=no_price"""
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_trade_score(type_id=99999, char_config=DEFAULT_CHAR)
        assert result["status"] == "no_price"
        assert result["score"] == 0.0

    def test_profitable_trade_has_positive_score(self, temp_db):
        """买低卖高应有正评分"""
        # 无人机: buy=100000, sell=120000 — 正利润
        svc = ScoringService(temp_db, ScoringCache(max_size=10))
        result = svc.calc_trade_score(
            type_id=2002,
            buy_hub="Jita",
            sell_hub="Jita",
            char_config=DEFAULT_CHAR,
        )
        if result["gross_profit"] > 0:
            assert result["score"] > 0
