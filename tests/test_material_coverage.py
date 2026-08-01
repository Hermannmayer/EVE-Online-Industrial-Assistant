"""材料覆盖率/缺口服务测试 — services/plan_execution.py 聚合函数

覆盖:
  - get_plans_for_mat_hangar: 只返回以该机库为材料机库的活跃计划（非 completed/done）
  - aggregate_material_requirements: 跨计划合并 need、对照机库库存算缺口、跳过评分失败
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from services import inventory_manager, plan_execution
from services.plan_execution import aggregate_material_requirements, get_plans_for_mat_hangar

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
def coverage_env(temp_db, monkeypatch):
    """temp_db + 注入 container + 建 user 业务表（hangars/inventory_items/production_plans）"""
    # 关键：把 inventory_manager 的模块级单例 db 换成每个测试全新的 DatabaseManager，
    # 避免线程本地连接缓存指向上一个测试已删除的临时库
    monkeypatch.setattr(inventory_manager, "db", temp_db)
    inventory_manager.init_db()
    with temp_db.connect("user") as conn:
        conn.executescript(_PLAN_SCHEMA)
    scoring = MagicMock()
    container = SimpleNamespace(db=temp_db, scoring_service=lambda: scoring)
    monkeypatch.setattr(plan_execution, "_container", lambda: container)
    return SimpleNamespace(db=temp_db, scoring=scoring)


def _insert_plan(db, mat_hangar_id: int, **overrides) -> int:
    """插入一条计划，返回 plan_id。默认 runs=1/parallels=1 便于需求计算。"""
    data = {
        "product_type_id": 2001,
        "product_name": "渡鸦级",
        "blueprint_type_id": 3001,
        "runs": 1,
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
        "mat_hangar_id": mat_hangar_id,
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


# ════════════════════════════════════════════════════════════════
#  get_plans_for_mat_hangar
# ════════════════════════════════════════════════════════════════


class TestGetPlansForMatHangar:
    def test_returns_only_active(self, coverage_env):
        p1 = _insert_plan(coverage_env.db, mat_hangar_id=1, status="pending")
        p2 = _insert_plan(coverage_env.db, mat_hangar_id=1, status="in_progress")
        p3 = _insert_plan(coverage_env.db, mat_hangar_id=1, status="completed")
        p4 = _insert_plan(coverage_env.db, mat_hangar_id=1, status="done")
        p5 = _insert_plan(coverage_env.db, mat_hangar_id=2, status="pending")

        plans = get_plans_for_mat_hangar(1)
        ids = {p["id"] for p in plans}
        assert ids == {p1, p2}
        assert p3 not in ids
        assert p4 not in ids
        assert p5 not in ids

    def test_returns_empty_when_no_plans(self, coverage_env):
        assert get_plans_for_mat_hangar(99) == []


# ════════════════════════════════════════════════════════════════
#  aggregate_material_requirements
# ════════════════════════════════════════════════════════════════


class TestAggregateMaterialRequirements:
    def test_merges_need_across_plans(self, coverage_env):
        """跨计划按 type_id 合并 need，对照机库库存算缺口"""
        coverage_env.scoring.calculate_plan_metrics.side_effect = [
            {"materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]},
            {"materials": [{"type_id": 1001, "name": "三钛合金", "qty": 50.0}]},
        ]
        _insert_item(coverage_env.db, 1, 1001, 120)
        _insert_plan(coverage_env.db, mat_hangar_id=1, status="pending")
        _insert_plan(coverage_env.db, mat_hangar_id=1, status="in_progress")

        rows = aggregate_material_requirements(get_plans_for_mat_hangar(1), 1)
        assert len(rows) == 1
        assert rows[0]["type_id"] == 1001
        assert rows[0]["name"] == "三钛合金"
        assert rows[0]["need"] == 150
        assert rows[0]["owned"] == 120
        assert rows[0]["missing"] == 30

    def test_sorted_by_need_desc(self, coverage_env):
        """结果按 need 降序排列"""
        coverage_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [
                {"type_id": 1001, "name": "三钛合金", "qty": 100.0},
                {"type_id": 1002, "name": "类银超金属", "qty": 40.0},
            ]
        }
        _insert_plan(coverage_env.db, mat_hangar_id=1, status="pending")

        rows = aggregate_material_requirements(get_plans_for_mat_hangar(1), 1)
        assert [r["type_id"] for r in rows] == [1001, 1002]

    def test_skips_plan_when_scoring_fails(self, coverage_env):
        """评分失败的计划跳过（material_requirements 返回空）"""
        coverage_env.scoring.calculate_plan_metrics.side_effect = [
            RuntimeError("boom"),
            {"materials": [{"type_id": 1002, "name": "类银超金属", "qty": 10.0}]},
        ]
        _insert_item(coverage_env.db, 1, 1002, 5)
        _insert_plan(coverage_env.db, mat_hangar_id=1, status="pending")
        _insert_plan(coverage_env.db, mat_hangar_id=1, status="pending")

        rows = aggregate_material_requirements(get_plans_for_mat_hangar(1), 1)
        assert len(rows) == 1
        assert rows[0]["type_id"] == 1002
        assert rows[0]["need"] == 10
        assert rows[0]["owned"] == 5
        assert rows[0]["missing"] == 5

    def test_no_plans_returns_empty(self, coverage_env):
        assert aggregate_material_requirements([], 1) == []

    def test_full_stock_no_missing(self, coverage_env):
        """库存充足时 missing=0"""
        coverage_env.scoring.calculate_plan_metrics.return_value = {
            "materials": [{"type_id": 1001, "name": "三钛合金", "qty": 100.0}]
        }
        _insert_item(coverage_env.db, 1, 1001, 1000)
        _insert_plan(coverage_env.db, mat_hangar_id=1, status="pending")

        rows = aggregate_material_requirements(get_plans_for_mat_hangar(1), 1)
        assert rows[0]["missing"] == 0
