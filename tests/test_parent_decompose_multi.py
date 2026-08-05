"""母项拆解弹窗多母项测试 — parent_decompose_dialog.py（需求1：智能调整支持多行）"""

from types import SimpleNamespace

import services.plan_decompose as pd
from services import inventory_manager
from ui_pyside6.views.industry import parent_decompose_dialog as dlg_mod
from ui_pyside6.views.industry.parent_decompose_dialog import ParentDecomposeDialog


def _build_dbs(db_manager):
    """ref item + bp 蓝图表 + user production_plans/hangars/inventory_items（与生产拆分一致）。"""
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute("INSERT INTO item VALUES (1001,'碳纤维','Carbon Fiber')")
        conn.execute("INSERT INTO item VALUES (35,'三钛合金','Tritanium')")
        conn.execute("INSERT INTO item VALUES (34,'类银超金属','Pyerite')")
        conn.execute("INSERT INTO item VALUES (2001,'渡鸦级','Raven')")
    with db_manager.connect("bp") as conn:
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        # 2001 ← bp3001(材料 1001×5 + 35×10)；1001 ← bp3002(材料 34×2)
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',1001,5)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',35,10)")
        conn.execute("INSERT INTO blueprint_materials VALUES (3002,'manufacturing',34,2)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',3600)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',1800)")
    with db_manager.connect("user") as conn:
        conn.execute(
            "CREATE TABLE production_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, product_type_id INTEGER, "
            "product_name TEXT, blueprint_type_id INTEGER, runs INTEGER DEFAULT 1, parallels INTEGER DEFAULT 1, "
            "me_level INTEGER DEFAULT 0, te_level INTEGER DEFAULT 0, status TEXT DEFAULT 'pending', "
            "group_number INTEGER DEFAULT 0, sub_level INTEGER DEFAULT 0, mat_hangar_id INTEGER, "
            "solar_system_id INTEGER, materials_ready INTEGER DEFAULT 0)"
        )
        conn.execute("CREATE TABLE hangars (id INTEGER PRIMARY KEY, name TEXT, solar_system_id INTEGER)")
        conn.execute("INSERT INTO hangars VALUES (1,'矿仓',30000145)")
        conn.execute(
            "CREATE TABLE inventory_items (id INTEGER PRIMARY KEY, hangar_id INTEGER, "
            "type_id INTEGER, quantity INTEGER, cost_price REAL)"
        )
        conn.execute(
            "CREATE TABLE user_blueprints (id INTEGER PRIMARY KEY, hangar_id INTEGER, "
            "blueprint_type_id INTEGER, is_bpo INTEGER DEFAULT 1, me_level INTEGER DEFAULT 0, "
            "te_level INTEGER DEFAULT 0, runs INTEGER DEFAULT 1, quantity INTEGER DEFAULT 1)"
        )
    return db_manager


def _patch(db_manager, monkeypatch):
    monkeypatch.setattr(pd, "get_container", lambda: SimpleNamespace(db=db_manager))
    monkeypatch.setattr(inventory_manager, "db", db_manager)
    monkeypatch.setattr(dlg_mod, "get_container", lambda: SimpleNamespace(db=db_manager))
    monkeypatch.setattr(dlg_mod.QMessageBox, "information", lambda *a, **k: None)


def _mother(plan_id, product_type_id=2001, group_number=0, **overrides):
    m = {
        "id": plan_id,
        "product_type_id": product_type_id,
        "runs": 2,
        "parallels": 1,
        "me_level": 0,
        "mat_hangar_id": 1,
        "sub_level": 0,
        "group_number": group_number,
    }
    m.update(overrides)
    return m


class TestParentDecomposeDialogMulti:
    def test_two_parents_get_distinct_groups(self, db_manager, monkeypatch, qapp):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute("INSERT INTO production_plans (id, product_type_id) VALUES (1, 2001)")
            conn.execute("INSERT INTO production_plans (id, product_type_id) VALUES (2, 2001)")
        dlg = ParentDecomposeDialog([_mother(1), _mother(2)])
        assert len(dlg._assignments) == 2
        gnums = {g for _, g, _ in dlg._assignments}
        assert len(gnums) == 2  # 每个母项一个独立组号

        dlg._on_accept()
        with db_manager.connect("user") as conn:
            mothers = conn.execute(
                "SELECT id, group_number, sub_level FROM production_plans WHERE id IN (1,2) ORDER BY id"
            ).fetchall()
            assert [m[2] for m in mothers] == [0, 0]  # sub_level=0
            assert len({m[1] for m in mothers}) == 2  # 组号互异
            subs = conn.execute(
                "SELECT product_type_id, sub_level, materials_ready, group_number "
                "FROM production_plans WHERE id NOT IN (1,2) ORDER BY id"
            ).fetchall()
            assert len(subs) == 2  # 每组各一个子项
            assert all(s[0] == 1001 for s in subs)
            assert all(s[1] == 1 for s in subs)  # 子级 1
            assert all(s[2] == 1 for s in subs)  # materials_ready=1（需求4 自动勾选）
            assert len({s[3] for s in subs}) == 2  # 落在各自组

    def test_reuses_existing_group_number(self, db_manager, monkeypatch, qapp):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, group_number, sub_level) " "VALUES (1, 2001, 7, 0)"
            )
        dlg = ParentDecomposeDialog([_mother(1, group_number=7)])
        assert dlg._assignments[0][1] == 7  # 已有组号 7 复用
        assert len({g for _, g, _ in dlg._assignments}) == 1

    def test_skip_mother_without_lines(self, db_manager, monkeypatch, qapp):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        # 99999 无蓝图 → decompose_plan 返回 [] → 不分配组号、不落库
        dlg = ParentDecomposeDialog([_mother(3, product_type_id=99999)])
        assert dlg._assignments == []

    def test_new_group_number_above_max(self, db_manager, monkeypatch, qapp):
        """无组号母项从 MAX(group_number)+1 起分配，不与既有组号撞号。"""
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, group_number, sub_level) " "VALUES (1, 2001, 3, 0)"
            )
        # 两个无组号母项 → 从 MAX(3)+1=4 起，得 4、5
        dlg = ParentDecomposeDialog([_mother(5, group_number=0), _mother(6, group_number=0)])
        gnums = sorted(g for _, g, _ in dlg._assignments)
        assert gnums == [4, 5]

    def test_redecompose_refreshes_existing_child(self, db_manager, monkeypatch, qapp):
        """已拆解的母项重跑拆解 → 已存在子项的 runs/parallels 按新 line 整体刷新（不残留旧并行数）。"""
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, group_number, sub_level, "
                "runs, parallels) VALUES (1, 2001, '渡鸦级', 7, 0, 2, 1)"
            )
            # 残留子项：并行 5（用户并行弹窗设过）、runs 与需求不符
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, blueprint_type_id, "
                "group_number, sub_level, runs, parallels) VALUES (2, 1001, '碳纤维', 3002, 7, 1, 3, 5)"
            )
        dlg = ParentDecomposeDialog([_mother(1, group_number=7)])
        dlg._on_accept()
        with db_manager.connect("user") as conn:
            row = conn.execute(
                "SELECT runs, parallels, me_level, te_level FROM production_plans WHERE id=2"
            ).fetchone()
        # 需求=5×2=10，单轮产出 1 → runs=10；parallels 重置为拆解默认 1，ME-TE 刷新
        assert tuple(row) == (10, 1, 0, 0)
