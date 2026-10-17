"""发明完成回填的落库测试 — actual_output_runs / 产出蓝图入库 / 输入流程消耗。

覆盖三个完成入口共用的 core：plan_execution.complete_plan 的科研分支。
（对话框本身是 UI，由 ui-retest 覆盖；这里测落库与口径。）
"""

from __future__ import annotations

import pytest

from services import plan_execution
from services.repositories.plan_repository import PlanRepository

T1_BP = 821  # 被发明的 T1 蓝图（输入）
T2_BP = 2890  # 发明产出的 T2 蓝图（产物）
DATACORE = 20424


@pytest.fixture
def research_env(db_manager, monkeypatch):
    """最小科研环境：蓝图 + 库存（1 张 T1 BPC）+ 计划行，容器指向临时库。"""
    from core.cache import TtlLRUCache
    from services.scoring_service import ScoringService

    with db_manager.connect("user") as conn:
        conn.executescript(PlanRepository.SCHEMA)
        conn.executescript(
            """
            CREATE TABLE hangars (id INTEGER PRIMARY KEY, name TEXT, solar_system_id INTEGER);
            CREATE TABLE inventory_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hangar_id INTEGER, type_id INTEGER, quantity INTEGER, cost_price REAL DEFAULT 0);
            CREATE TABLE user_blueprints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hangar_id INTEGER, blueprint_type_id INTEGER, is_bpo INTEGER DEFAULT 1,
                me_level INTEGER DEFAULT 0, te_level INTEGER DEFAULT 0,
                runs INTEGER DEFAULT 1, quantity INTEGER DEFAULT 1, notes TEXT DEFAULT '',
                cost_per_run REAL DEFAULT 0);
            CREATE TABLE plan_blueprint_bindings (
                plan_id INTEGER, blueprint_id INTEGER, runs_used INTEGER DEFAULT 0,
                PRIMARY KEY (plan_id, blueprint_id));
            """
        )
        conn.execute("INSERT INTO hangars VALUES (1, '研究库', 30000142)")
        # 一张 10 流程的 T1 BPC（发明每次尝试消耗 1 流程）
        conn.execute(
            "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, runs, quantity) "
            "VALUES (1, ?, 0, 10, 1)",
            (T1_BP,),
        )

    with db_manager.connect("bp") as conn:
        conn.executescript(
            """
            CREATE TABLE blueprint_products (
                blueprint_type_id INT, activity TEXT, product_type_id INT,
                quantity INT, probability REAL);
            CREATE TABLE blueprint_activities (
                blueprint_type_id INT, activity TEXT, time INT, max_production_limit INT);
            """
        )
        conn.execute("INSERT INTO blueprint_products VALUES (?,?,?,?,?)", (T1_BP, "invention", T2_BP, 1, 0.34))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T1_BP, "invention", 13800, 10))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T2_BP, "manufacturing", 2340, 10))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T1_BP, "copying", 720, 200))

    class _Container:
        def __init__(self, db):
            self.db = db
            self._scoring = ScoringService(db=db, cache=TtlLRUCache(max_size=8, ttl_seconds=30))

        def scoring_service(self):
            return self._scoring

    monkeypatch.setattr("core.container.get_container", lambda: _Container(db_manager))
    return db_manager


def _make_invention_plan(db, *, runs=2, decryptor=None, actual=None, deposit=1) -> int:
    with db.connect("user") as conn:
        cur = conn.execute(
            "INSERT INTO production_plans "
            "(product_type_id, product_name, blueprint_type_id, runs, parallels, status, "
            "activity, decryptor_type_id, actual_output_runs, deposit_hangar_id, mat_hangar_id) "
            "VALUES (?,?,?,?,1,'ready',?,?,?,?,1)",
            (T2_BP, "测试发明产物", T2_BP, runs, "invention", decryptor, actual, deposit),
        )
        plan_id = int(cur.lastrowid or 0)
        # 绑定库存的 T1 BPC（id=1）
        conn.execute(
            "INSERT INTO plan_blueprint_bindings (plan_id, blueprint_id, runs_used) VALUES (?,1,?)", (plan_id, runs)
        )
    return plan_id


def _plan_row(db, plan_id: int) -> dict:
    with db.connect("user") as conn:
        cur = conn.execute("SELECT * FROM production_plans WHERE id=?", (plan_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row, strict=False)) if row else {}


