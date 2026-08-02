"""生产计划递归拆解测试 — services/plan_decompose.py"""

from types import SimpleNamespace

import services.plan_decompose as pd
from services import inventory_manager


def _build_dbs(db_manager):
    """ref 主库含蓝图表；user 附随含 user_blueprints/hangars/inventory_items。"""
    with db_manager.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        # 渡鸦级 2001 ← bp3001(产出1)；材料 1001(组件×5) + 35(矿物×10)
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',1001,5)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',35,10)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3002,'manufacturing',34,2)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',3600)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',1800)")
    with db_manager.connect("user") as conn:
        conn.execute(
            "CREATE TABLE user_blueprints (id INTEGER PRIMARY KEY, hangar_id INTEGER, "
            "blueprint_type_id INTEGER, is_bpo INTEGER DEFAULT 1, me_level INTEGER DEFAULT 0, "
            "te_level INTEGER DEFAULT 0, runs INTEGER DEFAULT 1, quantity INTEGER DEFAULT 1)"
        )
        conn.execute("CREATE TABLE hangars (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute(
            "CREATE TABLE inventory_items (id INTEGER PRIMARY KEY, hangar_id INTEGER, "
            "type_id INTEGER, quantity INTEGER, cost_price REAL)"
        )
        conn.execute("INSERT INTO hangars VALUES (1,'矿仓')")
    return db_manager


def _patch(db_manager, monkeypatch):
    monkeypatch.setattr(pd, "get_container", lambda: SimpleNamespace(db=db_manager))
    monkeypatch.setattr(inventory_manager, "db", db_manager)


class TestDecomposePlan:
    def test_two_levels(self, db_manager, monkeypatch):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        lines = pd.decompose_plan({"product_type_id": 2001, "runs": 2, "parallels": 1, "me_level": 0})
        # 2001 材料 1001×5 → 需 10 → 1001 有蓝图 → 中间产线；35 叶子不拆
        assert len(lines) == 1
        assert lines[0]["product_type_id"] == 1001
        assert lines[0]["sub_level"] == 1
        assert lines[0]["runs"] == 10
        assert lines[0]["parallels"] == 1

    def test_no_blueprint_returns_empty(self, db_manager, monkeypatch):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        assert pd.decompose_plan({"product_type_id": 99999, "runs": 1, "parallels": 1}) == []

    def test_inventory_reduces_runs(self, db_manager, monkeypatch):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute("INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price) VALUES (1,1001,6,0)")
        # 1001 库存 6 → 覆盖 6 轮，需 10 轮 → 造 4 轮
        lines = pd.decompose_plan(
            {"product_type_id": 2001, "runs": 2, "parallels": 1, "me_level": 0}, mat_hangar_id=1
        )
        assert len(lines) == 1
        assert lines[0]["runs"] == 4

    def test_has_blueprint_flag(self, db_manager, monkeypatch):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level) "
                "VALUES (1,3002,1,6,2)"
            )
        lines = pd.decompose_plan({"product_type_id": 2001, "runs": 2, "parallels": 1})
        assert lines[0]["has_blueprint"] is True
        assert lines[0]["me_level"] == 6
        assert lines[0]["te_level"] == 2

    def test_no_blueprint_defaults_zero(self, db_manager, monkeypatch):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        lines = pd.decompose_plan({"product_type_id": 2001, "runs": 2, "parallels": 1})
        assert lines[0]["has_blueprint"] is False
        assert lines[0]["me_level"] == 0
        assert lines[0]["te_level"] == 0


class TestBestInventoryBlueprint:
    def test_bpo_preferred_over_higher_me_bpc(self, db_manager):
        _build_dbs(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level) "
                "VALUES (1,3002,0,4,1)"
            )
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level) "
                "VALUES (1,3002,1,6,2)"
            )
        with db_manager.connect("ref", "user") as conn:
            assert pd.best_inventory_blueprint(conn, 3002) == {"me_level": 6, "te_level": 2}

    def test_me_higher_bpc_without_bpo(self, db_manager):
        _build_dbs(db_manager)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level) "
                "VALUES (1,3002,0,4,1)"
            )
            conn.execute(
                "INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo, me_level, te_level) "
                "VALUES (1,3002,0,8,0)"
            )
        with db_manager.connect("ref", "user") as conn:
            assert pd.best_inventory_blueprint(conn, 3002) == {"me_level": 8, "te_level": 0}

    def test_none(self, db_manager):
        _build_dbs(db_manager)
        with db_manager.connect("ref", "user") as conn:
            assert pd.best_inventory_blueprint(conn, 999) is None
