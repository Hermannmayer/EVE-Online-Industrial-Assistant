"""plan_service 测试 — 共享「加入制造规划」落库"""

from types import SimpleNamespace

import pytest

from services import plan_execution, plan_service


def _build_user(db_manager):
    with db_manager.connect("user") as conn:
        conn.execute(
            "CREATE TABLE production_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "product_type_id INTEGER, product_name TEXT, runs INTEGER, parallels INTEGER, "
            "me_level INTEGER, te_level INTEGER, mat_hub TEXT, sell_hub TEXT, facility TEXT, "
            "char_name TEXT, status TEXT, profit REAL, margin REAL, score REAL, iskph REAL, "
            "material_cost REAL, calculated_time REAL, daily_output REAL, created_at TEXT, "
            "deposit_hangar_id INTEGER, mat_hangar_id INTEGER, solar_system_id INTEGER, "
            "materials_ready INTEGER DEFAULT 0, assigned_blueprint_id INTEGER DEFAULT NULL)"
        )
        # 自动绑定/释放读取的关联表（schema v7 迁移产物），测试库补齐
        conn.execute(
            "CREATE TABLE IF NOT EXISTS plan_blueprint_bindings ("
            "plan_id INTEGER NOT NULL, blueprint_id INTEGER NOT NULL, runs_used INTEGER DEFAULT 0, "
            "PRIMARY KEY (plan_id, blueprint_id))"
        )
    return db_manager


class _StubScoring:
    """容器里 `scoring_service()` 的最小替身：只认 `manufacturing_unit_costs`。

    默认「什么都算不出」= 空 dict（对应无制造蓝图/科研行产物/反应产物），
    界面据此显示 `—`；`calls` 记下每次问的 (type_ids, 参数)，供分组口径断言。
    """

    def __init__(self, unit_costs: dict[int, float] | None = None) -> None:
        self.unit_costs = unit_costs or {}
        self.calls: list[tuple[list[int], dict]] = []

    def manufacturing_unit_costs(self, type_ids, **kw) -> dict[int, float]:
        self.calls.append((sorted(int(t) for t in type_ids), kw))
        return {int(t): self.unit_costs[int(t)] for t in type_ids if int(t) in self.unit_costs}


def _patch_container(db_manager, monkeypatch, scoring=None):
    container = SimpleNamespace(db=db_manager, scoring_service=lambda: scoring or _StubScoring())
    monkeypatch.setattr(plan_service, "get_container", lambda: container)
    # insert_plan/insert_plans_batch 内部自动绑定走 plan_execution._container，也指向临时库
    monkeypatch.setattr(plan_execution, "_container", lambda: container)


def test_enrich_icon_type_id_uses_the_blueprint_product_for_science_rows():
    """科研行的图标 type_id 取「这张蓝图造出来的物品」。

    回归（2026-10-06 用户报）：科研行的 `product_type_id` 是**蓝图**，而图标缓存里只有
    物品（没有蓝图 png）—— 拿它去查必然没有图标，产线小助手的行首于是只剩类别首字
    「科」。制造行不受影响（产物本身就是物品）。
    """
    enrich = {
        "owned_bp": set(),
        "prod_to_bp": {},
        "bp_to_prod": {3009: 2002},
        "hangar_names": {},
        "binding_map": {},
        "need_map": {},
        "bp_level": {},
        "cap_map": {},
    }
    rows = plan_service._enrich_rows(
        [
            {"id": 1, "product_type_id": 2001, "activity": "manufacturing"},
            {"id": 2, "product_type_id": 3009, "activity": "invention"},
            {"id": 3, "product_type_id": 3008, "activity": "copying"},  # 蓝图没查到产物 → 0
        ],
        enrich,
    )

    assert [r["icon_type_id"] for r in rows] == [2001, 2002, 0]


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


# ══════════════════════════════════════════
#  group_and_sort_plans — 母项在前树状排序
# ══════════════════════════════════════════


