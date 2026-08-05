"""生产计划递归拆解测试 — services/plan_decompose.py"""

from types import SimpleNamespace

import services.plan_decompose as pd
from services import inventory_manager


def _build_dbs(db_manager):
    """bp 蓝图表（与生产拆分一致）；user 附随含 user_blueprints/hangars/inventory_items。"""
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
        lines = pd.decompose_plan({"product_type_id": 2001, "runs": 2, "parallels": 1, "me_level": 0}, mat_hangar_id=1)
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


class TestCollectGroupMembers:
    """collect_group_members — 跨选中行聚合相关组的母项与子项"""

    def test_cross_group_aggregation(self):
        all_plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
            {"id": 3, "group_id": 10, "child_level": 2},
            {"id": 4, "group_id": 20, "child_level": 0},
            {"id": 5, "group_id": 20, "child_level": 1},
            {"id": 6, "group_id": 30, "child_level": 0},  # 无关组
        ]
        selected = [all_plans[0], all_plans[3]]  # 选中组 10 与组 20 的母项
        parents, children = pd.collect_group_members(all_plans, selected)
        assert {p["id"] for p in parents} == {1, 4}
        assert {c["id"] for c in children} == {2, 3, 5}

    def test_orphan_parent_included(self):
        """游离母项（组号未落库）即使 all_plans 无同组行也应并入 parents"""
        all_plans = [
            {"id": 1, "group_id": 0, "child_level": 0},
            {"id": 2, "group_id": 0, "child_level": 1},
        ]
        parents, children = pd.collect_group_members(all_plans, [all_plans[0]])
        assert {p["id"] for p in parents} == {1}
        assert children == []

    def test_dedupe_by_id(self):
        """同一 plan id 在 all_plans 与 selected 中出现多次 → 去重"""
        all_plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 1, "group_id": 10, "child_level": 0},  # 重复行
            {"id": 2, "group_id": 10, "child_level": 1},
        ]
        selected = [all_plans[0], all_plans[1]]
        parents, children = pd.collect_group_members(all_plans, selected)
        assert len(parents) == 1
        assert {p["id"] for p in parents} == {1}
        assert {c["id"] for c in children} == {2}

    def test_selected_child_aggregates_whole_group(self):
        """选中子项行也能把整组（母项+子项）聚合出来"""
        all_plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
        ]
        parents, children = pd.collect_group_members(all_plans, [all_plans[1]])
        assert {p["id"] for p in parents} == {1}
        assert {c["id"] for c in children} == {2}

    def test_no_id_falls_back_to_identity(self):
        """无 id 的计划行退化用对象身份去重（不崩溃）"""
        p1 = {"group_id": 10, "child_level": 0}
        p1_dup = {"group_id": 10, "child_level": 0}
        parents, _ = pd.collect_group_members([p1, p1_dup], [p1])
        assert len(parents) == 2  # 对象身份不同 → 视为不同行

    def test_empty_selection(self):
        parents, children = pd.collect_group_members([], [])
        assert parents == []
        assert children == []


class TestIsLeafPlan:
    """is_leaf_plan — 采购只统计叶子产线，跳过已拆解母项"""

    def test_ungrouped_is_leaf(self):
        assert pd.is_leaf_plan({"group_id": 0, "child_level": 0}, [])

    def test_mother_with_children_not_leaf(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
        ]
        assert not pd.is_leaf_plan(plans[0], plans)  # 母项有子项 → 非叶子
        assert pd.is_leaf_plan(plans[1], plans)  # 子项 → 叶子

    def test_deepest_subitem_is_leaf(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
            {"id": 3, "group_id": 10, "child_level": 2},
        ]
        assert not pd.is_leaf_plan(plans[1], plans)  # 1 级子项还有 2 级 → 非叶子
        assert pd.is_leaf_plan(plans[2], plans)

    def test_different_group_ignored(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 20, "child_level": 1},  # 不同组
        ]
        assert pd.is_leaf_plan(plans[0], plans)  # 组内无子项 → 叶子


class TestCollectCascadeDeleteIds:
    """collect_cascade_delete_ids — 删除母项级联删除同组子项"""

    def test_delete_mother_cascades_subitems(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
            {"id": 3, "group_id": 10, "child_level": 2},
            {"id": 4, "group_id": 20, "child_level": 0},  # 无关组
        ]
        ids = pd.collect_cascade_delete_ids(plans, {1})
        assert ids == {1, 2, 3}  # 母项 + 全部子项

    def test_delete_subitem_only_its_descendants(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
            {"id": 3, "group_id": 10, "child_level": 2},
        ]
        ids = pd.collect_cascade_delete_ids(plans, {2})
        assert ids == {2, 3}  # 只删 1 级及更深，母项保留

    def test_other_group_untouched(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
            {"id": 3, "group_id": 20, "child_level": 0},
            {"id": 4, "group_id": 20, "child_level": 1},
        ]
        ids = pd.collect_cascade_delete_ids(plans, {1})
        assert ids == {1, 2}  # 组 20 不受影响

    def test_ungrouped_plan_deleted_alone(self):
        plans = [{"id": 1, "group_id": 0, "child_level": 0}]
        assert pd.collect_cascade_delete_ids(plans, {1}) == {1}


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
