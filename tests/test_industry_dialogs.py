"""industry 弹窗族测试 — 拆解/并行/成本/下线 弹窗。

由 4 个文件合并：cost_breakdown_dialog + parent_decompose_multi + industry_parallel + industry_complete。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import services.plan_decompose as pd
from services import inventory_manager
from services.repositories.plan_repository import PlanRepository
from ui_pyside6.views.industry import parent_decompose_dialog as dlg_mod
from ui_pyside6.views.industry.complete_plans_dialog import CompletePlansDialog
from ui_pyside6.views.industry.cost_breakdown_dialog import CostBreakdownDialog
from ui_pyside6.views.industry.mass_parallel_dialog import (
    compute_parallel_by_duration,
    compute_parallel_by_lines,
)
from ui_pyside6.views.industry.parent_decompose_dialog import ParentDecomposeDialog
from ui_pyside6.views.industry.status_bar import StatusBar

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


def test_compute_subitem_costs_single_level(db_manager, qapp):
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

    dlg = CostBreakdownDialog({"product_type_id": 2001, "group_number": 7, "sub_level": 0}, char_config={})
    with patch("ui_pyside6.views.industry.cost_breakdown_dialog.get_container") as mock_cont:
        mock_cont.return_value.db = db_manager
        mock_cont.return_value.scoring_service.return_value.calculate_plan_metrics.side_effect = _metrics
        costs = dlg._compute_subitem_costs(7, 0)
    # 子项制造价 = 4800 + 100×2 = 5000
    assert costs == {2002: pytest.approx(5000, abs=0.01)}


def test_compute_subitem_costs_nested(db_manager, qapp):
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

    dlg = CostBreakdownDialog({"product_type_id": 2001, "group_number": 7, "sub_level": 0}, char_config={})
    with patch("ui_pyside6.views.industry.cost_breakdown_dialog.get_container") as mock_cont:
        mock_cont.return_value.db = db_manager
        mock_cont.return_value.scoring_service.return_value.calculate_plan_metrics.side_effect = _metrics
        costs = dlg._compute_subitem_costs(7, 0)
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
    def test_auto_runs_covers_demand(self, db_manager, monkeypatch, qapp):
        """只设并行数 → 每条流程自动生成覆盖母项需求。"""
        from ui_pyside6.views.industry.child_parallel_dialog import ChildParallelDialog

        _build_ref(db_manager)
        monkeypatch.setattr(
            "ui_pyside6.views.industry.child_parallel_dialog.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 1, "parallels": 1, "blueprint_type_id": 3002},
        ]
        dlg = ChildParallelDialog(plans)
        # 母项需求 1001 = 2；per_run=1 → 自动 runs = ceil(2/1) = 2 → 总产出 2 ≥ 2 → 通过
        assert dlg._ok_btn.isEnabled()
        assert dlg._current_runs(0) == 2
        # 并行提到 3 → runs = ceil(2/3) = 1 → 总产出 3 ≥ 2，仍通过
        dlg._rows[0][0].setValue(3)
        assert dlg._current_runs(0) == 1
        assert dlg._ok_btn.isEnabled()

    def test_sufficient_passes(self, db_manager, monkeypatch, qapp):
        from ui_pyside6.views.industry.child_parallel_dialog import ChildParallelDialog

        _build_ref(db_manager)
        monkeypatch.setattr(
            "ui_pyside6.views.industry.child_parallel_dialog.get_container",
            lambda: SimpleNamespace(db=db_manager),
        )
        plans = [
            {"id": 10, "product_type_id": 2001, "sub_level": 0, "runs": 2, "parallels": 1, "me_level": 0},
            {"id": 11, "product_type_id": 1001, "sub_level": 1, "runs": 2, "parallels": 1, "blueprint_type_id": 3002},
        ]
        dlg = ChildParallelDialog(plans)
        assert dlg._ok_btn.isEnabled()  # 自动 runs 覆盖需求
        assert dlg._current_runs(0) == 2


# ════════════════════════════════════════════════════════════════
#  StatusBar / CompletePlansDialog / 启动向导（原 test_industry_complete.py）
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def production_wizard_mock_db():
    """给 ProductionWizard 注入 mock 容器/DB，避免访问真实库。

    ProductionWizard.__init__ 经 `_load_blueprint_names`（查 ref 库 item）与
    `char_capacity.active_lines_per_character`（查 user 库 production_plans）
    访问真实库；worktree / CI 无初始化 schema，必须 patch 这两条 get_container 路径。
    """
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_conn
    mock_cm.__exit__.return_value = False
    mock_mgr = MagicMock()
    mock_mgr.connect.return_value = mock_cm
    mock_cont = MagicMock()
    mock_cont.db = mock_mgr
    with (
        patch("ui_pyside6.dialogs.production_wizard.get_container", return_value=mock_cont),
        patch("services.char_capacity.get_container", return_value=mock_cont),
    ):
        yield


class TestStatusBarCompleteAll:
    """底部状态栏「全部下线」按钮显示/隐藏与信号"""

    def test_hidden_without_ready(self, qapp):
        bar = StatusBar()
        bar.update_stats([{"status": "pending"}, {"status": "running"}])
        assert bar._btn_complete_all.isHidden()

    def test_shown_with_ready_count(self, qapp):
        bar = StatusBar()
        bar.update_stats(
            [
                {"status": "pending"},
                {"status": "ready"},
                {"status": "ready"},
                {"status": "running"},
            ]
        )
        assert not bar._btn_complete_all.isHidden()
        assert bar._btn_complete_all.text() == "全部下线 (2)"

    def test_emit_complete_all_requested(self, qapp):
        bar = StatusBar()
        bar.update_stats([{"status": "ready"}])
        got = []
        bar.complete_all_requested.connect(lambda: got.append(True))
        bar._btn_complete_all.click()
        assert got == [True]


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
        assert dlg._table.rowCount() == 1
        assert dlg._table.item(0, 0).text() == "渡鸦级"
        assert dlg._table.item(0, 1).text() == "3X2"
        assert dlg._table.item(0, 2).text() == "6"  # 产出量

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


class TestReadyButtonDelegate:
    """状态列「待下线」按钮渲染 delegate"""

    def _ready_model(self):
        from ui_pyside6.models.industry_models import PlanTableModel

        return PlanTableModel([{"product_name": "渡鸦级", "status": "ready", "product_type_id": 2001}])

    def test_ready_cell_button_size_hint(self, qapp):
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.views.industry.plan_table_constants import COL_STATUS
        from ui_pyside6.views.industry.plan_table_delegate import ReadyButtonDelegate

        delegate = ReadyButtonDelegate()
        model = self._ready_model()  # 保持模型存活，避免 QModelIndex 悬空
        index = model.index(0, COL_STATUS)
        hint = delegate.sizeHint(QStyleOptionViewItem(), index)
        assert hint.width() >= 60
        assert hint.height() >= 20

    def test_non_ready_default_size_hint(self, qapp):
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.models.industry_models import PlanTableModel
        from ui_pyside6.views.industry.plan_table_constants import COL_STATUS
        from ui_pyside6.views.industry.plan_table_delegate import ReadyButtonDelegate

        delegate = ReadyButtonDelegate()
        model = PlanTableModel([{"product_name": "渡鸦级", "status": "in_progress", "product_type_id": 2001}])
        index = model.index(0, COL_STATUS)
        hint = delegate.sizeHint(QStyleOptionViewItem(), index)
        assert hint.width() < 60  # 非 ready 不渲染按钮，走默认

    def test_paint_ready_does_not_crash(self, qapp):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.views.industry.plan_table_constants import COL_STATUS
        from ui_pyside6.views.industry.plan_table_delegate import ReadyButtonDelegate

        delegate = ReadyButtonDelegate()
        model = self._ready_model()
        index = model.index(0, COL_STATUS)
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, 80, 26)
        pix = QPixmap(100, 30)
        pix.fill()
        painter = QPainter(pix)
        delegate.paint(painter, option, index)
        painter.end()
        assert not pix.isNull()


class TestLaunchWizard:
    """产线启动小助手：一级菜单按钮 + 两列 + 复制蓝图名 + 启动按钮显隐"""

    def test_launch_wizard_button_emits(self, qapp):
        from ui_pyside6.views.industry.action_buttons import ActionButtons

        ab = ActionButtons()
        got = []
        ab.launch_wizard_requested.connect(lambda: got.append(True))
        ab._btn_launch_wizard.click()
        assert got == [True]

    def test_orders_by_child_level_desc(self, qapp, production_wizard_mock_db):
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [
            {"product_name": "子项2", "child_level": 2, "status": "pending"},
            {"product_name": "母项", "child_level": 0, "status": "pending"},
            {"product_name": "子项1", "child_level": 1, "status": "pending"},
        ]
        wizard = ProductionWizard(plans, mat_hangar_id=None)
        names = [p["product_name"] for p in wizard._plans]
        assert names == ["子项2", "子项1", "母项"]  # 子级高的先做

    def test_copy_blueprint_name(self, qapp, production_wizard_mock_db):
        from PySide6.QtWidgets import QApplication

        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "blueprint_type_id": 32877,
                "status": "pending",
                "runs": 1,
                "parallels": 1,
            }
        ]
        wizard = ProductionWizard(plans, mat_hangar_id=None)
        wizard._copy_blueprint("渡鸦级蓝图")
        assert QApplication.clipboard().text() == "渡鸦级蓝图"

    def test_pending_shows_start_button(self, qapp, production_wizard_mock_db):
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "blueprint_type_id": 32877,
                "status": "pending",
                "runs": 1,
                "parallels": 1,
            }
        ]
        wizard = ProductionWizard(plans, mat_hangar_id=None)  # 无材料机库 → 视为备料充足
        assert wizard._table.rowCount() == 1
        assert not wizard._start_btn.isHidden()  # 备料足 → 显示启动按钮

    def test_flat_plans_unchanged(self, qapp, production_wizard_mock_db):
        from ui_pyside6.dialogs.production_wizard import ProductionWizard

        plans = [{"product_name": "A", "child_level": 0, "status": "pending"}]
        wizard = ProductionWizard(plans, mat_hangar_id=None)
        assert wizard._table.rowCount() == 1
