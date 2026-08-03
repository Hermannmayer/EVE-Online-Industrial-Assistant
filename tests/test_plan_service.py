"""plan_service 测试 — 共享「加入制造规划」落库"""

from types import SimpleNamespace

from services import plan_service


def _build_user(db_manager):
    with db_manager.connect("user") as conn:
        conn.execute(
            "CREATE TABLE production_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "product_type_id INTEGER, product_name TEXT, runs INTEGER, parallels INTEGER, "
            "me_level INTEGER, te_level INTEGER, mat_hub TEXT, sell_hub TEXT, facility TEXT, "
            "char_name TEXT, status TEXT, profit REAL, margin REAL, score REAL, iskph REAL, "
            "material_cost REAL, calculated_time REAL, daily_output REAL, created_at TEXT, "
            "deposit_hangar_id INTEGER, mat_hangar_id INTEGER, solar_system_id INTEGER, "
            "materials_ready INTEGER DEFAULT 0)"
        )
    return db_manager


def _patch_container(db_manager, monkeypatch):
    monkeypatch.setattr(plan_service, "get_container", lambda: SimpleNamespace(db=db_manager))


def test_insert_plan(db_manager, monkeypatch):
    _build_user(db_manager)
    _patch_container(db_manager, monkeypatch)
    pid = plan_service.insert_plan(
        2001,
        "渡鸦级",
        {"runs": 2, "parallels": 1, "me": 0, "te": 0, "char": "甲"},
        metrics={"profit": 1.0, "margin": 2.0, "score": 3.0, "iskph": 4.0, "material_cost": 5.0},
    )
    assert pid > 0
    with db_manager.connect("user") as conn:
        row = conn.execute("SELECT * FROM production_plans WHERE id=?", (pid,)).fetchone()
        assert row["product_type_id"] == 2001
        assert row["runs"] == 2
        assert row["profit"] == 1.0
        assert row["status"] == "pending"


def test_insert_plan_defaults(db_manager, monkeypatch):
    _build_user(db_manager)
    _patch_container(db_manager, monkeypatch)
    pid = plan_service.insert_plan(2001, "渡鸦级", {})
    assert pid > 0
    with db_manager.connect("user") as conn:
        row = conn.execute("SELECT * FROM production_plans WHERE id=?", (pid,)).fetchone()
        assert row["runs"] == 1
        assert row["me_level"] == 0


def test_insert_plans_batch(db_manager, monkeypatch):
    """批量插入多行（一次连接），返回对应 plan_id 列表"""
    _build_user(db_manager)
    _patch_container(db_manager, monkeypatch)
    rows = [
        {
            "type_id": 2001,
            "product_name": "渡鸦级",
            "data": {"runs": 2, "parallels": 3, "me": 0, "te": 0},
            "metrics": {"profit": 1.0, "material_cost": 5.0},
        },
        {
            "type_id": 2002,
            "product_name": "无人机",
            "data": {"runs": 1, "parallels": 1, "me": 0, "te": 0},
            "metrics": {"profit": 2.0},
        },
    ]
    ids = plan_service.insert_plans_batch(rows)
    assert len(ids) == 2 and all(i > 0 for i in ids)
    with db_manager.connect("user") as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM production_plans").fetchone()[0]
        assert cnt == 2
        r1 = conn.execute("SELECT * FROM production_plans WHERE id=?", (ids[0],)).fetchone()
        assert r1["parallels"] == 3
        assert r1["profit"] == 1.0


def test_insert_plans_batch_empty(db_manager, monkeypatch):
    _build_user(db_manager)
    _patch_container(db_manager, monkeypatch)
    assert plan_service.insert_plans_batch([]) == []


def test_insert_plan_sets_materials_ready(db_manager, monkeypatch):
    """新加入产线自动勾选备料 → insert_plan 写入 materials_ready=1"""
    _build_user(db_manager)
    _patch_container(db_manager, monkeypatch)
    pid = plan_service.insert_plan(2001, "渡鸦级", {"runs": 1, "parallels": 1, "me": 0, "te": 0})
    assert pid > 0
    with db_manager.connect("user") as conn:
        row = conn.execute("SELECT materials_ready FROM production_plans WHERE id=?", (pid,)).fetchone()
        assert row["materials_ready"] == 1


def test_insert_plans_batch_sets_materials_ready(db_manager, monkeypatch):
    """批量加入制造规划同样自动勾选备料 → 每条 materials_ready=1"""
    _build_user(db_manager)
    _patch_container(db_manager, monkeypatch)
    rows = [
        {"type_id": 2001, "product_name": "渡鸦级", "data": {"runs": 1, "parallels": 1}},
        {"type_id": 2002, "product_name": "无人机", "data": {"runs": 2, "parallels": 1}},
    ]
    ids = plan_service.insert_plans_batch(rows)
    assert len(ids) == 2
    with db_manager.connect("user") as conn:
        for pid in ids:
            row = conn.execute("SELECT materials_ready FROM production_plans WHERE id=?", (pid,)).fetchone()
            assert row["materials_ready"] == 1
