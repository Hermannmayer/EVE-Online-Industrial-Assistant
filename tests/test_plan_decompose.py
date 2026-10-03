"""生产计划递归拆解测试 — services/plan_decompose.py"""

from types import SimpleNamespace

import services.plan_decompose as pd
from services import inventory_manager


def _build_dbs(db_manager):
    """bp 蓝图表（与生产拆分一致）；user 附随含 user_blueprints/hangars/inventory_items。

    `production_plans` 也建出来：`decompose_plan` 现在按落库同一条口径读既有子项的
    `parallels`（见 `plan_decompose._existing_parallels`），真库一定有这张表。
    """
    from services.repositories.plan_repository import PlanRepository

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
        conn.executescript(PlanRepository.SCHEMA)
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
    monkeypatch.setattr(inventory_manager, "_default_db", lambda: db_manager)


class TestDecomposePlan:
    def test_two_levels(self, db_manager, monkeypatch):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        lines = pd.decompose_plan({"product_type_id": 2001, "runs": 2, "parallels": 1, "me_level": 0})
        # 2001 材料 1001×5 → 需 10 → 1001 有蓝图 → 中间产线；35 叶子不拆
        assert len(lines) == 1
        assert lines[0]["product_type_id"] == 1001
        assert lines[0]["sub_level"] == 1
        assert lines[0]["demand"] == 10  # 母项对 1001 的总需求（1X）
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


class TestPreviewMatchesRebuild:
    """预览（decompose_plan）与落库（rebuild_children）必须是同一组 runs/parallels。

    回归背景：预览曾走独立的 `_decompose` 折算（ceil 且 parallels 恒为 1、自己再扣一次库存、
    **库存覆盖到 0 就整行不建**），落库走 `compute_child_forest` + `_finalize_runs`
    （先扣库存再摊并行、需求>0 至少排 1 轮）。同一份输入因此给出两套数字 —— 用户实测
    对话框预览 11554=1360 / 41484=12，确认后表里是 2040 / 4。
    """

    def test_preview_matches_landed_runs_and_parallels(self, db_manager, monkeypatch):
        from services import plan_rebuild
        from services.repositories.plan_repository import PlanRepository

        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        monkeypatch.setattr(
            plan_rebuild,
            "get_container",
            lambda: SimpleNamespace(db=db_manager, plan_repo=PlanRepository(db_manager)),
        )
        with db_manager.connect("ref") as conn:
            # 落库路径的 `_resolve_name` 要查 ref.item
            conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
            conn.execute("INSERT INTO item VALUES (1001,'碳纤维','Carbon Fiber')")
            conn.execute("INSERT INTO item VALUES (35,'三钛合金','Tritanium')")
        with db_manager.connect("bp") as conn:
            # 给 35 配一张蓝图 → 母项拆出两条子项线（35 ← 34×2，34 无蓝图是叶子）
            conn.execute("INSERT INTO blueprint_products VALUES (3003,'manufacturing',35,1)")
            conn.execute("INSERT INTO blueprint_materials VALUES (3003,'manufacturing',34,2)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3003,'manufacturing',600)")
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, runs, parallels, me_level, "
                "status, group_number, sub_level, mat_hangar_id) "
                "VALUES (1, 2001, '渡鸦级', 2, 1, 0, 'pending', 7, 0, 1)"
            )
            # 机库库存：1001 需 10 有 6（净差 4）；35 需 20 有 20（库存全顶 → 仍要排 1 轮）
            conn.execute("INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price) VALUES (1,1001,6,0)")
            conn.execute("INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price) VALUES (1,35,20,0)")

        plan = {
            "id": 1,
            "product_type_id": 2001,
            "runs": 2,
            "parallels": 1,
            "me_level": 0,
            "group_number": 7,
            "sub_level": 0,
            "mat_hangar_id": 1,
        }
        preview = {
            int(line["product_type_id"]): (int(line["runs"]), int(line["parallels"]))
            for line in pd.decompose_plan(dict(plan), mat_hangar_id=1)
        }
        plan_rebuild.rebuild_children(create=True, prune=True, mother_ids={1})
        with db_manager.connect("user") as conn:
            landed = {
                int(r["product_type_id"]): (int(r["runs"]), int(r["parallels"]))
                for r in conn.execute(
                    "SELECT product_type_id, runs, parallels FROM production_plans WHERE sub_level > 0"
                ).fetchall()
            }

        # 逐位一致（含「库存全顶住的那条线」：预览不许把整行丢掉，落库也没有丢）
        assert preview == landed
        assert preview == {1001: (4, 1), 35: (1, 1)}

        # 既有子项行设过并行（用户在并行弹窗里设的）→ 预览必须按同一组 `existing_parallels`
        # 折算，否则预览按 1 条线摊、落库以用户线数为上限寻优，又是两套数字（实测母项 311 的
        # 41484 就是这个：预览 12 轮 × 1 线，落库以既有 5 线为上限寻优成 3 轮 × 4 线）。
        with db_manager.connect("user") as conn:
            conn.execute("UPDATE production_plans SET parallels=5 WHERE product_type_id=1001 AND sub_level>0")

        preview2 = {
            int(line["product_type_id"]): (int(line["runs"]), int(line["parallels"]))
            for line in pd.decompose_plan(dict(plan), mat_hangar_id=1)
        }
        plan_rebuild.rebuild_children(create=True, prune=True, mother_ids={1})
        with db_manager.connect("user") as conn:
            landed2 = {
                int(r["product_type_id"]): (int(r["runs"]), int(r["parallels"]))
                for r in conn.execute(
                    "SELECT product_type_id, runs, parallels FROM production_plans WHERE sub_level > 0"
                ).fetchall()
            }

        assert preview2 == landed2
        # 净差 4 个线·轮 → 寻优到 4 线 × 1 轮（零多余）；旧值 (1, 5) 是「沿用既有并行不寻优」，
        # 会 5×1=5 多造 1 个（见 `plan_rebuild._finalize_runs` 的并行数寻优）。
        assert preview2 == {1001: (1, 4), 35: (1, 1)}


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
        assert pd.is_leaf_plan({"group_id": 0, "child_level": 0}, []) is True

    def test_mother_with_children_not_leaf(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
        ]
        assert pd.is_leaf_plan(plans[0], plans) is False  # 母项有子项 → 非叶子
        assert pd.is_leaf_plan(plans[1], plans) is True  # 子项 → 叶子

    def test_deepest_subitem_is_leaf(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 10, "child_level": 1},
            {"id": 3, "group_id": 10, "child_level": 2},
        ]
        assert pd.is_leaf_plan(plans[1], plans) is False  # 1 级子项还有 2 级 → 非叶子
        assert pd.is_leaf_plan(plans[2], plans) is True

    def test_different_group_ignored(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0},
            {"id": 2, "group_id": 20, "child_level": 1},  # 不同组
        ]
        assert pd.is_leaf_plan(plans[0], plans) is True  # 组内无子项 → 叶子


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


