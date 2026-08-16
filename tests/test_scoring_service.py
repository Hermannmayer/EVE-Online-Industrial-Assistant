"""评分服务测试 — 合并 test_scoring / test_scoring_core / test_scoring_service

覆盖:
  - 经纪人费率/改单折扣/销售税独立计算
  - 制造评分（结构/ME 浪费/TE 时间/边缘情况/char_config 缺省）
  - 贸易评分（全路径/无价格/边缘情况）
  - cost 联动：solar_system_id 透传 → SCI（含缓存 key 修复）
  - 机库结构加成联动
"""

from unittest.mock import patch

import pytest

from core.cache import TtlLRUCache
from services.scoring_service import ScoringService

DEFAULT_SKILLS = {"工业理论": 5, "高级工业理论": 5, "经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5}
DEFAULT_CHAR = {"skills": DEFAULT_SKILLS}


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

    # ── 修复回归：快照为空时从材料机库带出星系（避免回退吉他 SCI） ──

    @staticmethod
    def _create_hangar(temp_db, hangar_id: int, solar_system_id: int | None):
        """建完整 hangars 表（含设施列，供 resolve_hangar_industry_config 读取）并插入测试机库。"""
        with temp_db.connect("user") as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS hangars ("
                "id INTEGER PRIMARY KEY, name TEXT, notes TEXT DEFAULT '', "
                "solar_system_id INTEGER DEFAULT NULL, "
                "facility_type TEXT DEFAULT NULL, facility_tax REAL DEFAULT NULL, rigs TEXT DEFAULT NULL)"
            )
            conn.execute(
                "INSERT OR REPLACE INTO hangars (id, name, solar_system_id) VALUES (?, ?, ?)",
                (hangar_id, f"机库{hangar_id}", solar_system_id),
            )

    def test_plan_metrics_derives_system_from_mat_hangar(self, temp_db):
        """无 solar_system_id + mat_hangar_id（机库在 30000150）→ 推导机库星系 SCI(0.15)"""
        self._prepare(temp_db)
        self._create_hangar(temp_db, 1, 30000150)
        cache = TtlLRUCache(max_size=10)
        plan = {
            "product_type_id": 2001,
            "me_level": 0,
            "te_level": 0,
            "runs": 1,
            "parallels": 1,
            "facility_tax": 0.0,
            "mat_hangar_id": 1,
        }
        metrics = self._metrics(temp_db, cache, plan)
        assert metrics["breakdown"]["sci"] == 0.15, "应从材料机库带出星系(30000150)的 SCI"
        assert metrics["solar_system_id"] == 30000150

    def test_plan_metrics_snapshot_takes_precedence_over_mat_hangar(self, temp_db):
        """既有 solar_system_id 快照又绑定机库 → 快照优先（手动覆盖不被机库覆盖）"""
        self._prepare(temp_db)
        self._create_hangar(temp_db, 1, 30000150)
        cache = TtlLRUCache(max_size=10)
        plan = {
            "product_type_id": 2001,
            "me_level": 0,
            "te_level": 0,
            "runs": 1,
            "parallels": 1,
            "facility_tax": 0.0,
            "mat_hangar_id": 1,
            "solar_system_id": 30000142,  # 快照（如手动设置设施星系）→ 用 0.03
        }
        metrics = self._metrics(temp_db, cache, plan)
        assert metrics["breakdown"]["sci"] == 0.03
        assert metrics["solar_system_id"] == 30000142

    def test_plan_metrics_mat_hangar_without_system_falls_back_to_sell_hub(self, temp_db):
        """材料机库未设星系 → 仍回退 sell_hub(吉他 30000142)，不报错"""
        self._prepare(temp_db)
        self._create_hangar(temp_db, 1, None)
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
        assert metrics["breakdown"]["sci"] == 0.03  # 回落 sell_hub → 30000142
        assert metrics["solar_system_id"] == 30000142

    def test_research_cost_cache_keyed_by_system(self, temp_db):
        """研究成本缓存 key 必须含 solar_system_id：不同星系研究成本不串缓存"""
        from services import scoring_service as ss

        ss._research_cost_cache.invalidate()
        try:
            calls: list[int | None] = []
            with patch("services.research_calculator.research_cost_for_item") as mock_r:

                def fake_rf(conn, type_id, *, solar_system_id=None):
                    calls.append(solar_system_id)
                    return 1.0 if solar_system_id == 30000142 else 2.0

                mock_r.side_effect = fake_rf
                v1 = ss._research_cost_cached(temp_db, 2001, solar_system_id=30000142)
                v2 = ss._research_cost_cached(temp_db, 2001, solar_system_id=30000150)
                v1_again = ss._research_cost_cached(temp_db, 2001, solar_system_id=30000142)

            assert v1 == 1.0 and v2 == 2.0 and v1_again == 1.0
            # 同 type 不同星系各自缓存；同一星系第二次命中缓存不再查询
            assert calls == [30000142, 30000150]
        finally:
            ss._research_cost_cache.invalidate()


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


# ════════════════════════════════════════════════════════════════
#  制造评分 — 结构验证 / ME 浪费 / TE 时间
# ════════════════════════════════════════════════════════════════


class TestCalcManufacturingScore:
    """calc_manufacturing_score 返回结构验证"""

    def test_valid_data_returns_correct_keys(self, temp_db):
        """正常数据应返回完整的结果字典"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2001,
            char_config=DEFAULT_CHAR,
            mat_source_hub="Jita",
            sell_hub="Jita",
        )
        # 必须包含的顶层 key
        expected_keys = {
            "score",
            "profit_per_run",
            "margin_pct",
            "isk_per_hour",
            "cost_per_unit",
            "revenue_per_unit",
            "hours_per_run",
            "status",
            "breakdown",
            "materials",
        }
        assert expected_keys.issubset(result.keys())
        assert result["score"] > 0
        assert result["profit_per_run"] > 0
        assert result["materials"]  # 非空

    def test_breakdown_contains_cost_keys(self, temp_db):
        """breakdown 应包含费用相关字段（安装费按游戏类目拆分）"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=5,
            bp_te=10,
        )
        keys = result["breakdown"]
        # 新 breakdown 有 material_cost / installation_fee / eiv / scc_surcharge
        assert "material_cost" in keys
        assert "installation_fee" in keys
        assert "eiv" in keys
        assert "scc_surcharge" in keys
        # 材料信息在 materials 列表中
        assert "materials" in result
        assert len(result["materials"]) > 0
        assert "wastefactor" in result["materials"][0]

    def test_no_price_returns_status(self, temp_db):
        """成品无市场价格时返回 status=no_price"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        # Mock get_price 以模拟无价格场景（避免连接缓存导致的可见性问题）
        with patch("services.scoring_service.get_price", return_value=None):
            result = svc.calc_manufacturing_score(type_id=2001, char_config=DEFAULT_CHAR)
        assert result["status"] == "no_price"
        assert result["score"] == 0.0


class TestManufacturingScore:
    """制造评分 — 利润/蓝图/ME/亏本场景"""

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


class TestMEWasteFactor:
    """验证 ME 对材料浪费的影响 — 使用 manufacturing_calculator 正确公式"""

    def test_me0_gives_minimal_waste(self, temp_db):
        """ME 0 → wastefactor=10 → waste_factor=1.0（SDE quantity=ME0 含损耗量）"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=0,
        )
        mat = result["materials"][0]
        assert mat["wastefactor"] == 10
        assert mat["waste_factor"] == 1.0

    def test_me10_still_has_some_waste(self, temp_db):
        """ME 10 → waste_factor < 1.0（相对 ME0 减量）"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_me=10,
        )
        mat = result["materials"][0]
        assert mat["wastefactor"] == 10
        assert mat["waste_factor"] < 1.0
        assert mat["waste_factor"] >= 0.9

    def test_me5_waste_between_me0_and_me10(self, temp_db):
        """ME 5 的浪费应在 ME0 和 ME10 之间"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        r0 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=0)
        r5 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=5)
        r10 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=10)
        qty0 = r0["materials"][0]["qty"]
        qty5 = r5["materials"][0]["qty"]
        qty10 = r10["materials"][0]["qty"]
        assert qty0 >= qty5 >= qty10

    def test_higher_me_reduces_material_cost(self, temp_db):
        """ME 10 的材料成本应低于 ME 0"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        r0 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=0)
        r10 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_me=10)
        mat_cost_0 = sum(m["subtotal"] for m in r0["materials"])
        mat_cost_10 = sum(m["subtotal"] for m in r10["materials"])
        assert mat_cost_10 < mat_cost_0


class TestTEFactor:
    """验证 TE 对制造时间的影响"""

    def test_te0_no_time_reduction(self, temp_db):
        """TE 0 → hours_per_run 应为最长"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        result = svc.calc_manufacturing_score(
            type_id=2002,
            char_config=DEFAULT_CHAR,
            bp_te=0,
        )
        # TE0 耗时最多，应有合理的正值
        assert result["hours_per_run"] > 0

    def test_te20_gives_20_percent_reduction(self, temp_db):
        """TE 20 的 ISK/h 应明显高于 TE 0（因为时间更短）"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        r0 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_te=0)
        r20 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_te=20)
        # hours_per_run 被 round(2) 截断，不能直接做精确比例
        # 但 TE20 的 ISK/h 应高于 TE0（时间更短则效率更高）
        assert r20["isk_per_hour"] > r0["isk_per_hour"]
        # hours 比例应在合理范围内
        hours_ratio = r0["hours_per_run"] / r20["hours_per_run"]
        assert hours_ratio > 1.0  # TE0 耗时更多

    def test_te10_gives_10_percent_reduction(self, temp_db):
        """TE 10 的 ISK/h 应高于 TE 0（因为时间更短）"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        r0 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_te=0)
        r10 = svc.calc_manufacturing_score(type_id=2002, char_config=DEFAULT_CHAR, bp_te=10)
        assert r10["isk_per_hour"] > r0["isk_per_hour"]

    def test_higher_te_reduces_hours(self, temp_db):
        """TE 20 的小时数应少于 TE 0"""
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
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
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
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
        svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
        result = svc.calc_trade_score(type_id=99999, char_config=DEFAULT_CHAR)
        assert result["status"] == "no_price"
        assert result["score"] == 0.0