def _bpcs(db) -> list[tuple]:
    with db.connect("user") as conn:
        return [
            tuple(r)
            for r in conn.execute(
                "SELECT blueprint_type_id, is_bpo, me_level, te_level, runs, quantity, hangar_id "
                "FROM user_blueprints WHERE blueprint_type_id = ? AND is_bpo = 0 ORDER BY id",
                (T2_BP,),
            )
        ]


class TestNeedOutcomeGuard:
    def test_unfilled_invention_refuses_to_complete(self, research_env):
        """发明未回填实际产出 → 拒绝完成（采购页一键完成不能静默吞掉）。"""
        pid = _make_invention_plan(research_env, actual=None)
        res = plan_execution.complete_plan(_plan_row(research_env, pid))
        assert res["ok"] is False
        assert res["code"] == "need_outcome"
        assert _plan_row(research_env, pid)["status"] == "ready", "状态不应被改动"

    def test_filled_invention_completes(self, research_env):
        pid = _make_invention_plan(research_env, actual=7)
        res = plan_execution.complete_plan(_plan_row(research_env, pid))
        assert res["ok"] is True
        assert _plan_row(research_env, pid)["status"] == "completed"

    def test_backfill_via_parameter_recorded(self, research_env):
        """经 complete_plan(actual_output_runs=...) 传入也会落库。"""
        pid = _make_invention_plan(research_env, actual=None)
        res = plan_execution.complete_plan(_plan_row(research_env, pid), actual_output_runs=9)
        assert res["ok"] is True
        assert _plan_row(research_env, pid)["actual_output_runs"] == 9


class TestOutcomeDeposit:
    def test_success_deposits_bpc_with_actual_runs(self, research_env):
        """成功 → 产出 1 份 T2 BPC，流程数 = 实际值。"""
        pid = _make_invention_plan(research_env, actual=9)
        plan_execution.complete_plan(_plan_row(research_env, pid))
        bpcs = _bpcs(research_env)
        assert len(bpcs) == 1
        _type_id, is_bpo, _me, _te, runs, qty, hangar = bpcs[0]
        assert is_bpo == 0
        assert runs == 9
        assert qty == 1
        assert hangar == 1

    def test_failure_deposits_nothing(self, research_env):
        """失败（回填 0）→ 不产出蓝图，但状态照常完成。"""
        pid = _make_invention_plan(research_env, actual=0)
        res = plan_execution.complete_plan(_plan_row(research_env, pid))
        assert res["ok"] is True
        assert _bpcs(research_env) == []
        assert _plan_row(research_env, pid)["status"] == "completed"

    def test_me_te_from_decryptor(self, research_env):
        """解码器决定产出 BPC 的 ME/TE（放大装置 −2/−2 → ME0/TE6）。"""
        pid = _make_invention_plan(research_env, actual=5, decryptor=34203)
        plan_execution.complete_plan(_plan_row(research_env, pid))
        _type_id, _is_bpo, me, te, _runs, _qty, _hangar = _bpcs(research_env)[0]
        assert (me, te) == (0, 6)

    def test_no_decryptor_uses_base_me_te(self, research_env):
        pid = _make_invention_plan(research_env, actual=5, decryptor=None)
        plan_execution.complete_plan(_plan_row(research_env, pid))
        _type_id, _is_bpo, me, te, _runs, _qty, _hangar = _bpcs(research_env)[0]
        assert (me, te) == (2, 4)

    def test_same_spec_merges_quantity(self, research_env):
        """同机库同规格（蓝图/ME/TE/流程）再次产出 → 累加 quantity，不新增行。"""
        pid1 = _make_invention_plan(research_env, actual=5)
        plan_execution.complete_plan(_plan_row(research_env, pid1))
        pid2 = _make_invention_plan(research_env, actual=5)
        plan_execution.complete_plan(_plan_row(research_env, pid2))
        bpcs = _bpcs(research_env)
        assert len(bpcs) == 1, "应合并为一行"
        assert bpcs[0][5] == 2, "quantity 累加"

    def test_different_runs_makes_new_row(self, research_env):
        """流程数不同 → 规格不同，新增一行。"""
        pid1 = _make_invention_plan(research_env, actual=5)
        plan_execution.complete_plan(_plan_row(research_env, pid1))
        pid2 = _make_invention_plan(research_env, actual=8)
        plan_execution.complete_plan(_plan_row(research_env, pid2))
        assert len(_bpcs(research_env)) == 2