class TestCollectRemovedChildIds:
    """collect_removed_child_ids — 母项拆解删除集（组内血缘，不误伤兄弟支系）"""

    def test_delete_type_and_its_group_descendants(self):
        rows = [
            {"id": 1, "product_type_id": 2003, "group_number": 1, "sub_level": 1, "component_parent_type_id": 2001},
            {"id": 2, "product_type_id": 2004, "group_number": 1, "sub_level": 2, "component_parent_type_id": 2003},
            {"id": 3, "product_type_id": 2005, "group_number": 1, "sub_level": 2, "component_parent_type_id": 2002},
            {"id": 4, "product_type_id": 2004, "group_number": 2, "sub_level": 1, "component_parent_type_id": 9999},
        ]
        ids = pd.collect_removed_child_ids(rows, {2003})
        assert ids == {1, 2}  # 2003 及其同组子孙；兄弟 2005 与他组 2004 不删

    def test_transitive_depth(self):
        rows = [
            {"id": 1, "product_type_id": 2003, "group_number": 1, "sub_level": 1, "component_parent_type_id": 2001},
            {"id": 2, "product_type_id": 2004, "group_number": 1, "sub_level": 2, "component_parent_type_id": 2003},
            {"id": 3, "product_type_id": 2005, "group_number": 1, "sub_level": 3, "component_parent_type_id": 2004},
        ]
        assert pd.collect_removed_child_ids(rows, {2003}) == {1, 2, 3}

    def test_cross_group_seed_rows_all_deleted(self):
        rows = [
            {"id": 1, "product_type_id": 2003, "group_number": 1, "sub_level": 1, "component_parent_type_id": 2001},
            {"id": 4, "product_type_id": 2003, "group_number": 2, "sub_level": 1, "component_parent_type_id": 9999},
            {"id": 5, "product_type_id": 2003, "group_number": 3, "sub_level": 2, "component_parent_type_id": None},
        ]
        assert pd.collect_removed_child_ids(rows, {2003}) == {1, 4, 5}

    def test_empty_removed(self):
        rows = [{"id": 1, "product_type_id": 2003, "group_number": 1, "sub_level": 1, "component_parent_type_id": 2001}]
        assert pd.collect_removed_child_ids(rows, set()) == set()

    def test_mother_rows_not_touched(self):
        rows = [
            {"id": 1, "product_type_id": 2001, "group_number": 1, "sub_level": 0, "component_parent_type_id": None},
            {"id": 2, "product_type_id": 2003, "group_number": 1, "sub_level": 1, "component_parent_type_id": 2001},
        ]
        assert pd.collect_removed_child_ids(rows, {2003}) == {2}


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
