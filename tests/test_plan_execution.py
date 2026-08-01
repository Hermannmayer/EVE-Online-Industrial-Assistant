"""生产计划执行服务测试 — services/plan_execution.py

覆盖：倒计时、重启补算、材料校验/扣减、启动/批量启动、蓝图绑定/占用/消耗、完成入库。
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import inventory_manager, plan_execution
from services.plan_execution import (
    _split_bpc_consumption,
    bind_blueprint,
    cancel_plan,
    check_materials,
    complete_plan,
    consume_bpc_runs,
    deduct_materials,
    expire_overdue_plans,
    find_available_blueprints,
    get_occupied_blueprint_ids,
    material_requirements,
    release_blueprint,
    remaining_seconds,
    start_plan,
    start_plan_batch,
)

_PLAN_SCHEMA = """
CREATE TABLE IF NOT EXISTS production_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_type_id INTEGER NOT NULL,
    product_name TEXT,
    blueprint_type_id INTEGER,
    runs INTEGER DEFAULT 1,
    parallels INTEGER DEFAULT 1,
    me_level INTEGER DEFAULT 0,
    te_level INTEGER DEFAULT 0,
    mat_hub TEXT DEFAULT 'Jita',
    sell_hub TEXT DEFAULT 'Jita',
    facility TEXT DEFAULT '',
    char_name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    profit REAL DEFAULT 0,
    margin REAL DEFAULT 0,
    score REAL DEFAULT 0,
    material_cost REAL DEFAULT 0,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    facility_cost_mult REAL DEFAULT 1.0,
    notes TEXT DEFAULT '',
    group_number INTEGER DEFAULT 0,
    sub_level INTEGER DEFAULT 0,
    output_location TEXT DEFAULT '',
    market_margin REAL DEFAULT 0,
    personal_margin REAL DEFAULT 0,
    daily_output REAL DEFAULT 0,
    materials_ready INTEGER DEFAULT 0,
    iskph REAL DEFAULT 0,
    deposit_hangar_id INTEGER DEFAULT NULL,
    deposited INTEGER DEFAULT 0,
    calculated_time REAL DEFAULT 0,
    assigned_blueprint_id INTEGER DEFAULT NULL,
    mat_hangar_id INTEGER DEFAULT NULL,
    material_short TEXT DEFAULT ''
);
"""


@pytest.fixture
def user_env(temp_db, monkeypatch):
    """temp_db + 注入 container + 建 user 业务表（hangars/inventory_items/user_blueprints/production_plans）"""
    # 关键：把 inventory_manager 的模块级单例 db 换成每个测试全新的 DatabaseManager，
    # 避免线程本地连接缓存指向上一个测试已删除的临时库（导致「no such table/已删除」污染）
    monkeypatch.setattr(inventory_manager, "db", temp_db)
    inventory_manager.init_db()
    with temp_db.connect("user") as conn:
        conn.executescript(_PLAN_SCHEMA)
    scoring = MagicMock()
    container = SimpleNamespace(db=temp_db, scoring_service=lambda: scoring)
    monkeypatch.setattr(plan_execution, "_container", lambda: container)
    return SimpleNamespace(db=temp_db, scoring=scoring)


def _insert_plan(db, **overrides) -> int:
    """插入一条 pending 计划，返回 plan_id。"""
    data = {
        "product_type_id": 2001,
        "product_name": "渡鸦级",
        "blueprint_type_id": 3001,
        "runs": 2,
        "parallels": 1,
        "me_level": 0,
        "te_level": 0,
        "mat_hub": "Jita",
        "sell_hub": "Jita",
        "facility": "",
        "char_name": "",
        "status": "pending",
        "material_cost": 1000.0,
        "calculated_time": 7200,
        "deposit_hangar_id": None,
        "mat_hangar_id": None,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
    }
    data.update(overrides)
    cols = ", ".join(data)
    ph = ", ".join("?" for _ in data)
    with db.connect("user") as conn:
        cur = conn.execute(f"INSERT INTO production_plans ({cols}) VALUES ({ph})", list(data.values()))
        return int(cur.lastrowid)


def _insert_item(db, hangar_id: int, type_id: int, qty: int) -> int:
    return inventory_manager.add_item(hangar_id, type_id, qty)


def _insert_blueprint(db, blueprint_type_id: int, *, is_bpo: bool = False, me=0, te=0, runs=10, quantity=1) -> int:
    return inventory_manager.add_blueprint(
        1, blueprint_type_id, is_bpo=is_bpo, me_level=me, te_level=te, runs=runs, quantity=quantity
    )


def _get_plan(db, plan_id: int) -> dict:
    with db.connect("user") as conn:
        cur = conn.execute("SELECT * FROM production_plans WHERE id=?", (plan_id,))
        cols = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(cols, row, strict=False))


# ════════════════════════════════════════════════════════════════
#  倒计时
# ════════════════════════════════════════════════════════════════


class TestRemainingSeconds:
    def test_in_progress_returns_remaining(self):
        start = datetime(2026, 1, 1, 0, 0, 0)
        now = start + timedelta(seconds=3600)
        plan = {"status": "in_progress", "started_at": start.strftime("%Y-%m-%d %H:%M:%S"), "calculated_time": 7200}
        assert remaining_seconds(plan, now=now) == 3600

    def test_pending_returns_none(self):
        assert remaining_seconds({"status": "pending", "calculated_time": 7200}, now=datetime.now(UTC)) is None

    def test_no_started_at_returns_none(self):
        assert remaining_seconds({"status": "in_progress", "calculated_time": 7200}, now=datetime.now(UTC)) is None

    def test_zero_duration_returns_none(self):
        plan = {"status": "in_progress", "started_at": "2026-01-01 00:00:00", "calculated_time": 0}
        assert remaining_seconds(plan, now=datetime(2026, 1, 1, 1, 0, 0)) is None

    def test_overdue_returns_negative(self):
        plan = {"status": "in_progress", "started_at": "2026-01-01 00:00:00", "calculated_time": 3600}
        assert remaining_seconds(plan, now=datetime(2026, 1, 1, 2, 0, 0)) == -3600

    def test_bad_started_at_returns_none(self):
        plan = {"status": "in_progress", "started_at": "not-a-date", "calculated_time": 3600}
        assert remaining_seconds(plan, now=datetime(2026, 1, 1, 2, 0, 0)) is None


class TestExpireOverduePlans:
    def test_expires_overdue_in_progress(self, user_env):
        pid = _insert_plan(user_env.db, status="in_progress", calculated_time=3600)
        with user_env.db.connect("user") as conn:
            conn.execute("UPDATE production_plans SET started_at=? WHERE id=?", ("2020-01-01 00:00:00", pid))

        assert expire_overdue_plans(user_env.db) == 1
        assert _get_plan(user_env.db, pid)["status"] == "ready"

    def test_keeps_not_yet_expired(self, user_env):
        pid = _insert_plan(user_env.db, status="in_progress", calculated_time=86400)
        with user_env.db.connect("user") as conn:
            conn.execute("UPDATE production_plans SET started_at=? WHERE id=?", ("2099-01-01 00:00:00", pid))

        assert expire_overdue_plans(user_env.db) == 0
        assert _get_plan(user_env.db, pid)["status"] == "in_progress"

    def test_ignores_pending_and_missing_started_at(self, user_env):
        p1 = _insert_plan(user_env.db, status="pending")
        p2 = _insert_plan(user_env.db, status="in_progress", calculated_time=3600)  # started_at NULL
        assert expire_overdue_plans(user_env.db) == 0
        assert _get_plan(user_env.db, p1)["status"] == "pending"
        assert _get_plan(user_env.db, p2)["status"] == "in_progress"


# ════════════════════════════════════════════════════════════════
#  材料校验 / 扣减
# ════════════════════════════════════════════════════════════════


class TestMaterialRequirements:
    def test_multiplies_by_runs_and_parallels(self, user_env):
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        reqs = material_requirements({"runs": 3, "parallels": 2, "char_name": ""})
        assert reqs == [{"type_id": 1001, "name": "三钛合金", "need": 600}]

    def test_empty_materials_when_scoring_fails(self, user_env):
        user_env.scoring.calculate_plan_metrics.side_effect = RuntimeError("boom")
        assert material_requirements({"runs": 1, "parallels": 1}) == []


class TestCheckMaterials:
    def test_sufficient(self, user_env):
        _insert_item(user_env.db, 1, 1001, 5000)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        res = check_materials({"runs": 2, "parallels": 1}, 1)
        assert res[0]["need"] == 200
        assert res[0]["owned"] == 5000
        assert res[0]["missing"] == 0

    def test_shortfall(self, user_env):
        _insert_item(user_env.db, 1, 1001, 50)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        res = check_materials({"runs": 2, "parallels": 1}, 1)
        assert res[0]["missing"] == 150

    def test_no_mat_hangar_returns_empty(self, user_env):
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        assert check_materials({"runs": 1, "parallels": 1}, None) == []


class TestDeductMaterials:
    def test_full_deduction(self, user_env):
        _insert_item(user_env.db, 1, 1001, 500)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        res = deduct_materials({"runs": 2, "parallels": 1}, 1)
        assert res[0]["deducted"] == 200
        assert inventory_manager.get_hangar_stock(1)[1001] == 300

    def test_partial_deduction(self, user_env):
        _insert_item(user_env.db, 1, 1001, 50)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        res = deduct_materials({"runs": 1, "parallels": 1}, 1)
        assert res[0]["deducted"] == 50
        assert res[0]["missing"] == 50
        assert 1001 not in inventory_manager.get_hangar_stock(1)  # 行被删除

    def test_no_stock(self, user_env):
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        res = deduct_materials({"runs": 1, "parallels": 1}, 1)
        assert res[0]["deducted"] == 0


# ════════════════════════════════════════════════════════════════
#  启动
# ════════════════════════════════════════════════════════════════


class TestStartPlan:
    def test_starts_and_writes_started_at(self, user_env):
        pid = _insert_plan(user_env.db)
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=1)
        assert res["ok"]
        db_plan = _get_plan(user_env.db, pid)
        assert db_plan["status"] == "in_progress"
        assert db_plan["started_at"] is not None

    def test_already_started_rejected(self, user_env):
        pid = _insert_plan(user_env.db, status="in_progress", started_at="2026-01-01 00:00:00")
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=1)
        assert not res["ok"]
        assert res["code"] == "already_started"

    def test_completed_rejected(self, user_env):
        pid = _insert_plan(user_env.db, status="completed")
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=1)
        assert res["code"] == "already_completed"

    def test_material_short_blocks_without_allow(self, user_env):
        _insert_item(user_env.db, 1, 1001, 10)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        pid = _insert_plan(user_env.db, runs=1)
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=1, allow_short=False)
        assert not res["ok"]
        assert res["code"] == "material_short"
        assert res["shortfalls"][0]["missing"] == 90

    def test_force_start_records_shortage(self, user_env):
        _insert_item(user_env.db, 1, 1001, 10)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        pid = _insert_plan(user_env.db, runs=1)
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=1, allow_short=True)
        assert res["ok"]
        db_plan = _get_plan(user_env.db, pid)
        assert db_plan["status"] == "in_progress"
        assert "1001" in db_plan["material_short"]  # 缺口 JSON 已落库
        assert inventory_manager.get_hangar_stock(1).get(1001, 0) == 0  # 可用 10 件已扣

    def test_auto_binds_bpo(self, user_env):
        _insert_blueprint(user_env.db, 3001, is_bpo=True)
        pid = _insert_plan(user_env.db)
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=1, auto_bind=True)
        assert res["ok"]
        db_plan = _get_plan(user_env.db, pid)
        assert db_plan["assigned_blueprint_id"] is not None

    def test_no_material_hangar_skips_deduction(self, user_env):
        pid = _insert_plan(user_env.db)
        plan = _get_plan(user_env.db, pid)
        res = start_plan(plan, mat_hangar_id=None)
        assert res["ok"]
        assert _get_plan(user_env.db, pid)["status"] == "in_progress"


class TestStartPlanBatch:
    def test_mixed_results(self, user_env):
        p1 = _insert_plan(user_env.db)
        p2 = _insert_plan(user_env.db, status="in_progress", started_at="2026-01-01 00:00:00")
        plans = [_get_plan(user_env.db, p1), _get_plan(user_env.db, p2)]
        res = start_plan_batch(plans, mat_hangar_id=1)
        assert res["ok_count"] == 1
        assert res["total"] == 2
        assert not res["ok"]


class TestCancelPlan:
    def test_returns_materials(self, user_env):
        _insert_item(user_env.db, 1, 1001, 500)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        pid = _insert_plan(user_env.db, runs=2, mat_hangar_id=1)
        plan = _get_plan(user_env.db, pid)
        start_plan(plan, mat_hangar_id=1)
        assert inventory_manager.get_hangar_stock(1)[1001] == 300  # 扣 200

        plan = _get_plan(user_env.db, pid)
        res = cancel_plan(plan)
        assert res["ok"]
        assert res["returned"] == 200
        assert inventory_manager.get_hangar_stock(1)[1001] == 500  # 返还 200
        db_plan = _get_plan(user_env.db, pid)
        assert db_plan["status"] == "pending"
        assert db_plan["started_at"] is None

    def test_returns_only_deducted_when_force_started(self, user_env):
        _insert_item(user_env.db, 1, 1001, 50)
        user_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        pid = _insert_plan(user_env.db, runs=1, mat_hangar_id=1)
        plan = _get_plan(user_env.db, pid)
        start_plan(plan, mat_hangar_id=1, allow_short=True)  # 扣 50，缺口 50
        assert inventory_manager.get_hangar_stock(1).get(1001, 0) == 0

        plan = _get_plan(user_env.db, pid)
        res = cancel_plan(plan)
        assert res["returned"] == 50  # 只返还实际扣掉的 50，不返还缺口
        assert inventory_manager.get_hangar_stock(1).get(1001, 0) == 50

    def test_releases_blueprint(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=10)
        pid = _insert_plan(user_env.db, mat_hangar_id=1)
        plan = _get_plan(user_env.db, pid)
        bind_blueprint(pid, bp_id)
        start_plan(plan, mat_hangar_id=1)  # 已绑定则不再自动改
        assert get_occupied_blueprint_ids(user_env.db) == {bp_id}

        plan = _get_plan(user_env.db, pid)
        cancel_plan(plan)
        assert get_occupied_blueprint_ids(user_env.db) == set()

    def test_no_material_hangar_returns_nothing(self, user_env):
        pid = _insert_plan(user_env.db, status="in_progress", started_at="2026-01-01 00:00:00", mat_hangar_id=None)
        plan = _get_plan(user_env.db, pid)
        res = cancel_plan(plan)
        assert res["ok"]
        assert res["returned"] == 0
        assert _get_plan(user_env.db, pid)["status"] == "pending"

    def test_completed_rejected(self, user_env):
        pid = _insert_plan(user_env.db, status="completed")
        plan = _get_plan(user_env.db, pid)
        res = cancel_plan(plan)
        assert not res["ok"]


# ════════════════════════════════════════════════════════════════
#  蓝图占用 / 消耗
# ════════════════════════════════════════════════════════════════


class TestBlueprintBinding:
    def test_bind_and_release(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=True)
        pid = _insert_plan(user_env.db)
        assert bind_blueprint(pid, bp_id)
        assert _get_plan(user_env.db, pid)["assigned_blueprint_id"] == bp_id
        assert get_occupied_blueprint_ids(user_env.db) == {bp_id}
        assert release_blueprint(pid)
        assert get_occupied_blueprint_ids(user_env.db) == set()

    def test_bpc_occupied_by_other_plan_rejected(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=10)
        p1 = _insert_plan(user_env.db)
        p2 = _insert_plan(user_env.db)
        assert bind_blueprint(p1, bp_id)
        assert not bind_blueprint(p2, bp_id)  # BPC 已被 p1 占用

    def test_bpo_shareable(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=True)
        p1 = _insert_plan(user_env.db)
        p2 = _insert_plan(user_env.db)
        assert bind_blueprint(p1, bp_id)
        assert bind_blueprint(p2, bp_id)  # BPO 可共享

    def test_completed_plan_releases_occupancy(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=10)
        p1 = _insert_plan(user_env.db, status="ready", deposit_hangar_id=1, material_cost=1000)
        _insert_item(user_env.db, 1, 1001, 100)
        assert bind_blueprint(p1, bp_id)
        plan = _get_plan(user_env.db, p1)
        complete_plan(plan)
        assert get_occupied_blueprint_ids(user_env.db) == set()


class TestFindAvailableBlueprints:
    def test_lists_blueprints_with_occupancy(self, user_env):
        bpo = _insert_blueprint(user_env.db, 3001, is_bpo=True)
        bpc = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=10, quantity=2)
        p1 = _insert_plan(user_env.db)
        bind_blueprint(p1, bpc)

        with user_env.db.connect("user", "bp", "ref") as conn:
            options = find_available_blueprints(conn, 3001)
        by_id = {o["id"]: o for o in options}
        assert by_id[bpo]["is_bpo"] is True
        assert by_id[bpo]["available_runs"] == float("inf")
        assert by_id[bpc]["available_runs"] == 20  # quantity×runs
        assert by_id[bpc]["occupied"] is True
        assert by_id[bpo]["occupied"] is False


class TestConsumeBpcRuns:
    def test_bpo_untouched(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=True, runs=-1)
        with user_env.db.direct_connect("user") as conn:
            res = consume_bpc_runs(conn, bp_id, 5)
        assert res["skipped"] is True
        assert inventory_manager.get_blueprints(1)[0]["runs"] == -1

    def test_partial_consumption(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=10, quantity=1)
        with user_env.db.direct_connect("user") as conn:
            res = consume_bpc_runs(conn, bp_id, 4)
        assert not res["skipped"]
        assert res["new_quantity"] == 1
        assert res["new_runs"] == 6

    def test_full_stack_consumed_deletes(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=5, quantity=2)
        with user_env.db.direct_connect("user") as conn:
            res = consume_bpc_runs(conn, bp_id, 10)
        assert res["deleted"] is True
        assert inventory_manager.get_blueprints(1) == []

    def test_exact_multi_copy(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=5, quantity=3)
        with user_env.db.direct_connect("user") as conn:
            res = consume_bpc_runs(conn, bp_id, 5)
        assert res["new_quantity"] == 2
        assert res["new_runs"] == 5


class TestSplitBpcConsumption:
    def test_no_consumption(self):
        assert _split_bpc_consumption(2, 10, 0) == (2, 10)

    def test_full_copies(self):
        assert _split_bpc_consumption(3, 10, 20) == (1, 10)

    def test_partial_consumption_collapses(self):
        q, r = _split_bpc_consumption(2, 10, 6)
        assert q * r == 14  # 剩余总流程不变

    def test_exhausts_row(self):
        assert _split_bpc_consumption(2, 10, 20) == (0, None)  # 恰好耗尽 → 删行
        assert _split_bpc_consumption(2, 10, 25) == (0, None)  # 超出 → 删行


# ════════════════════════════════════════════════════════════════
#  完成入库
# ════════════════════════════════════════════════════════════════


class TestCompletePlan:
    def test_deposits_product(self, user_env):
        pid = _insert_plan(
            user_env.db,
            status="ready",
            runs=2,
            parallels=3,
            deposit_hangar_id=1,
            material_cost=600,
            calculated_time=3600,
        )
        plan = _get_plan(user_env.db, pid)
        res = complete_plan(plan)
        assert res["ok"]
        assert res["deposited"] == 1
        stock = inventory_manager.get_hangar_stock(1)
        assert stock[2001] == 6  # runs×parallels×per_run(1)
        db_plan = _get_plan(user_env.db, pid)
        assert db_plan["status"] == "completed"
        assert db_plan["deposited"] == 1
        assert db_plan["completed_at"] is not None

    def test_no_deposit_hangar_skips(self, user_env):
        pid = _insert_plan(user_env.db, status="ready", deposit_hangar_id=None)
        plan = _get_plan(user_env.db, pid)
        res = complete_plan(plan)
        assert res["ok"]
        assert res["deposited"] == 0
        assert "跳过入库" in res["message"]
        assert _get_plan(user_env.db, pid)["status"] == "completed"

    def test_consumes_bpc_on_complete(self, user_env):
        bp_id = _insert_blueprint(user_env.db, 3001, is_bpo=False, runs=10, quantity=1)
        pid = _insert_plan(
            user_env.db, status="ready", runs=4, parallels=1, deposit_hangar_id=1, assigned_blueprint_id=bp_id
        )
        plan = _get_plan(user_env.db, pid)
        complete_plan(plan)
        bp = inventory_manager.get_blueprints(1)[0]
        assert bp["runs"] == 6  # 10 - 4 已消耗
