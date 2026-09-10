"""科研作业指标分派集成测试 — ScoringService.calculate_plan_metrics 的 activity 分支。

用临时库搭最小数据（蓝图/材料/SCI/价格），只验证「分派 + 取数 + 组装」这一段接线；
纯算法口径由 tests/test_research_formulas.py 与 tests/test_research_plan_metrics.py 覆盖。
"""

from __future__ import annotations

import sqlite3

import pytest

from core.cache import TtlLRUCache
from services.scoring_service import ScoringService

JITA = 30000142
MECH_DATACORE = 20424
NUCLEAR_DATACORE = 20423
DECRYPTOR_AMPLIFIED = 34203
T1_BP = 821  # 200mm自动加农炮蓝图 I
T2_BP = 2890  # 200mm自动加农炮蓝图 II
STANDARD_BP = 9001  # 带拷贝/研究材料的普通蓝图


@pytest.fixture
def research_db(db_manager, monkeypatch):
    """在临时库里建齐科研所需的最小表与数据，并把容器指向它。

    注意 ATTACH 语义：`db.connect("bp", "ref")` 时主库是 **bp**，`ref` 是附随库。
    因此蓝图四表必须建在 bp 库里、item/SCI 建在 ref 库里，查询才用 `bp.` / `ref.` 前缀。
    """
    from services.database_manager import DB_PATH_MAP

    ref_path, bp_path, mkt_path = DB_PATH_MAP["ref"], DB_PATH_MAP["bp"], DB_PATH_MAP["mkt"]
    with sqlite3.connect(bp_path) as conn:
        conn.executescript(
            """
            CREATE TABLE blueprint_products (
                blueprint_type_id INT, activity TEXT, product_type_id INT,
                quantity INT, probability REAL);
            CREATE TABLE blueprint_activities (
                blueprint_type_id INT, activity TEXT, time INT, max_production_limit INT);
            CREATE TABLE blueprint_materials (
                blueprint_type_id INT, material_type_id INT, quantity INT,
                activity TEXT, wastefactor INT DEFAULT 10);
            CREATE TABLE blueprint_skills (
                blueprint_type_id INT, activity TEXT, skill_type_id INT, level INT);
            """
        )
        # T2 蓝图（2890）：制造活动（产出上限 10）+ 发明活动（本计划要跑的作业）
        conn.execute("INSERT INTO blueprint_products VALUES (?,?,?,?,?)", (T2_BP, "manufacturing", 2889, 1, 1.0))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T2_BP, "manufacturing", 2340, 10))
        # T1 蓝图（821）的发明活动：本计划要跑的作业（产出 T2 蓝图）
        # T1 蓝图（821）发明出 T2 蓝图；基础成功率 0.34、拷份上限 200
        conn.execute("INSERT INTO blueprint_products VALUES (?,?,?,?,?)", (T1_BP, "invention", T2_BP, 1, 0.34))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T1_BP, "invention", 13800, 10))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T1_BP, "copying", 720, 200))
        for mid in (MECH_DATACORE, NUCLEAR_DATACORE):
            conn.execute("INSERT INTO blueprint_materials VALUES (?,?,?,?,?)", (T1_BP, mid, 1, "invention", 10))
        # 发明要求的两个科学技能（11453 电子工程学、11454 加达里星舰工程学）+ 加密（21790）
        for sid in (11453, 11454, 21790):
            conn.execute("INSERT INTO blueprint_skills VALUES (?,?,?,?)", (T1_BP, "invention", sid, 1))
        # 普通蓝图：拷贝（材料 3812×10、上限 100）与 ME 研究（材料 11459×2）
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (STANDARD_BP, "copying", 600, 100))
        conn.execute("INSERT INTO blueprint_materials VALUES (?,?,?,?,?)", (STANDARD_BP, 3812, 10, "copying", 10))
        conn.execute(
            "INSERT INTO blueprint_activities VALUES (?,?,?,?)",
            (STANDARD_BP, "researching_material_efficiency", 210, 10),
        )
        conn.execute(
            "INSERT INTO blueprint_materials VALUES (?,?,?,?,?)", (STANDARD_BP, 11459, 2, "research_material", 10)
        )

    with sqlite3.connect(ref_path) as conn:
        conn.executescript(
            """
            CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT, group_id INT);
            CREATE TABLE industry_system_costs (
                solar_system_id INT, activity TEXT, cost_index REAL, fetch_time TIMESTAMP,
                PRIMARY KEY (solar_system_id, activity));
            """
        )
        for tid, zh in ((MECH_DATACORE, "数据核心 - 机械工程"), (NUCLEAR_DATACORE, "数据核心 - 核芯物理")):
            conn.execute("INSERT INTO item VALUES (?,?,?,?)", (tid, zh, zh, 0))
        # 发明技能条目（success 率解析要按中文名查 item）
        for sid, zh in ((11453, "电子工程学"), (11454, "加达里星舰工程学"), (21790, "加达里加密技术原理")):
            conn.execute("INSERT INTO item VALUES (?,?,?,?)", (sid, zh, zh, 270))
        conn.execute("INSERT INTO item VALUES (?,?,?,?)", (3812, "测试材料", "Test Mat", 0))
        conn.execute("INSERT INTO item VALUES (?,?,?,?)", (11459, "测试报告", "Test Report", 0))
        for act, sci in (
            ("manufacturing", 0.1722),
            ("copying", 0.0014),
            ("invention", 0.0014),
            ("researching_material_efficiency", 0.0014),
            ("researching_time_efficiency", 0.0014),
        ):
            conn.execute("INSERT INTO industry_system_costs VALUES (?,?,?,?)", (JITA, act, sci, "2026-01-01"))

    with sqlite3.connect(mkt_path) as conn:
        conn.executescript(
            """
            CREATE TABLE market_prices (
                type_id INT, region_id INT, sell_price REAL, buy_price REAL,
                adjusted_price REAL, fetch_time TIMESTAMP);
            """
        )
        for tid, sell in (
            (MECH_DATACORE, 27890.0),
            (NUCLEAR_DATACORE, 96830.0),
            (DECRYPTOR_AMPLIFIED, 708900.0),
            (3812, 100.0),
            (11459, 1000.0),
            (T2_BP, 5000000.0),
        ):
            conn.execute(
                "INSERT INTO market_prices VALUES (?,?,?,?,?,?)",
                (tid, 10000002, sell, sell * 0.9, 0.0, "2026-01-01"),
            )

    container = _FakeContainer(db_manager)
    monkeypatch.setattr("core.container.get_container", lambda: container)
    return db_manager


