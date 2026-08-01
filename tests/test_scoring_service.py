"""评分服务精细化测试 — 覆盖 test_scoring.py 未触及的分支

覆盖目标:
  - 经纪人费率/改单折扣/销售税的独立单元测试（私有方法直接调用）
  - 贸易评分全路径（正利润分支，含 score/margin/profit_per_m3）
  - char_config=None / {} 时 ScoringService 的默认行为（技能用 fallback 值）
  - 成本联动：solar_system_id 透传 → SCI（含缓存 key 修复）
"""

from unittest.mock import patch

import pytest

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


class TestPlanMetricsSystemCostIndex:
    """成本联动：solar_system_id 透传 → SCI（缓存 key 必须含 system_id）

    说明: 材料 adjusted_price 需非零，否则 eiv=0 时 SCI 对安装费无影响，
    无法区分两个星系的成本差异。
    """

    @staticmethod
    def _prepare(temp_db):
        """插入两个星系的 SCI + 材料 adjusted_price（激活 eiv → 安装费随 SCI 变化）"""
        with temp_db.connect("ref") as conn:
            conn.execute(
                "INSERT INTO industry_system_costs (solar_system_id, activity, cost_index) VALUES (?, 'manufacturing', ?)",
                (30000142, 0.03),
            )
            conn.execute(
                "INSERT INTO industry_system_costs (solar_system_id, activity, cost_index) VALUES (?, 'manufacturing', ?)",
                (30000150, 0.15),
            )
        with temp_db.connect("mkt") as conn:
            conn.execute("UPDATE market_prices SET adjusted_price = 4.0 WHERE type_id = 1001")
            conn.execute("UPDATE market_prices SET adjusted_price = 8.0 WHERE type_id = 1002")

    @staticmethod
    def _metrics(temp_db, cache, plan_data):
        """通过容器调用 calculate_plan_metrics，注入绑定 temp_db 的 ScoringService"""
        svc = ScoringService(temp_db, cache)
        with patch("core.container.get_container") as m:
            cont = m.return_value
            cont.scoring_service.return_value = svc
            return ScoringService.calculate_plan_metrics(plan_data, {}, mat_hub="Jita", sell_hub="Jita")

    def test_breakdown_sci_matches_system_id(self, temp_db):
        """calc_manufacturing_score(system_id=30000150) → breakdown.sci == 0.15"""
        self._prepare(temp_db)
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config={},
            mat_source_hub="Jita",
            sell_hub="Jita",
            system_id=30000150,
        )
        assert result["status"] == ""
        assert result["breakdown"]["sci"] == 0.15

    def test_plan_metrics_matches_direct_scoring_sci(self, temp_db):
        """plan_data.solar_system_id → 内部 calc_manufacturing_score 用同星系 SCI"""
        self._prepare(temp_db)
        cache = TtlLRUCache(max_size=10)
        plan = {
            "product_type_id": 2001,
            "me_level": 0,
            "te_level": 0,
            "runs": 1,
            "parallels": 1,
            "solar_system_id": 30000142,
            "facility_tax": 0.0,  # 显式 0 税，与下方 direct 调用（默认 0）对齐，专注验证 SCI 链路
        }
        metrics = self._metrics(temp_db, cache, plan)

        direct_svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        direct = direct_svc.calc_manufacturing_score(
            type_id=2001,
            char_config={},
            mat_source_hub="Jita",
            sell_hub="Jita",
            system_id=30000142,
        )
        assert direct["breakdown"]["sci"] == 0.03
        assert metrics["profit"] == round(direct["profit_per_run"], 2)

    def test_no_solar_system_id_falls_back_to_sell_hub(self, temp_db):
        """无 solar_system_id → 走 sell_hub(Jita=30000142) 推断 → 与显式 30000142 结果一致"""
        self._prepare(temp_db)
        cache = TtlLRUCache(max_size=10)
        plan_no_sys = {"product_type_id": 2001, "me_level": 0, "te_level": 0, "runs": 1, "parallels": 1}
        plan_jita = dict(plan_no_sys, solar_system_id=30000142)

        result_fallback = self._metrics(temp_db, cache, plan_no_sys)
        result_jita = self._metrics(temp_db, TtlLRUCache(max_size=10), plan_jita)

        assert result_fallback["profit"] == result_jita["profit"]
        assert result_fallback["profit"] > 0

    def test_same_type_different_system_id_not_cached_together(self, temp_db):
        """缓存 key 必须含 system_id：同 type/me/te/hub 不同星系不串缓存"""
        self._prepare(temp_db)
        cache = TtlLRUCache(max_size=10)
        base = {"product_type_id": 2001, "me_level": 0, "te_level": 0, "runs": 1, "parallels": 1}

        r_low = self._metrics(temp_db, cache, dict(base, solar_system_id=30000142))
        r_high = self._metrics(temp_db, cache, dict(base, solar_system_id=30000150))

        assert r_high["profit"] != r_low["profit"], "不同星系 SCI 不同 → 利润必须不同（缓存 key 含 system_id）"
        assert r_high["profit"] < r_low["profit"], "高 SCI 星系安装费更高 → 利润更低"


