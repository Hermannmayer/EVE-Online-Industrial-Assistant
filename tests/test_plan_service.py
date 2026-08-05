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


# ══════════════════════════════════════
#  enrich_plan_hangar_names — 设施/输出列显示补全
# ══════════════════════════════════════


class TestEnrichPlanHangarNames:
    def test_facility_filled_from_material_hangar(self):
        """空 facility + 有材料机库 → 填材料机库名称"""
        rows = [{"mat_hangar_id": 3, "facility": "", "deposit_hangar_id": None}]
        out = plan_service.enrich_plan_hangar_names(rows, {3: "材料仓库A"})
        assert out[0]["facility"] == "材料仓库A"

    def test_explicit_facility_preserved(self):
        """显式 facility 不被覆盖"""
        rows = [{"mat_hangar_id": 3, "facility": "自定义设施", "deposit_hangar_id": None}]
        out = plan_service.enrich_plan_hangar_names(rows, {3: "材料仓库A"})
        assert out[0]["facility"] == "自定义设施"

    def test_no_mat_hangar_unchanged(self):
        """无材料机库 → facility 保持空"""
        rows = [{"mat_hangar_id": None, "facility": "", "deposit_hangar_id": None}]
        out = plan_service.enrich_plan_hangar_names(rows, {})
        assert out[0]["facility"] == ""

    def test_unknown_hangar_id_unchanged(self):
        """机库 id 不在映射中 → facility 保持空"""
        rows = [{"mat_hangar_id": 99, "facility": "", "deposit_hangar_id": None}]
        out = plan_service.enrich_plan_hangar_names(rows, {3: "材料仓库A"})
        assert out[0]["facility"] == ""

    def test_output_hangar_from_deposit(self):
        """输出列显示输出机库：output_hangar 来自 deposit_hangar_id（不是输出数量）"""
        rows = [{"mat_hangar_id": None, "facility": "", "deposit_hangar_id": 7}]
        out = plan_service.enrich_plan_hangar_names(rows, {7: "成品仓库"})
        assert out[0]["output_hangar"] == "成品仓库"

    def test_no_deposit_output_empty(self):
        """无输出机库 → output_hangar 为空"""
        rows = [{"mat_hangar_id": None, "facility": "", "deposit_hangar_id": None}]
        out = plan_service.enrich_plan_hangar_names(rows, {7: "成品仓库"})
        assert out[0]["output_hangar"] == ""

    def test_returns_same_list(self):
        """原地修改并返回同一列表（与 load_plans 现有补全风格一致）"""
        rows = [{"mat_hangar_id": 1, "facility": "", "deposit_hangar_id": 2}]
        assert plan_service.enrich_plan_hangar_names(rows, {1: "A", 2: "B"}) is rows