def _plan(activity: str, **over):
    """产物/蓝图契约见 services/plan_job_kinds：科研行的 blueprint_type_id 是**本计划那张蓝图**。

    发明 → 被发明的 T2 蓝图（T1 由它反查）；拷贝/研究 → 被拷贝/被研究的 BPO。
    """
    plan = {
        "product_type_id": T2_BP,
        "blueprint_type_id": T2_BP,  # 被发明的 T2 蓝图（不是 T1 输入）
        "activity": activity,
        "runs": 1,
        "parallels": 1,
        "me_level": 0,
        "te_level": 0,
        "solar_system_id": JITA,
        "mat_hub": "Jita",
        "sell_hub": "Jita",
    }
    plan.update(over)
    return plan


def _calc(plan: dict) -> dict:
    return ScoringService.calculate_plan_metrics(plan, {"skills": {}, "market": {}})


class TestInventionDispatch:
    def test_wired_and_computed(self, research_db):
        r = _calc(_plan("invention"))
        assert r["status"] == ""
        assert r["activity"] == "invention"
        bd = r["breakdown"]
        assert bd["base_probability"] == pytest.approx(0.34)
        assert bd["success_rate"] == pytest.approx(0.34)  # 无技能 → 基础值
        # 产出 BPC 流程数 = min(T1 拷份上限 200, T2 制造上限 10) = 10
        assert bd["runs_per_bpc"] == 10
        # 需 1×10 流程；0.34×10=3.4 → ceil(10/3.4) = 3 次
        assert bd["attempts"] == 3
        assert r["material_cost"] == pytest.approx((27890.0 + 96830.0) * 3)
        assert r["calculated_time"] > 0

    def test_skills_read_from_char_config(self, research_db):
        """技能名来自 blueprint_skills，等级从 char_config 读。"""
        plan = _plan("invention")
        r = ScoringService.calculate_plan_metrics(
            plan,
            {"skills": {"电子工程学": 5, "加达里星舰工程学": 5, "加达里加密技术原理": 5}, "market": {}},
        )
        expected = 0.34 * (1 + 10 / 30 + 5 / 40)
        assert r["breakdown"]["success_rate"] == pytest.approx(expected, rel=1e-6)
        assert "电子工程学 L5" in r["breakdown"]["skills"]
        assert "加达里加密技术原理 L5" in r["breakdown"]["skills"]

    def test_decryptor_applied(self, research_db):
        """放大装置解码器：成功率 ×0.60、产出 10+9=19 流程、解码器成本按尝试次数计。"""
        r = _calc(_plan("invention", decryptor_type_id=DECRYPTOR_AMPLIFIED, runs=2))
        bd = r["breakdown"]
        assert bd["decryptor"] == "放大装置解码器"
        assert bd["success_rate"] == pytest.approx(0.204)
        assert bd["runs_per_bpc"] == 19
        # 需 2×10=20 流程；0.204×19=3.876 → ceil(20/3.876) = 6 次
        assert bd["attempts"] == 6
        assert r["material_cost"] == pytest.approx((27890.0 + 96830.0 + 708900.0) * 6)

    def test_success_rate_override_used(self, research_db):
        r = _calc(_plan("invention", success_rate=0.5, runs=1))
        assert r["breakdown"]["success_rate"] == pytest.approx(0.5)
        assert r["breakdown"]["attempts"] == 2  # ceil(10/5)

    def test_actual_output_runs_recorded(self, research_db):
        r = _calc(_plan("invention", actual_output_runs=7))
        bd = r["breakdown"]
        assert bd["is_actual"] is True
        assert bd["output_runs"] == 7

    def test_no_blueprint_when_t1_unknown(self, research_db):
        r = _calc(_plan("invention", blueprint_type_id=999999))
        assert r["status"] == "no_blueprint"

    def test_missing_blueprint_type_id(self, research_db):
        r = _calc(_plan("invention", blueprint_type_id=None))
        assert r["status"] == "no_blueprint"