class TestHangarStructureBonus:
    """机库结构加成联动 — structure_mat_saving / structure_time_mod / 设施税"""

    @staticmethod
    def _prepare(temp_db):
        """建 hangars(v6) + structure_rigs + 机库配置（raitaru + 材料效率I(-2%)）"""
        with temp_db.connect("user") as conn:
            conn.executescript(
                """
                CREATE TABLE hangars (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    notes TEXT DEFAULT '',
                    solar_system_id INTEGER DEFAULT NULL,
                    facility_type TEXT DEFAULT NULL,
                    facility_tax REAL DEFAULT NULL,
                    rigs TEXT DEFAULT NULL
                );
                INSERT INTO hangars (id, name, facility_type, facility_tax, rigs)
                VALUES (1, '制造仓', 'raitaru', 0.5, '[43920]');
                INSERT INTO hangars (id, name, facility_type) VALUES (2, 'NPC仓', 'npc');
                """
            )
        with temp_db.connect("ref") as conn:
            conn.executescript(
                """
                CREATE TABLE structure_rigs (
                    type_id INTEGER PRIMARY KEY,
                    mat_bonus REAL DEFAULT 0.0,
                    time_bonus REAL DEFAULT 0.0
                );
                INSERT INTO structure_rigs VALUES (43920, -2.0, 0.0);
                """
            )

    @staticmethod
    def _metrics(temp_db, cache, plan_data):
        svc = ScoringService(temp_db, cache)
        with patch("core.container.get_container") as m:
            cont = m.return_value
            cont.scoring_service.return_value = svc
            return ScoringService.calculate_plan_metrics(plan_data, {}, mat_hub="Jita", sell_hub="Jita")

    def test_mat_saving_affects_materials(self, temp_db):
        """structure_mat_saving=0.98 → 材料量 ceil(1000×0.98)=980"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        r1 = svc.calc_manufacturing_score(type_id=2001, char_config={})
        r2 = svc.calc_manufacturing_score(type_id=2001, char_config={}, structure_mat_saving=0.98)
        m1 = {m["type_id"]: m["qty"] for m in r1["materials"]}
        m2 = {m["type_id"]: m["qty"] for m in r2["materials"]}
        assert m2[1001] == 980
        assert m2[1001] < m1[1001]

    def test_plan_metrics_uses_hangar_config(self, temp_db):
        """机库 raitaru + 材料效率I → mat 0.99×0.98、time 0.85、cost 0.97、税 0.5"""
        self._prepare(temp_db)
        cache = TtlLRUCache(max_size=10)
        plan = {
            "product_type_id": 2001,
            "me_level": 0,
            "te_level": 0,
            "runs": 1,
            "parallels": 1,
            "mat_hangar_id": 1,
        }
        metrics = self._metrics(temp_db, cache, plan)
        assert metrics["structure_mat_saving"] == pytest.approx(0.99 * 0.98, abs=1e-3)
        assert metrics["structure_time_mod"] == pytest.approx(0.85, abs=1e-3)
        assert metrics["structure_cost_mult"] == pytest.approx(0.97, abs=1e-3)
        assert metrics["facility_tax_pct"] == pytest.approx(0.5)

    def test_facility_tax_precedence(self, temp_db):
        """计划显式 facility_tax > 机库税"""
        self._prepare(temp_db)
        cache = TtlLRUCache(max_size=10)
        plan = {
            "product_type_id": 2001,
            "me_level": 0,
            "te_level": 0,
            "runs": 1,
            "parallels": 1,
            "mat_hangar_id": 1,
            "facility_tax": 2.0,
        }
        metrics = self._metrics(temp_db, cache, plan)
        assert metrics["facility_tax_pct"] == 2.0

    def test_no_hangar_default_tax_npc(self, temp_db):
        """无机库 → 设施税兜底 NPC 0.25%"""
        cache = TtlLRUCache(max_size=10)
        plan = {
            "product_type_id": 2001,
            "me_level": 0,
            "te_level": 0,
            "runs": 1,
            "parallels": 1,
        }
        metrics = self._metrics(temp_db, cache, plan)
        assert metrics["facility_tax_pct"] == pytest.approx(0.25)

    def test_structure_cached_separately(self, temp_db):
        """缓存 key 含 structure 参数：不同加成不串缓存"""
        cache = TtlLRUCache(max_size=10)
        svc = ScoringService(temp_db, cache)
        r_low = svc.calc_manufacturing_score(type_id=2001, char_config={})
        r_high = svc.calc_manufacturing_score(type_id=2001, char_config={}, structure_mat_saving=0.5)
        mat_low = {m["type_id"]: m["qty"] for m in r_low["materials"]}
        mat_high = {m["type_id"]: m["qty"] for m in r_high["materials"]}
        assert mat_low[1001] == 1000
        assert mat_high[1001] == 500  # ceil(1000×0.5)