class TestDepositRecordsBpcCost:
    """D 回归：发明完成自动把**期望单流程成本**写进产出 BPC 的 `cost_per_run`。

    制造评分按绑定 BPC 的 cost_per_run 计入利润（scoring_service._bound_bpc_costs），
    所以发明完成时必须落这个值，否则用户永远要手填。
    """

    def test_completed_invention_records_cost_per_run(self, research_env, monkeypatch):
        monkeypatch.setattr(plan_execution, "_expected_bpc_cost_per_run", lambda bp_id: 1234.0)
        pid = _make_invention_plan(research_env, actual=9)
        res = plan_execution.complete_plan(_plan_row(research_env, pid))
        assert res["ok"] is True
        with research_env.connect("user") as conn:
            value = conn.execute(
                "SELECT cost_per_run FROM user_blueprints WHERE blueprint_type_id=? AND is_bpo=0",
                (T2_BP,),
            ).fetchone()[0]
        assert value == pytest.approx(1234.0)

    def test_merge_uses_quantity_weighted_cost(self, research_env, monkeypatch):
        """同规格再次产出 → 成本按 quantity 加权平均（1×1234 + 1×2000）/ 2。"""
        values = iter([1234.0, 2000.0])
        monkeypatch.setattr(plan_execution, "_expected_bpc_cost_per_run", lambda bp_id: next(values))
        pid1 = _make_invention_plan(research_env, actual=5)
        plan_execution.complete_plan(_plan_row(research_env, pid1))
        pid2 = _make_invention_plan(research_env, actual=5)
        plan_execution.complete_plan(_plan_row(research_env, pid2))
        with research_env.connect("user") as conn:
            value = conn.execute(
                "SELECT cost_per_run FROM user_blueprints WHERE blueprint_type_id=? AND is_bpo=0",
                (T2_BP,),
            ).fetchone()[0]
        assert value == pytest.approx((1234.0 + 2000.0) / 2)


class TestInputBpcConsumption:
    def test_invention_consumes_input_runs(self, research_env):
        """每次尝试消耗 1 个输入 T1 BPC 流程（runs=2 → 剩 8）。"""
        pid = _make_invention_plan(research_env, runs=2, actual=7)
        plan_execution.complete_plan(_plan_row(research_env, pid))
        with research_env.connect("user") as conn:
            row = conn.execute(
                "SELECT runs, quantity FROM user_blueprints WHERE blueprint_type_id=? AND is_bpo=0",
                (T1_BP,),
            ).fetchone()
        assert row is not None, "输入 BPC 不应被删（还剩流程）"
        assert int(row[0] or 0) * int(row[1] or 1) == 8

    def test_input_bpc_exhausted_is_removed(self, research_env):
        """尝试次数把输入流程耗尽 → 该行删除。"""
        pid = _make_invention_plan(research_env, runs=10, actual=7)
        plan_execution.complete_plan(_plan_row(research_env, pid))
        with research_env.connect("user") as conn:
            row = conn.execute(
                "SELECT 1 FROM user_blueprints WHERE blueprint_type_id=? AND is_bpo=0", (T1_BP,)
            ).fetchone()
        assert row is None


class TestIdempotency:
    def test_second_complete_is_noop(self, research_env):
        pid = _make_invention_plan(research_env, actual=7)
        plan_execution.complete_plan(_plan_row(research_env, pid))
        baseline = _bpcs(research_env)
        res2 = plan_execution.complete_plan(_plan_row(research_env, pid))
        assert res2["ok"] is True
        assert _bpcs(research_env) == baseline, "重复完成不得重复入库"


class TestBreakdownActualFlag:
    @staticmethod
    def test_actual_runs_switches_cost_basis():
        """回填后 bpc_unit_cost 按实际产出算（纯函数层，见 plan_metrics）。"""
        from services.plan_metrics import invention_plan_cost

        common = {
            "base_probability": 0.34,
            "materials": [(DATACORE, 1)],
            "prices": {DATACORE: 100000.0},
            "sci": 0.0,
            "base_runs": 10,
            "output_runs_needed": 10,
        }
        expected = invention_plan_cost(**common)
        actual = invention_plan_cost(**common, actual_output_runs=3)
        assert actual["is_actual"] is True
        assert actual["output_runs"] == 3
        assert actual["bpc_unit_cost"] > expected["bpc_unit_cost"]


# ════════════════════════════════════════════════════════════════
#  T3 发明成本（发明产物 → BPC cost_per_run）
# ════════════════════════════════════════════════════════════════

T3_INPUT = 30752  # SDE：完整的船体舱段（只有 invention 活动的古文物类输入）
T3_BP = 29985  # SDE：金鹏级蓝图（T3 战略巡洋舰）
T3_DATACORES = (20424, 20412)