class TestCopyingDispatch:
    def test_materials_use_total_licensed_runs(self, research_db):
        r = _calc(_plan("copying", product_type_id=STANDARD_BP, blueprint_type_id=STANDARD_BP, runs=50, parallels=2))
        bd = r["breakdown"]
        assert bd["activity"] == "copying"
        assert bd["copies"] == 2
        assert bd["runs_per_copy"] == 50
        # 材料按总授权流程 2×50=100 计：10 × 100 × ¥100 = ¥100,000
        assert r["material_cost"] == pytest.approx(100000.0)
        assert r["calculated_time"] > 0

    def test_runs_per_copy_clamped_to_blueprint_limit(self, research_db):
        r = _calc(_plan("copying", product_type_id=STANDARD_BP, blueprint_type_id=STANDARD_BP, runs=9999))
        assert r["breakdown"]["runs_per_copy"] == 100  # 上限 100

    def test_copying_without_materials(self, research_db):
        """T1 蓝图多数无拷贝材料 → 材料成本 0、安装费 0，不报错。"""
        r = _calc(_plan("copying", product_type_id=T1_BP, blueprint_type_id=T1_BP, runs=10))
        assert r["material_cost"] == 0.0
        assert r["status"] == ""


class TestResearchDispatch:
    def test_me_research_scales_with_target_level(self, research_db):
        r = _calc(
            _plan("researching_material_efficiency", product_type_id=STANDARD_BP, blueprint_type_id=STANDARD_BP, runs=5)
        )
        bd = r["breakdown"]
        assert bd["activity"] == "researching_material_efficiency"
        assert bd["target_level"] == 5
        assert bd["time_is_approximate"] is True
        assert r["material_cost"] == pytest.approx(2 * 5 * 1000.0)  # 材料 2 × 5 级 × ¥1,000


class TestManufacturingUnaffected:
    def test_default_activity_is_manufacturing(self, research_db):
        """未带 activity 字段 → 仍走制造分支（旧计划零回归）。

        fixture 没给 2889 建制造蓝图 → 制造路径返回 no_blueprint；
        返回值不带 activity 字段（只有科研分支才带），据此确认没被误分派到科研。
        """
        plan = _plan("manufacturing", product_type_id=T2_BP, blueprint_type_id=T2_BP)
        plan.pop("activity")
        r = _calc(plan)
        assert "activity" not in r
        assert r.get("status") == "no_blueprint"


class _FakeContainer:
    """把 calculate_plan_metrics 内部与 facade 用的 get_container() 指向临时库。"""

    def __init__(self, db):
        self.db = db
        self._scoring = ScoringService(db=db, cache=TtlLRUCache(max_size=16, ttl_seconds=60))

    def scoring_service(self):
        return self._scoring