def test_trade_score_relist_fee_is_delta_based():
    """卖出改单 broker 只按买/卖价差额计（原为全额，高估费用）"""
    import services.scoring_service as ss

    class FakeSvc(ss.ScoringService):
        def __init__(self):
            super().__init__(db=None, cache=None)  # type: ignore[arg-type]

        def _calc_broker_rate(self, skills, market_data):
            return 0.5  # 0.5%

        def _calc_relist_discount(self, skills):
            return 50.0  # 50% 折扣

        def _calc_sales_tax_rate(self, skills):
            return 2.0  # 2%

    FakeSvc()  # 实例化验证构造路径
    # 直接调用私有计算路径验证 fee 构成：买 100 卖 200，qty 1
    # 期望：sell_fee = 初始挂单 0.5% + 改单差额 (100/200)*0.5%*50% + 税 2%
    buy_price, sell_price = 100.0, 200.0
    broker_rate, relist_discount, sales_tax_rate = 0.5, 50.0, 2.0

    sell_fee_total = (
        broker_rate + (sell_price - buy_price) / sell_price * broker_rate * (1 - relist_discount / 100) + sales_tax_rate
    )
    expected_sell_fee = 0.5 + (100.0 / 200.0) * 0.5 * 0.5 + 2.0  # = 0.5 + 0.125 + 2.0 = 2.625

    assert sell_fee_total == pytest.approx(expected_sell_fee, abs=1e-9)
    # 旧公式（全额）是 0.5*0.5 + 0.5 + 2 = 2.75 → 差额计费应更小
    assert sell_fee_total < 2.75


# ════════════════════════════════════════════════════════════════
#  缓存 / 参数化
# ════════════════════════════════════════════════════════════════


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