@pytest.fixture
def t3_research_env(research_env):
    """在最小科研环境上补 T3 发明链路（古文物 → T3 BPC）。

    数据形状照 SDE：输入 30752 只有 invention 活动（无 manufacturing/copying），
    产物 29985 一次成功产 20 流程、基础概率 26%。价格/SCI 用最小夹具值。
    """
    db = research_env
    with db.connect("bp") as conn:
        conn.executescript(
            """
            CREATE TABLE blueprint_materials (
                blueprint_type_id INTEGER, activity TEXT, material_type_id INTEGER, quantity INTEGER);
            CREATE TABLE blueprint_skills (
                blueprint_type_id INTEGER, activity TEXT, skill_type_id INTEGER, level INTEGER);
            """
        )
        conn.execute("INSERT INTO blueprint_products VALUES (?,?,?,?,?)", (T3_INPUT, "invention", T3_BP, 20, 0.26))
        conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?,?)", (T3_INPUT, "invention", 13800, 10))
        for mat in T3_DATACORES:
            conn.execute("INSERT INTO blueprint_materials VALUES (?,?,?,?)", (T3_INPUT, "invention", mat, 3))
        for skill in (3408, 11441, 11452):
            conn.execute("INSERT INTO blueprint_skills VALUES (?,?,?,?)", (T3_INPUT, "invention", skill, 1))
    with db.connect("ref") as conn:
        conn.executescript(
            """
            CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT);
            CREATE TABLE industry_system_costs (solar_system_id INTEGER, activity TEXT, cost_index REAL);
            """
        )
        conn.execute("INSERT INTO item VALUES (3408, '冬眠者加密技术原理', 'Sleeper Encryption Methods')")
        conn.execute("INSERT INTO item VALUES (11441, '等离子物理学', 'Plasma Physics')")
        conn.execute("INSERT INTO item VALUES (11452, '机械工程学', 'Mechanical Engineering')")
        conn.execute("INSERT INTO industry_system_costs VALUES (30000142, 'invention', 0.05)")
    with db.connect("mkt") as conn:
        conn.executescript(
            """
            CREATE TABLE market_prices (
                type_id INTEGER, region_id INTEGER, buy_price REAL, sell_price REAL,
                adjusted_price REAL DEFAULT 0.0, buy_volume INTEGER DEFAULT 0,
                sell_volume INTEGER DEFAULT 0, fetch_time TEXT);
            """
        )
        for mat, price in zip(T3_DATACORES, (90000.0, 95000.0), strict=True):
            conn.execute(
                "INSERT INTO market_prices VALUES (?,10000002,?,?,0.0,1000,1000,'2026-01-01 00:00:00')",
                (mat, price * 0.95, price),
            )
    return db


class TestT3InventionBpcCost:
    def test_t3_invention_records_cost_per_run(self, t3_research_env):
        """T3 发明完成 → 产出 BPC 自动写 cost_per_run > 0（与 T2 同口径）。"""
        db = t3_research_env
        with db.connect("user") as conn:
            cur = conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, runs, quantity) "
                "VALUES (1, ?, 0, 200, 1)",
                (T3_INPUT,),
            )
            input_id = int(cur.lastrowid or 0)
            cur = conn.execute(
                "INSERT INTO production_plans "
                "(product_type_id, product_name, blueprint_type_id, runs, parallels, status, activity, "
                " deposit_hangar_id, mat_hangar_id) "
                "VALUES (?,?,?,5,1,'ready','invention',1,1)",
                (T3_BP, "金鹏级蓝图(T3)", T3_BP),
            )
            plan_id = int(cur.lastrowid or 0)
            conn.execute(
                "INSERT INTO plan_blueprint_bindings (plan_id, blueprint_id, runs_used) VALUES (?,?,5)",
                (plan_id, input_id),
            )
        res = plan_execution.complete_plan(_plan_row(db, plan_id), actual_output_runs=20, actual_bpc_count=1)
        assert res["ok"] is True
        with db.connect("user") as conn:
            row = conn.execute(
                "SELECT runs, cost_per_run FROM user_blueprints WHERE blueprint_type_id=? AND is_bpo=0",
                (T3_BP,),
            ).fetchone()
        assert row is not None, "T3 发明应产出 BPC"
        assert row[0] == 20
        assert row[1] > 0, "T3 发明产出必须写入期望单流程成本（与 T2 同口径）"
