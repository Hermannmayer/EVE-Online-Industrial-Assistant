"""研究成本计算测试 — services/research_calculator.py"""

import services.research_calculator as rc


def _build_ref(db_manager):
    with db_manager.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER, probability REAL)"
        )
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute(
            "CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time INTEGER)"
        )
        # T1 物品 2001 ← 制造蓝图 3001；拷贝材料 1001×5
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1,NULL)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'copying',1001,5)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'copying',4800)")
        # T2 物品 2002 ← 制造蓝图 3002（自身是 invention 产物）；发明材料挂在 T1 蓝图 3003
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',2002,1,NULL)")
        conn.execute("INSERT INTO blueprint_products VALUES (3003,'invention',2002,1,0.3)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3003,'invention',1002,2)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3003,'invention',63900)")
        # 蓝图原图 3004（自身是蓝图）
        conn.execute("INSERT INTO blueprint_activities VALUES (3004,'manufacturing',3600)")
        # 无制造蓝图的物品 2005
    return db_manager


def _patch_prices(monkeypatch):
    monkeypatch.setattr(
        rc,
        "_prices",
        lambda ids: {t: (10.0 if t == 1001 else 50.0 if t == 1002 else 1.0) for t in ids},
    )


class TestResearchCostsBatch:
    def test_t1_copy_cost(self, db_manager, monkeypatch):
        _build_ref(db_manager)
        _patch_prices(monkeypatch)
        with db_manager.connect("ref") as conn:
            cost = rc.research_costs_batch(conn, [2001])[2001]
            assert cost is not None
            assert cost > 0  # 拷贝材料 5×10 + 安装费

    def test_t2_invention_cost(self, db_manager, monkeypatch):
        _build_ref(db_manager)
        _patch_prices(monkeypatch)
        with db_manager.connect("ref") as conn:
            cost = rc.research_costs_batch(conn, [2002])[2002]
            assert cost is not None
            assert cost > 0

    def test_blueprint_original_none(self, db_manager, monkeypatch):
        _build_ref(db_manager)
        _patch_prices(monkeypatch)
        with db_manager.connect("ref") as conn:
            assert rc.research_costs_batch(conn, [3004])[3004] is None

    def test_no_blueprint_none(self, db_manager, monkeypatch):
        _build_ref(db_manager)
        _patch_prices(monkeypatch)
        with db_manager.connect("ref") as conn:
            assert rc.research_costs_batch(conn, [2005])[2005] is None

    def test_batch_mixed(self, db_manager, monkeypatch):
        _build_ref(db_manager)
        _patch_prices(monkeypatch)
        with db_manager.connect("ref") as conn:
            result = rc.research_costs_batch(conn, [2001, 2002, 3004, 2005])
            assert result[2001] is not None
            assert result[2002] is not None
            assert result[3004] is None
            assert result[2005] is None

    def test_empty(self, db_manager, monkeypatch):
        _patch_prices(monkeypatch)
        with db_manager.connect("ref") as conn:
            assert rc.research_costs_batch(conn, []) == {}
