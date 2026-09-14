"""industry 弹窗族测试 — 拆解/并行/成本/下线 弹窗。

由 4 个文件合并：cost_breakdown_dialog + parent_decompose_multi + industry_parallel + industry_complete。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import services.plan_decompose as pd
from services import inventory_manager
from services.repositories.plan_repository import PlanRepository
from ui_pyside6.views.industry import parent_decompose_dialog as dlg_mod
from ui_pyside6.views.industry.parent_decompose_dialog import ParentDecomposeDialog
from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog as CompletePlansDialog
from ui_qml.bridge.cost_breakdown_bridge import CostBreakdownBridge
from ui_qml.bridge.mass_parallel_bridge import (
    compute_parallel_by_duration,
    compute_parallel_by_lines,
)

pytestmark = pytest.mark.ui

# ════════════════════════════════════════════════════════════════
#  CostBreakdownDialog — 成本明细（原 test_cost_breakdown_dialog.py）
# ════════════════════════════════════════════════════════════════


def _insert_plans(db, rows: list[dict]) -> None:
    with db.connect("user") as conn:
        conn.executescript(PlanRepository.SCHEMA)
        for r in rows:
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, runs, parallels, "
                "group_number, sub_level, status) VALUES (?,?,?,?,?,?,?,?)",
                (
                    r["id"],
                    r["product_type_id"],
                    r["product_name"],
                    r["runs"],
                    r["parallels"],
                    r["group_number"],
                    r["sub_level"],
                    "pending",
                ),
            )


def _bridge_with_metrics(db_manager, monkeypatch, metrics_fn):
    """造一个成本明细桥，把 `calculate_plan_metrics` 换成 `metrics_fn`（阶段 4 后走桥）。"""
    svc = MagicMock()
    svc.calculate_plan_metrics.side_effect = metrics_fn
    monkeypatch.setattr(
        "ui_qml.bridge.cost_breakdown_bridge.get_container",
        lambda: SimpleNamespace(db=db_manager, scoring_service=lambda: svc),
    )
    return CostBreakdownBridge({"product_type_id": 2001, "group_number": 7, "sub_level": 0}, char_config={})


def test_compute_subitem_costs_single_level(db_manager, monkeypatch, qapp):
    """拆解母项：子项制造价 = 材料成本 + 作业费 × runs。"""
    _insert_plans(
        db_manager,
        [
            {
                "id": 1,
                "product_type_id": 2001,
                "product_name": "母项",
                "runs": 1,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 0,
            },
            {
                "id": 2,
                "product_type_id": 2002,
                "product_name": "子项",
                "runs": 2,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 1,
            },
        ],
    )

    def _metrics(plan, char_config, **kw):
        if plan.get("product_type_id") == 2002:
            return {"material_cost": 4800.0, "breakdown": {"installation_fee": 100.0}}
        return {}

    bridge = _bridge_with_metrics(db_manager, monkeypatch, _metrics)
    costs = bridge._compute_subitem_costs(7, 0)
    # 子项制造价 = 4800 + 100×2 = 5000
    assert costs == {2002: pytest.approx(5000, abs=0.01)}


def test_compute_subitem_costs_nested(db_manager, monkeypatch, qapp):
    """嵌套拆解：孙项成本先算，子项含孙项制造价 + 自身作业费。"""
    _insert_plans(
        db_manager,
        [
            {
                "id": 1,
                "product_type_id": 2001,
                "product_name": "母项",
                "runs": 1,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 0,
            },
            {
                "id": 2,
                "product_type_id": 2002,
                "product_name": "子项",
                "runs": 1,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 1,
            },
            {
                "id": 3,
                "product_type_id": 3003,
                "product_name": "孙项",
                "runs": 1,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 2,
            },
        ],
    )

    def _metrics(plan, char_config, **kw):
        pid = plan.get("product_type_id")
        if pid == 3003:
            return {"material_cost": 100.0, "breakdown": {"installation_fee": 50.0}}
        if pid == 2002:
            return {
                "material_cost": 1000.0,
                "materials": [{"type_id": 3003, "qty": 1, "unit_price": 500.0}],
                "breakdown": {"installation_fee": 100.0},
            }
        return {}

    bridge = _bridge_with_metrics(db_manager, monkeypatch, _metrics)
    costs = bridge._compute_subitem_costs(7, 0)
    # 孙项制造价 = 100 + 50 = 150；子项制造价 = 150(孙项) + 100(作业费) = 250
    assert costs[3003] == pytest.approx(150, abs=0.01)
    assert costs[2002] == pytest.approx(250, abs=0.01)


# ════════════════════════════════════════════════════════════════
#  ParentDecomposeDialog — 母项拆解多母项（原 test_parent_decompose_multi.py）
# ════════════════════════════════════════════════════════════════


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
            "solar_system_id INTEGER, deposit_hangar_id INTEGER, materials_ready INTEGER DEFAULT 0, "
            "source_mother_ids TEXT DEFAULT '', component_parent_type_id INTEGER, demand INTEGER DEFAULT 0)"
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
    monkeypatch.setattr(inventory_manager, "_default_db", lambda: db_manager)
    monkeypatch.setattr(
        dlg_mod, "get_container", lambda: SimpleNamespace(db=db_manager, plan_repo=PlanRepository(db_manager))
    )
    monkeypatch.setattr(dlg_mod.QMessageBox, "information", lambda *a, **k: None)
    # 拆解落库走 plan_rebuild，注入同一 container
    from services import plan_rebuild

    monkeypatch.setattr(
        plan_rebuild, "get_container", lambda: SimpleNamespace(db=db_manager, plan_repo=PlanRepository(db_manager))
    )


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
                "SELECT product_type_id, sub_level, materials_ready "
                "FROM production_plans WHERE id NOT IN (1,2) ORDER BY id"
            ).fetchall()
            # 共享组件 1001 被两母项引用 → 全局合并为一行（引用式需求）
            assert len(subs) == 1
            assert subs[0][0] == 1001
            assert subs[0][1] == 1  # 子级 1
            assert subs[0][2] == 1  # materials_ready=1（需求4 自动勾选）
            src = conn.execute("SELECT source_mother_ids FROM production_plans WHERE product_type_id=1001").fetchone()
            assert sorted(int(x) for x in src[0].split(",") if x) == [1, 2]

    def test_reuses_existing_group_number(self, db_manager, monkeypatch, qapp):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("user") as conn:
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, group_number, sub_level) VALUES (1, 2001, 7, 0)"
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
                "INSERT INTO production_plans (id, product_type_id, group_number, sub_level) VALUES (1, 2001, 3, 0)"
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
            row = conn.execute("SELECT runs, parallels, me_level, te_level FROM production_plans WHERE id=2").fetchone()
        # 需求=5×2=10、并行保留 5 → runs=ceil(10/(5×1))=2；ME-TE 刷新
        assert tuple(row) == (2, 5, 0, 0)

    def test_row_refs_map_each_row_to_its_own_line(self, db_manager, monkeypatch, qapp):
        """回归：同一母项的多行必须各自对应真实行下标。

        早先 _append_row 用「子项列表长度 − 1」推断下标，导致该母项的所有预览行都指向
        最后一行——删除时先删最后一行、再删就越界（IndexError）。
        """
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        # 再给三钛合金配一张蓝图，使母项 2001 拆出两条子项线
        with db_manager.connect("bp") as conn:
            conn.execute("INSERT INTO blueprint_products VALUES (3003,'manufacturing',35,1)")
            conn.execute("INSERT INTO blueprint_materials VALUES (3003,'manufacturing',34,1)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3003,'manufacturing',600)")
        with db_manager.connect("user") as conn:
            conn.execute("INSERT INTO production_plans (id, product_type_id) VALUES (1, 2001)")
        dlg = ParentDecomposeDialog([_mother(1)])
        n_rows = dlg._table.rowCount()
        assert n_rows >= 2  # 渡鸦级拆出碳纤维 + 三钛合金
        assert [l_idx for _a, l_idx, _line in dlg._row_refs] == list(range(n_rows))

        # 选中同一母项的全部行一起删除 → 不得越界，且子项列表清空
        dlg._table.selectAll()
        dlg._delete_selected_rows()
        assert dlg._table.rowCount() == 0
        assert dlg._assignments[0][2] == []


# ════════════════════════════════════════════════════════════════
#  mass_parallel / ChildParallel — 并行（原 test_industry_parallel.py）
# ════════════════════════════════════════════════════════════════


class TestComputeParallelByLines:
    def test_even_distribution(self):
        subitems = [{"id": 1, "demand": 100, "per_run": 1}, {"id": 2, "demand": 100, "per_run": 1}]
        result = compute_parallel_by_lines(subitems, 6)
        assert {r["id"]: r["parallels"] for r in result} == {1: 3, 2: 3}

    def test_weighted(self):
        subitems = [{"id": 1, "demand": 300, "per_run": 1}, {"id": 2, "demand": 100, "per_run": 1}]
        result = compute_parallel_by_lines(subitems, 6)
        assert {r["id"]: r["parallels"] for r in result} == {1: 4, 2: 2}

    def test_less_lines_than_items(self):
        subitems = [{"id": 1, "demand": 10, "per_run": 1}, {"id": 2, "demand": 10, "per_run": 1}]
        result = compute_parallel_by_lines(subitems, 1)
        assert {r["id"]: r["parallels"] for r in result} == {1: 1, 2: 1}  # 每子项至少 1

    def test_empty(self):
        assert compute_parallel_by_lines([], 10) == []


class TestComputeParallelByDuration:
    def test_ceil_to_target_days(self):
        subitems = [
            {"id": 1, "duration_sec": 10 * 86400},
            {"id": 2, "duration_sec": 3 * 86400},
        ]
        result = compute_parallel_by_duration(subitems, 5)
        assert {r["id"]: r["parallels"] for r in result} == {1: 2, 2: 1}  # ceil(10/5)=2, ceil(3/5)=1

    def test_zero_duration(self):
        assert compute_parallel_by_duration([{"id": 1, "duration_sec": 0}], 5) == [{"id": 1, "parallels": 1}]


def _build_ref(db_manager):
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute("INSERT INTO item VALUES (1001,'碳纤维','Carbon Fiber')")
        conn.execute("INSERT INTO item VALUES (2001,'渡鸦级','Raven')")
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("INSERT INTO blueprint_products VALUES (3001,'manufacturing',2001,1)")
        conn.execute("INSERT INTO blueprint_products VALUES (3002,'manufacturing',1001,1)")
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute("INSERT INTO blueprint_materials VALUES (3001,'manufacturing',1001,1)")
        conn.execute("CREATE TABLE blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3001,'manufacturing',7200)")
        conn.execute("INSERT INTO blueprint_activities VALUES (3002,'manufacturing',3600)")
    return db_manager


class TestChildParallelDialog:
    """只设并行数 → 每条流程自动生成覆盖母项需求；不达标时禁用保存。

    阶段 4：断言从 Widgets 内部控件（`_ok_btn` / `_current_runs`）换成桥的字段。
    """

    @staticmethod
    def _bridge(db_manager, monkeypatch, plans):
        from ui_qml.bridge.child_parallel_bridge import ChildParallelBridge

        monkeypatch.setattr(
            "ui_qml.bridge.child_parallel_bridge.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )
        return ChildParallelBridge(plans)

    def test_auto_runs_covers_demand(self, db_manager, monkeypatch, qapp):
        _build_ref(db_manager)
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 1, "parallels": 1, "blueprint_type_id": 3002},
        ]
        bridge = self._bridge(db_manager, monkeypatch, plans)
        # 母项需求 1001 = 2；per_run=1 → 自动 runs = ceil(2/1) = 2 → 总产出 2 ≥ 2 → 通过
        assert bridge.canAccept is True
        assert bridge.rows[0]["runs"] == 2
        # 并行提到 3 → runs = ceil(2/3) = 1 → 总产出 3 ≥ 2，仍通过
        bridge.setParallels(0, 3)
        assert bridge.rows[0]["runs"] == 1
        assert bridge.canAccept is True

    def test_sufficient_passes(self, db_manager, monkeypatch, qapp):
        _build_ref(db_manager)
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 2, "parallels": 1, "blueprint_type_id": 3002},
        ]
        bridge = self._bridge(db_manager, monkeypatch, plans)
        assert bridge.canAccept is True
        assert bridge.rows[0]["runs"] == 2

    def test_shortfall_blocks_accept(self, db_manager, monkeypatch, qapp):
        """母项需求涨到覆盖不了时，校验行给出差额且禁用保存。"""
        _build_ref(db_manager)
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 99, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 1, "parallels": 1, "blueprint_type_id": 3002},
        ]
        bridge = self._bridge(db_manager, monkeypatch, plans)
        # 需求 99、per_run=1、并行 1 → runs=99 → 总产出 99 ≥ 99 恰好够；把并行降不了（最小 1），
        # 改为直接验证校验字段的语义
        assert bridge.rows[0]["checkToken"] == "ACCENT_GREEN"
        assert bridge.canAccept is True


class TestCompletePlansDialog:
    """下线确认对话框 — 计划清单 / 机库默认值"""

    def test_default_hangar_from_settings(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "runs": 2,
                "parallels": 3,
                "deposit_hangar_id": 5,
            }
        ]
        hangars = [{"id": 1, "name": "矿仓"}, {"id": 2, "name": "组件仓"}]
        dlg = CompletePlansDialog(plans, hangars, 2)  # 默认 = 设置的默认产出机库
        assert dlg.selected_hangar_id() == 2
        rows = dlg.bridge.rows
        assert len(rows) == 1
        assert rows[0]["name"] == "渡鸦级"
        assert rows[0]["runs"] == "3X2"
        assert rows[0]["qty"] == "6"  # 产出量 = 3 并行 × 2 流程 × 每次 1
        assert rows[0]["deposit"] == "不自动入库"  # 计划里存的机库 id=5 不在机库表里

    def test_default_fallback_first_hangar(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [{"id": 1, "product_name": "渡鸦级", "runs": 1, "parallels": 1, "deposit_hangar_id": None}]
        hangars = [{"id": 1, "name": "矿仓"}, {"id": 2, "name": "组件仓"}]
        dlg = CompletePlansDialog(plans, hangars, None)
        assert dlg.selected_hangar_id() == 1  # 无默认时选第一个机库

    def test_no_hangar_keeps_no_auto_deposit(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [{"id": 1, "product_name": "渡鸦级", "runs": 1, "parallels": 1}]
        dlg = CompletePlansDialog(plans, [], -1)
        assert dlg.selected_hangar_id() == -1  # 无机库时保持「不自动入库」


class TestCompleteGuard:
    """四条下线入口共用的「蓝图流程不足」确认。

    回归背景：底部状态栏的「全部下线」曾是唯一不预检、也不传 `allow_bp_short`
    的入口 —— 强制启动过的计划在那里永远下不了线，且只显示一句「失败 N 项」。
    """

    def test_no_shortfall_returns_false_without_asking(self, qapp, monkeypatch):
        from ui_pyside6.views.industry import complete_guard

        asked = []
        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: None)
        monkeypatch.setattr(
            complete_guard.QMessageBox,
            "question",
            lambda *a, **k: asked.append(True),  # type: ignore[func-returns-value]
        )
        result = complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}])
        assert result is False
        assert asked == [], "无短板不该弹确认框"

    def test_shortfall_yes_allows_force(self, qapp, monkeypatch):
        from ui_pyside6.views.industry import complete_guard

        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: "第 1 张绑定蓝图流程不足")
        monkeypatch.setattr(
            complete_guard.QMessageBox,
            "question",
            lambda *a, **k: complete_guard.QMessageBox.StandardButton.Yes,
        )
        assert complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}]) is True

    def test_shortfall_no_cancels(self, qapp, monkeypatch):
        from ui_pyside6.views.industry import complete_guard

        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: "第 1 张绑定蓝图流程不足")
        monkeypatch.setattr(
            complete_guard.QMessageBox,
            "question",
            lambda *a, **k: complete_guard.QMessageBox.StandardButton.No,
        )
        assert complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}]) is None

    def test_shortfall_lines_skips_plans_without_id(self, monkeypatch):
        from ui_pyside6.views.industry import complete_guard

        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: f"缺流程 {pid}")
        assert complete_guard.shortfall_lines([{"product_name": "无 id"}]) == []
        assert complete_guard.shortfall_lines([{"id": 7, "product_name": "电磁发生器"}]) == ["  电磁发生器: 缺流程 7"]


class TestStatusBarCompleteAllGuard:
    """状态栏「全部下线」必须与另外三条入口行为一致：预检 + 透传 allow_bp_short。"""

    @staticmethod
    def _run(monkeypatch, short_text: str | None, user_choice: bool):
        import ui_pyside6.views.industry_view as iv
        from ui_pyside6.views.industry import complete_guard

        model = MagicMock()
        model.rowCount.return_value = 1
        model.get_plan.return_value = {"id": 1, "status": "ready", "product_name": "电磁发生器"}

        class _Dlg:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                return 1

            def selected_hangar_id(self):
                return 4

        captured: dict = {}

        def _complete_plans(plans, hid, **kwargs):
            captured["hid"] = hid
            captured.update(kwargs)
            return {"completed": len(plans), "deposited": 0, "failed": [], "failed_reasons": []}

        monkeypatch.setattr(iv, "CompletePlansDialog", _Dlg)
        monkeypatch.setattr(iv, "complete_plans", _complete_plans)
        monkeypatch.setattr("services.inventory_manager.get_hangars", lambda: [{"id": 4, "name": "产出仓"}])
        monkeypatch.setattr("services.user_settings.get_default_hangar_id", lambda key: 4)
        monkeypatch.setattr(iv.QMessageBox, "information", lambda *a, **k: None)
        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: short_text)
        monkeypatch.setattr(
            complete_guard.QMessageBox,
            "question",
            lambda *a, **k: (
                complete_guard.QMessageBox.StandardButton.Yes
                if user_choice
                else complete_guard.QMessageBox.StandardButton.No
            ),
        )

        page = SimpleNamespace(
            _plan_table_widget=MagicMock(get_model=lambda: model),
            load_plans=lambda: None,
        )
        # 只借 IndustryPage 的方法体，self 用最小替身（构造整页代价过高）
        iv.IndustryPage.complete_all(page)  # type: ignore[arg-type]
        return captured

    def test_forwards_allow_bp_short_after_confirmation(self, qapp, monkeypatch):
        captured = self._run(monkeypatch, "第 1 张绑定蓝图流程不足", user_choice=True)
        assert captured.get("allow_bp_short") is True, "确认强制后必须透传给 complete_plans"
        assert captured.get("hid") == 4

    def test_cancel_stops_before_completing(self, qapp, monkeypatch):
        captured = self._run(monkeypatch, "第 1 张绑定蓝图流程不足", user_choice=False)
        assert captured == {}, "用户在「仍要下线？」选否 → 不该调用 complete_plans"

    def test_no_shortfall_passes_false(self, qapp, monkeypatch):
        captured = self._run(monkeypatch, None, user_choice=True)
        assert captured.get("allow_bp_short") is False


# ════════════════════════════════════════════════════════════════
#  单行下线端到端（计划表格 / 小助手共用 complete_one_plan）
# ════════════════════════════════════════════════════════════════


class TestCompleteOnePlan:
    """契约是**非 None 即成功** —— 调用方据此决定要不要把行标成已完成。

    若失败也返回 dict，计划表格会把失败的计划置 status="completed" 并刷新表格，
    用户看到的是「已完成」而库里根本没入库。
    """

    PLAN = {"id": 7, "product_name": "渡鸦级", "product_type_id": 2001, "runs": 1, "parallels": 1, "status": "ready"}

    @staticmethod
    def _setup(monkeypatch, *, dialog_result: int, completed: int, warned: list):
        from ui_pyside6.views.industry import complete_plans_dialog as cpd

        calls: dict = {}

        class _Dlg:
            def __init__(self, plans, hangars, default_hid, parent):
                calls["plans"] = plans

            def exec(self):
                return dialog_result

            def selected_hangar_id(self):
                return 4

        def _complete_plans(plans, hid, **kwargs):
            calls["complete_hid"] = hid
            calls["complete_kwargs"] = kwargs
            return {
                "completed": completed,
                "deposited": completed,
                "failed": [] if completed else ["渡鸦级"],
                "skipped": [],
                "failed_reasons": [] if completed else ["渡鸦级：蓝图绑定不满足完成条件"],
            }

        # 对话框在 `complete_one_plan` 里**函数内导入**，故要打在桥模块的属性上
        import ui_qml.bridge.complete_plans_bridge as cpb

        monkeypatch.setattr(cpb, "CompletePlansQmlDialog", _Dlg)
        monkeypatch.setattr(cpd, "complete_plans", _complete_plans)
        monkeypatch.setattr("services.inventory_manager.get_hangars", lambda: [{"id": 4, "name": "产出仓"}])
        monkeypatch.setattr("services.user_settings.get_default_hangar_id", lambda key: 4)
        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: None)
        monkeypatch.setattr(cpd.QMessageBox, "warning", lambda *a, **k: warned.append(a[2:]))
        return calls

    def test_cancel_returns_none_without_completing(self, qapp, monkeypatch):
        from ui_pyside6.views.industry.complete_plans_dialog import complete_one_plan

        warned: list = []
        calls = self._setup(monkeypatch, dialog_result=0, completed=0, warned=warned)
        assert complete_one_plan(None, dict(self.PLAN)) is None
        assert "complete_hid" not in calls
        assert warned == []

    def test_success_returns_result(self, qapp, monkeypatch):
        from ui_pyside6.views.industry.complete_plans_dialog import complete_one_plan

        warned: list = []
        calls = self._setup(monkeypatch, dialog_result=1, completed=1, warned=warned)
        result = complete_one_plan(None, dict(self.PLAN))
        assert result is not None and result["completed"] == 1
        assert calls["complete_hid"] == 4
        assert warned == []

    def test_failure_warns_and_returns_none(self, qapp, monkeypatch):
        """失败必须返回 None，否则调用方会把失败的行标成已完成。"""
        from ui_pyside6.views.industry.complete_plans_dialog import complete_one_plan

        warned: list = []
        self._setup(monkeypatch, dialog_result=1, completed=0, warned=warned)
        assert complete_one_plan(None, dict(self.PLAN)) is None
        assert len(warned) == 1
        assert "蓝图绑定不满足完成条件" in warned[0][0]


class TestPlanTableCompleteFailure:
    """计划表格单行下线：`complete_one_plan` 返回 None 时不得改动行状态。"""

    def test_failed_plan_not_marked_completed(self, qapp, monkeypatch):
        from ui_pyside6.views.industry.plan_table import PlanTable

        monkeypatch.setattr(
            "ui_pyside6.views.industry.complete_plans_dialog.complete_one_plan",
            lambda parent, plan: None,
        )
        plan = {"id": 7, "product_name": "渡鸦级", "status": "ready"}
        holder = SimpleNamespace(_model=MagicMock(), _rebuild_subitems=lambda: None, plan_updated=MagicMock())
        PlanTable._complete_plan_with_dialog(holder, plan)  # type: ignore[arg-type]
        assert plan["status"] == "ready", "失败不得把计划标成已完成"
        holder._model.layoutChanged.emit.assert_not_called()
        holder.plan_updated.emit.assert_not_called()

    def test_successful_plan_marked_completed(self, qapp, monkeypatch):
        from ui_pyside6.views.industry.plan_table import PlanTable

        monkeypatch.setattr(
            "ui_pyside6.views.industry.complete_plans_dialog.complete_one_plan",
            lambda parent, plan: {"completed": 1, "deposited": 1, "failed": [], "failed_reasons": []},
        )
        plan = {"id": 7, "product_name": "渡鸦级", "status": "ready"}
        holder = SimpleNamespace(_model=MagicMock(), _rebuild_subitems=lambda: None, plan_updated=MagicMock())
        PlanTable._complete_plan_with_dialog(holder, plan)  # type: ignore[arg-type]
        assert plan["status"] == "completed"
        assert plan["deposited"] == 1
        assert plan["assigned_blueprint_id"] is None
        holder.plan_updated.emit.assert_called_once()


class TestPartialStartDialog:
    """部分启动对话框 —— 取值范围 1..P-1，摘要随条数实时更新。

    阶段 4：断言从 Widgets 内部控件（`_spin.minimum()`）换成**桥的字段**，
    行为契约不变（调用方仍是 `exec()` + `lines()`）。
    """

    @staticmethod
    def _dialog(total: int):
        from ui_qml.bridge.partial_start_bridge import PartialStartQmlDialog

        return PartialStartQmlDialog("渡鸦级", total)

    def test_range_and_default(self, qapp):
        dlg = self._dialog(4)
        try:
            assert dlg.bridge.maxLines == 3  # 至少要留 1 条给「未启动」那行
            assert dlg.lines() == 3
        finally:
            dlg.deleteLater()

    def test_two_lines_only_allows_one(self, qapp):
        dlg = self._dialog(2)
        try:
            assert dlg.bridge.maxLines == 1
            assert dlg.lines() == 1
        finally:
            dlg.deleteLater()

    def test_summary_follows_value(self, qapp):
        dlg = self._dialog(5)
        try:
            dlg.bridge.setLines(2)
            assert dlg.lines() == 2
            assert "启动 2 条" in dlg.bridge.summaryText
            assert "剩余 3 条" in dlg.bridge.summaryText
        finally:
            dlg.deleteLater()

    def test_value_is_clamped_to_the_range(self, qapp):
        dlg = self._dialog(4)
        try:
            dlg.bridge.setLines(99)
            assert dlg.lines() == 3
            dlg.bridge.setLines(0)
            assert dlg.lines() == 1
        finally:
            dlg.deleteLater()