class TestGroupAndSortPlans:
    def test_parent_first_children_after(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0, "status": "pending"},
            {"id": 3, "group_id": 10, "child_level": 2, "status": "pending"},
            {"id": 2, "group_id": 10, "child_level": 1, "status": "pending"},
            {"id": 9, "group_id": 0, "child_level": 0, "status": "pending"},
        ]
        ordered = plan_service.group_and_sort_plans(plans)
        assert [p["id"] for p in ordered] == [1, 2, 3, 9]

    def test_pending_children_attached_to_parent(self):
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0, "status": "pending"},
            {"id": 2, "group_id": 10, "child_level": 1, "status": "pending"},
            {"id": 3, "group_id": 10, "child_level": 1, "status": "in_progress"},
            {"id": 4, "group_id": 10, "child_level": 1, "status": "completed"},
        ]
        ordered = plan_service.group_and_sort_plans(plans)
        assert ordered[0]["_pending_children"] == 2  # 完成态不计

    def test_multiple_groups_then_standalone(self):
        plans = [
            {"id": 9, "group_id": 0, "child_level": 0, "status": "pending"},
            {"id": 5, "group_id": 20, "child_level": 0, "status": "pending"},
            {"id": 6, "group_id": 20, "child_level": 1, "status": "pending"},
            {"id": 1, "group_id": 10, "child_level": 0, "status": "pending"},
            {"id": 2, "group_id": 10, "child_level": 1, "status": "pending"},
        ]
        ordered = plan_service.group_and_sort_plans(plans)
        ids = [p["id"] for p in ordered]
        assert ids == [1, 2, 5, 6, 9]  # 组 10 → 组 20 → 独立计划殿后

    def test_no_pending_children_key_on_standalone(self):
        plans = [{"id": 9, "group_id": 0, "child_level": 0, "status": "pending"}]
        ordered = plan_service.group_and_sort_plans(plans)
        assert "_pending_children" not in ordered[0]

    def test_shared_children_lifted_to_synthetic_root(self):
        """跨 ≥2 母项引用的子行提升到「共享组件」合成根（group_id=-1），殿后于各母项组。"""
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0, "status": "pending"},
            {"id": 2, "group_id": 10, "child_level": 1, "status": "pending"},
            {"id": 5, "group_id": 20, "child_level": 0, "status": "pending"},
            {"id": 3, "group_id": 20, "child_level": 1, "source_mother_ids": "1,5", "status": "pending"},
        ]
        ordered = plan_service.group_and_sort_plans(plans)
        assert [p["id"] for p in ordered] == [1, 2, 5, None, 3]  # 合成根 id=None
        assert ordered[3]["_synthetic"] is True
        assert ordered[3]["group_id"] == -1
        assert ordered[3]["product_name"] == "共享组件"

    def test_single_source_child_stays_in_mother_group(self):
        """仅被一个母项引用的子行保留在原组（不提升共享区）。"""
        plans = [
            {"id": 1, "group_id": 10, "child_level": 0, "status": "pending"},
            {"id": 2, "group_id": 10, "child_level": 1, "source_mother_ids": "1", "status": "pending"},
        ]
        ordered = plan_service.group_and_sort_plans(plans)
        assert [p["id"] for p in ordered] == [1, 2]  # 不插入合成根


# ══════════════════════════════════════════
#  load_plans_for_wizard — 非完成计划数据源
# ══════════════════════════════════════════


class TestLoadPlansForWizard:
    def test_excludes_completed_and_enriches(self, temp_db, monkeypatch):
        _build_user(temp_db)
        with temp_db.connect("user") as conn:
            conn.execute("CREATE TABLE hangars (id INTEGER PRIMARY KEY, name TEXT, solar_system_id INTEGER)")
            conn.execute(
                "CREATE TABLE user_blueprints (id INTEGER PRIMARY KEY, blueprint_type_id INTEGER,"
                " hangar_id INTEGER, is_bpo INTEGER, me_level INTEGER, te_level INTEGER,"
                " runs INTEGER, quantity INTEGER, notes TEXT)"
            )
            for i, status in enumerate(["pending", "in_progress", "completed", "done"], start=1):
                conn.execute(
                    "INSERT INTO production_plans (id, product_type_id, product_name, status) VALUES (?,?,?,?)",
                    (i, 2001, f"计划{i}", status),
                )
        _patch_container(temp_db, monkeypatch)
        rows = plan_service.load_plans_for_wizard()
        statuses = [r["status"] for r in rows]
        assert "completed" not in statuses
        assert "done" not in statuses
        assert len(rows) == 2
        assert all("category" in r for r in rows)
        assert all("has_image" in r for r in rows)
        assert all("group_id" in r for r in rows)


class TestLineLevels:
    """逐线 ME/TE 列表 —— 并行产线各按绑定蓝图结算。"""

    def test_all_bound(self):
        from services.plan_service import _line_levels

        assert _line_levels([10, 11], 2, {10: (5, 10), 11: (8, 20)}) == [(5, 10), (8, 20)]

    def test_unbound_lines_take_worst_bound(self):
        """未绑的线取已绑里最差那张：ME 与 TE **分别**取最小值（各自保守界）。"""
        from services.plan_service import _line_levels

        assert _line_levels([10, 11], 3, {10: (5, 20), 11: (8, 10)}) == [(5, 20), (8, 10), (5, 10)]

    def test_no_binding_returns_empty(self):
        """一张没绑 → 空列表，由 calculate_plan_metrics 回退计划级。"""
        from services.plan_service import _line_levels

        assert _line_levels([], 2, {10: (5, 10)}) == []

    def test_unknown_blueprint_ids_ignored(self):
        from services.plan_service import _line_levels

        assert _line_levels([999], 1, {10: (5, 10)}) == []

    def test_more_bound_than_need_truncates(self):
        from services.plan_service import _line_levels

        assert _line_levels([10, 11, 12], 2, {10: (5, 10), 11: (6, 11), 12: (7, 12)}) == [(5, 10), (6, 11)]


def test_attach_make_costs_groups_by_hub_and_hangar_and_keeps_none(monkeypatch):
    """「自制成本/件」补数：按（材料 Hub, 材料机库）分组批量问，**算不出的保持 None**。

    helper 不返回的 type（无制造蓝图 / 取不到价 / 科研行产物是蓝图 / 反应产物）不能填 0
    —— 界面靠 `None` 显示 `—`，0 会被读成「自己造不要钱」。
    """
    stub = _StubScoring({2001: 1234.5})
    _patch_container(None, monkeypatch, stub)

    rows = plan_service._attach_make_costs(
        [
            {"id": 1, "product_type_id": 2001, "mat_hub": "Jita", "mat_hangar_id": 5},
            {"id": 2, "product_type_id": 3009, "mat_hub": "Jita", "mat_hangar_id": 5},
            {"id": 3, "product_type_id": 2002, "mat_hub": "Amarr", "mat_hangar_id": None},
            {"id": 4, "product_type_id": None},
        ]
    )

    assert [r["make_cost"] for r in rows] == [1234.5, None, None, None]
    assert [(tids, kw["mat_hub"], kw["hangar_id"]) for tids, kw in stub.calls] == [
        ([2001, 3009], "Jita", 5),
        ([2002], "Amarr", None),
    ]


def test_attach_make_costs_folds_group_subitem_make_cost(temp_db, monkeypatch):
    """拆解母项的「自制成本/件」按同组更深子项的**自制单件成本**折算。

    回归：只看当前 filter 的 rows 会让被筛掉的子项按**市价**算 —— 母项成本虚高
    （真库 383 灼烧 XL：1,423,889.99 市价口径 → 959,435 自制口径）。子项行必须
    直接从 user.db 按 `group_number` 查。
    """
    from core.cache import TtlLRUCache
    from services.scoring_service import ScoringService

    with temp_db.connect("user") as conn:
        conn.execute(
            "CREATE TABLE production_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "product_type_id INTEGER, group_number INTEGER DEFAULT 0, sub_level INTEGER DEFAULT 0, "
            "runs INTEGER DEFAULT 1, parallels INTEGER DEFAULT 1, mat_hub TEXT, mat_hangar_id INTEGER)"
        )
        conn.execute(
            "INSERT INTO production_plans (id, product_type_id, group_number, sub_level, runs, parallels, mat_hub) "
            "VALUES (1, 2001, 7, 0, 1, 1, 'Jita'), (2, 2002, 7, 1, 1, 1, 'Jita')"
        )
    # 渡鸦级(2001) 多要 2 个无人机(2002)：同组另有一条 2002 的自制产线
    with temp_db.connect("bp") as conn:
        conn.execute("INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 2002, 2, 10)")

    svc = ScoringService(temp_db, TtlLRUCache(max_size=10))
    _patch_container(temp_db, monkeypatch, svc)

    sub_cost = svc.manufacturing_unit_costs([2002], mat_hub="Jita", price_type_mat="sell")[2002]
    plain = svc.manufacturing_unit_costs([2001], mat_hub="Jita", price_type_mat="sell")[2001]
    expected = svc.manufacturing_unit_costs(
        [2001], mat_hub="Jita", price_type_mat="sell", cost_overrides={2002: sub_cost}
    )[2001]

    rows = plan_service._attach_make_costs(
        [{"id": 1, "product_type_id": 2001, "group_number": 7, "sub_level": 0, "mat_hub": "Jita"}]
    )

    assert expected < plain, "自制件比市价便宜，折算后必须更低（否则这个用例测不出折叠）"
    assert rows[0]["make_cost"] == pytest.approx(expected, abs=0.01)
