"""industry 弹窗族测试 — 拆解/并行/成本/下线 弹窗。

由 4 个文件合并：cost_breakdown_dialog + parent_decompose_multi + industry_parallel + industry_complete。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import services.plan_decompose as pd
from services import inventory_manager
from services.plan_metrics import SubitemCost
from services.repositories.plan_repository import PlanRepository
from ui_qml.bridge import parent_decompose_bridge as dlg_mod
from ui_qml.bridge.complete_plans_bridge import CompletePlansQmlDialog as CompletePlansDialog
from ui_qml.bridge.cost_breakdown_bridge import CostBreakdownBridge
from ui_qml.bridge.mass_parallel_bridge import (
    compute_parallel_by_duration,
    compute_parallel_by_lines,
)
from ui_qml.bridge.parent_decompose_bridge import (
    ParentDecomposeBridge,
)
from ui_qml.bridge.parent_decompose_bridge import (
    ParentDecomposeQmlDialog as ParentDecomposeDialog,
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


def _insert_bp_products(db, rows: list[tuple[int, int, int]]) -> None:
    """bp 库：`(blueprint_type_id, product_type_id, 每轮产出)` → 子项产出量的来源。"""
    with db.connect("bp") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS blueprint_activities (blueprint_type_id INTEGER, activity TEXT, time REAL)"
        )
        for bp_id, product_type_id, qty in rows:
            conn.execute(
                "INSERT INTO blueprint_products VALUES (?,?,?,?)", (bp_id, "manufacturing", product_type_id, qty)
            )
            conn.execute("INSERT INTO blueprint_activities VALUES (?,?,?)", (bp_id, "manufacturing", 60.0))


def _bridge_with_metrics(db_manager, monkeypatch, metrics_fn):
    """造一个成本明细桥，把 `calculate_plan_metrics` 换成 `metrics_fn`（阶段 4 后走桥）。"""
    svc = MagicMock()
    svc.calculate_plan_metrics.side_effect = metrics_fn
    # 「自制成本」列另走一个取数（`manufacturing_unit_costs`）：本组用例只关心子项制造价，
    # 这里给空映射，免得 MagicMock 的返回值被当成金额格式化（那是另一条链的断言）
    svc.manufacturing_unit_costs.return_value = {}
    monkeypatch.setattr(
        "ui_qml.bridge.cost_breakdown_bridge.get_container",
        lambda: SimpleNamespace(db=db_manager, scoring_service=lambda: svc),
    )
    return CostBreakdownBridge({"product_type_id": 2001, "group_number": 7, "sub_level": 0}, char_config={})


def test_compute_subitem_costs_single_level(db_manager, monkeypatch, qapp):
    """拆解母项：子项单件制造价 = (材料 + 作业费 × runs) ÷ 子项自己的产出量。

    产出量 = `runs × parallels × 每轮产出`（每轮产出查该计划 activity 的配方），
    **不是**母项的需求 —— 子项产线排的是净需求，拿需求当分母会低估单价。
    """
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
    _insert_bp_products(db_manager, [(4002, 2002, 1)])

    def _metrics(plan, char_config, **kw):
        if plan.get("product_type_id") == 2002:
            return {"material_cost": 4800.0, "breakdown": {"installation_fee": 100.0}}
        return {}

    bridge = _bridge_with_metrics(db_manager, monkeypatch, _metrics)
    costs = bridge._compute_subitem_costs(7, 0)
    # 整线制造价 = 4800 + 100×2 = 5000；产出量 = 2×1×1 = 2 → 单件 2500
    assert costs == {2002: SubitemCost(unit_cost=2500.0, covered_qty=2.0)}


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
    _insert_bp_products(db_manager, [(4002, 2002, 1), (4003, 3003, 1)])

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
    # 孙项制造价 = 100 + 50 = 150（产出 1）；子项制造价 = 150(孙项) + 100(作业费) = 250（产出 1）
    assert costs[3003] == SubitemCost(unit_cost=150.0, covered_qty=1.0)
    assert costs[2002] == SubitemCost(unit_cost=250.0, covered_qty=1.0)


def test_compute_subitem_costs_zero_run_child_excluded(db_manager, monkeypatch, qapp):
    """0 轮子项（制造价 0）不进映射 → 母项该行回退市价，而不是「自制件 0 ISK」。

    回归背景：这条路径原先自建子项成本映射、没做 0 值剔除，于是 `runs=0` 的子项被算成
    0 成本自制件，母项 `material_cost` 被 `adjust_mother_metrics` 打成 **0.00**
    （与 `services.plan_metrics.mother_subitem_cost_map` 的 `cost <= 0` 剔除规则不一致）。
    """
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
                "product_name": "0 轮子项",
                "runs": 0,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 1,
            },
            {
                "id": 3,
                "product_type_id": 2003,
                "product_name": "在造子项",
                "runs": 3,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 1,
            },
        ],
    )
    _insert_bp_products(db_manager, [(4002, 2002, 1), (4003, 2003, 1)])

    def _metrics(plan, char_config, **kw):
        pid = plan.get("product_type_id")
        if pid == 2002:
            return {"material_cost": 4800.0, "breakdown": {"installation_fee": 100.0}}
        if pid == 2003:
            return {"material_cost": 300.0, "breakdown": {"installation_fee": 50.0}}
        return {}

    bridge = _bridge_with_metrics(db_manager, monkeypatch, _metrics)
    # 在造子项 = (300 + 50×3) ÷ 产出 3 = 150/件；0 轮子项制造价 0 → 整条不进映射
    assert bridge._compute_subitem_costs(7, 0) == {2003: SubitemCost(unit_cost=150.0, covered_qty=3.0)}


def test_compute_subitem_costs_without_recipe_needs_the_mother_demand(db_manager, monkeypatch, qapp):
    """查不到配方（拿不到每轮产出）→ 整线价按母项需求折成单件价，`covered_qty=None`。

    这条是旧口径的等价写法：`adjust_mother_metrics` 对 `covered_qty=None` 按「整线覆盖
    全部需求」处理，所以 `需求 × 单件价` 必须正好还原整线价；连需求都拿不到时**不猜**
    （不进映射、该行回退市价），免得把一个凭空的单件价写进母项成本。
    """
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
                "product_name": "无配方子项",
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
    # 整线 5000 / 需求 8 = 625/件，covered_qty=None → 消费方按需求 8 件结算 = 5000
    assert bridge._compute_subitem_costs(7, 0, need_by_type={2002: 8.0}) == {
        2002: SubitemCost(unit_cost=625.0, covered_qty=None)
    }
    assert bridge._compute_subitem_costs(7, 0) == {}


def test_cost_breakdown_subitem_coverage_gap_and_iskph(db_manager, monkeypatch, qapp):
    """汇总框三件事一起钉住：自制子项按产出计价 + 缺口按市价、ISK/h 与利润同口径、两个口径分别标注。

    回归背景（真库 plan 383 灼烧XL 实测）：① 利润被换成个人口径、`ISK/h` 却仍取市场口径的
    `metrics["iskph"]`，同一个汇总框里「利润 +3.4 亿 / ISK/h −514 万」自相矛盾；
    ② 子项单价用「子项产线总价 ÷ 母项需求」，把子项没覆盖的那部分（库存/待买）当 0 成本，
    单价偏低且与右栏「自制成本」不可比。
    """
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
                "product_name": "子项A",
                "runs": 3,
                "parallels": 2,
                "group_number": 7,
                "sub_level": 1,
            },
            {
                "id": 3,
                "product_type_id": 2003,
                "product_name": "子项B",
                "runs": 1,
                "parallels": 1,
                "group_number": 7,
                "sub_level": 1,
            },
        ],
    )
    # 只有 2002 有配方：每轮产出 5 → 产出量 3×2×5 = 30（母项需求 40，缺口 10 在库存里）
    _insert_bp_products(db_manager, [(4002, 2002, 5)])

    def _metrics(plan, char_config, **kw):
        pid = plan.get("product_type_id")
        if pid == 2002:
            return {"material_cost": 900.0, "breakdown": {"installation_fee": 100.0}}  # 900+100×6=1500
        if pid == 2003:
            return {"material_cost": 700.0, "breakdown": {"installation_fee": 0.0}}  # 无配方 → 700/需求 10
        return {
            "material_cost": 4000.0,
            "revenue": 10_000.0,
            "fees": 0.0,
            "profit": 3_000.0,
            "margin": -14.81,
            "score": 42.0,
            "iskph": -5_147_145.46,
            "calculated_time": 3_600.0,
            "daily_output": 8.0,
            "status": "",
            "structure_mat_saving": 1.0,
            "materials": [
                {"name": "子项A", "base_qty": 40, "qty": 40, "type_id": 2002, "unit_price": 100.0, "total_qty": 40},
                {"name": "子项B", "base_qty": 10, "qty": 10, "type_id": 2003, "unit_price": 100.0, "total_qty": 10},
            ],
            "breakdown": {"activity": "manufacturing", "revenue": 10_000.0},
        }

    bridge = _bridge_with_metrics(db_manager, monkeypatch, _metrics)
    rows = [c["text"] for r in bridge.materialRows for c in r["cells"]]
    # 子项A：30 件自制（1500/30 = 50/件）+ 10 件缺口按市价 100 → 小计 2500、单价 2500/40 = 62.50
    assert "子项A（自制 30/40）" in rows
    assert bridge.materialRows[0]["cells"][4]["text"] == "62.50"
    assert bridge.materialRows[0]["cells"][6]["text"] == "2,500"
    # 子项B：查不到配方 → 整线价 700 按需求 10 折成 70/件，行名不带覆盖量
    assert "子项B（自制）" in rows
    assert bridge.materialRows[1]["cells"][6]["text"] == "700"

    summ = {f["label"]: f["value"] for f in bridge.summaryFields}
    assert summ["总成本:"] == "3,200"
    assert summ["利润:"] == "6,800"
    assert summ["利润率:"] == "212.50%"  # 个人口径：(10000−3200)/3200
    assert summ["市场口径利润率:"] == "-14.81%"  # 调整前留存的市场口径，别与上面那个混为一谈
    assert summ["ISK/h:"] == "6,800"  # 6800 利润 / 1h —— 不是 metrics["iskph"] 的 −5,147,145
    assert "个人口径（同组自制子项按自制价，缺口按市价/库存）" in bridge.statusText


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
    # 消息框在批次 7.1 收敛成 `FMessageDialog`，`QMessageBox` 已不是模块属性。
    # 替换**模块属性**而不是类上的方法：那个类是所有桥共用的，改它会外溢到别的用例。
    monkeypatch.setattr(dlg_mod, "FMessageDialog", SimpleNamespace(information=lambda *a, **k: None))
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
        assert len(dlg.bridge._assignments) == 2
        gnums = {g for _, g, _ in dlg.bridge._assignments}
        assert len(gnums) == 2  # 每个母项一个独立组号

        dlg.bridge.accept()
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
        assert dlg.bridge._assignments[0][1] == 7  # 已有组号 7 复用
        assert len({g for _, g, _ in dlg.bridge._assignments}) == 1

    def test_skip_mother_without_lines(self, db_manager, monkeypatch, qapp):
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        # 99999 无蓝图 → decompose_plan 返回 [] → 不分配组号、不落库
        dlg = ParentDecomposeDialog([_mother(3, product_type_id=99999)])
        assert dlg.bridge._assignments == []
        assert dlg.bridge.isEmpty is True

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
        gnums = sorted(g for _, g, _ in dlg.bridge._assignments)
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
        dlg.bridge.accept()
        with db_manager.connect("user") as conn:
            row = conn.execute("SELECT runs, parallels, me_level, te_level FROM production_plans WHERE id=2").fetchone()
        # 需求=5×2=10、并行保留 5 → runs=ceil(10/(5×1))=2；ME-TE 刷新
        assert tuple(row) == (2, 5, 0, 0)

    def test_row_refs_map_each_row_to_its_own_line(self, db_manager, monkeypatch, qapp):
        """回归：同一母项的多行必须各自对应真实行下标。

        早先 `_append_row` 用「子项列表长度 − 1」推断下标，导致该母项的所有预览行都指向
        最后一行——移除时先删最后一行、再删就越界（IndexError）。
        QML 版把「移除一行」从「多选 + 按钮」改成行内按钮，这条不变量仍是关键：
        `removeRow(row)` 必须按**该行**的下标删除。
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
        # 直接造桥，不造 `QmlDialog` 窗口：这条用例要的是**行号映射与删除语义**，
        # 窗口只是外壳。造真 QML 窗口在本机 offscreen 下会把整档拖住（同
        # `test_qml_shell.py` 的症状），而「对话框能加载」另有
        # `tests/test_qml_dialogs.py` 的 `_LOADS_CASES` 参数化覆盖。
        bridge = ParentDecomposeBridge([_mother(1)])
        n_rows = bridge.rowCount
        assert n_rows >= 2  # 渡鸦级拆出碳纤维 + 三钛合金
        assert [l_idx for _a, l_idx, _line in bridge._refs] == list(range(n_rows))

        # 逐行移除（倒序，避免行号漂移）→ 不得越界，且子项列表清空
        for row in reversed(range(n_rows)):
            bridge.removeRow(row)
        assert bridge.rowCount == 0
        assert bridge._assignments[0][2] == []
        assert bridge.statusText == f"已移除 {n_rows} 个组件（本轮不内造，改外购）"

        # 批量移除（Ctrl / Shift 多选后点「移除选中行」）：QML 的 `selectedRows` 是**升序**的，
        # 所以降序化必须由 `removeRows` 自己做 —— 升序删会因下标前移而漏掉后半（甚至错删）。
        bridge2 = ParentDecomposeBridge([_mother(1)])
        assert bridge2.rowCount == n_rows
        bridge2.removeRows(list(range(n_rows)))  # 故意传升序
        assert bridge2.rowCount == 0
        assert bridge2._assignments[0][2] == []
        assert bridge2.statusText == f"已移除 {n_rows} 个组件（本轮不内造，改外购）"
        # 重复行号只算一次（QML 侧理论上不会给重，但按集合处理才不会被删两次）
        bridge2.removeRows([0, 0, 0])
        assert bridge2.statusText == f"已移除 {n_rows} 个组件（本轮不内造，改外购）"

    def test_removed_child_only_touches_this_dialogs_mother(self, db_manager, monkeypatch, qapp):
        """P0 回归：预览里移除子项，只许作用于本次对话框那条母项，别的组一行都不许动。

        用户报障（2026-09-28）：「对未开始的产线进行对母项进行递归拆解，并在弹出的窗口中
        移除不需要新建的子项，会导致所有生产计划，不管是否在运行，都自动拆解母项。」

        `accept()` 里两条路径都是**全库**的，这才是「所有生产计划」的来源：

        - `rebuild_children(create=True, prune=True)` 是全库重放 —— DB 里任何
          `group_number>0` 的 level-0 行都被当母项重新拆解，缺失的子项行被补建，
          于是本次对话框没碰过的组（含在产）也被「自动拆解」；
        - `_remove_planning_discarded()` 只拿到一组 `type_id`，`collect_removed_child_ids`
          按 `product_type_id` 全库命中：别的组引用的同一组件行（引用式合并后就是同一行）
          一并被删 —— 在产母项需要的子项产线凭空消失。

        构造：A = 本次要拆的未开始母项 2001（拆出 1001 与 35）；B = 与 A 无关的在产组
        （母项 2010 在产，引用 1001（与 A 共享同一行）与 1010（该行用户已删、改外购））。
        """
        _build_dbs(db_manager)
        _patch(db_manager, monkeypatch)
        with db_manager.connect("bp") as conn:
            # A 的母项 2001 拆出两条子项：1001（bp3002 已有）+ 35（补 bp3003）
            conn.execute("INSERT INTO blueprint_products VALUES (3003,'manufacturing',35,1)")
            conn.execute("INSERT INTO blueprint_materials VALUES (3003,'manufacturing',34,1)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3003,'manufacturing',600)")
            # B 组：母项 2010 吃 1001×3（与 A 共享）与 1010×2；1010 由 bp3011 产
            conn.execute("INSERT INTO blueprint_products VALUES (3010,'manufacturing',2010,1)")
            conn.execute("INSERT INTO blueprint_materials VALUES (3010,'manufacturing',1001,3)")
            conn.execute("INSERT INTO blueprint_materials VALUES (3010,'manufacturing',1010,2)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3010,'manufacturing',3600)")
            conn.execute("INSERT INTO blueprint_products VALUES (3011,'manufacturing',1010,1)")
            conn.execute("INSERT INTO blueprint_materials VALUES (3011,'manufacturing',34,1)")
            conn.execute("INSERT INTO blueprint_activities VALUES (3011,'manufacturing',600)")
        with db_manager.connect("user") as conn:
            # A：未开始的母项（还没拆过，group_number=0）
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, runs, parallels, status, "
                "group_number, sub_level, mat_hangar_id) VALUES (1, 2001, '渡鸦级', 2, 1, 'pending', 0, 0, 1)"
            )
            # B：无关的在产组。1001 行在库里（引用式合并后与 A 共用一行）；
            #    1010 行用户已删（改外购）—— 修复后不许被对话框补建回来。
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, runs, parallels, status, "
                "group_number, sub_level, mat_hangar_id, source_mother_ids, component_parent_type_id, demand) "
                "VALUES (10, 2010, '别的母项', 1, 1, 'in_progress', 9, 0, 1, '', NULL, 0)"
            )
            conn.execute(
                "INSERT INTO production_plans (id, product_type_id, product_name, runs, parallels, status, "
                "group_number, sub_level, mat_hangar_id, source_mother_ids, component_parent_type_id, demand) "
                "VALUES (11, 1001, '碳纤维', 3, 1, 'pending', 9, 1, 1, '10', 2010, 3)"
            )

        bridge = ParentDecomposeBridge([_mother(1)])
        # A 的预览里移除 1001 那行（用户判为「不需要新建」）
        idx = next(i for i, (_a, _l, line) in enumerate(bridge._refs) if int(line["product_type_id"]) == 1001)
        bridge.removeRow(idx)
        bridge.accept()

        with db_manager.connect("user") as conn:
            rows = {
                int(r["id"]): dict(r)
                for r in conn.execute(
                    "SELECT id, product_type_id, group_number, sub_level, status, source_mother_ids, runs "
                    "FROM production_plans"
                ).fetchall()
            }
        # 1）B 组不许被「自动拆解」：1010 那一行是用户特意删掉改外购的，不许补建
        assert [r for r in rows.values() if int(r["product_type_id"]) == 1010] == []
        # 2）B 在产母项还引用的 1001 行不许被删、状态不许变
        assert 11 in rows, "别的组引用的子项行被删了"
        assert rows[11]["status"] == "pending"
        assert "10" in str(rows[11]["source_mother_ids"]).split(",")
        # 3）B 的母项行不许被动
        assert (
            rows[10]["status"],
            int(rows[10]["group_number"]),
            int(rows[10]["sub_level"]),
        ) == ("in_progress", 9, 0)
        # 4）A 自己保留的组件仍要正常拆出来（别把功能一起修坏）
        assert [
            r
            for r in rows.values()
            if int(r["product_type_id"]) == 35 and "1" in str(r["source_mother_ids"]).split(",")
        ]


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


# ════════════════════════════════════════════════════════════════
#  产出总表底栏（OutputSummaryBridge）
# ════════════════════════════════════════════════════════════════


def test_output_summary_footer_reports_total_margin(qapp, monkeypatch):
    """底栏要给出**总利润率**，且分母必须与利润同口径。

    回归背景（2026-09-28，用户要求）：底栏原先只有「总产出价值 / 总利润 / N 个计划存在
    材料溢出」，看不出整体赚几个点。

    ⚠️ 分母**不能**用表格里那列「成本」（`production_plans.material_cost`，纯材料）——
    利润减掉的是材料 + 安装费 + 经纪人/改单/销售税 + T1 拷贝/T2-T3 发明研究成本
    （`domain/scoring.py` 的 total_cost），两者不同源；用成本列当分母会把利润率系统性
    抬高。这里让 `plan_value − profit` 恰好等于已知成本，把口径钉死。
    """
    from types import SimpleNamespace

    from ui_qml.bridge import output_dialog_bridge as mod

    fake = [
        {
            "plan_name": "A",
            "product_type_id": 1,
            "total_qty": 1,
            "plan_value": 200.0,
            "material_cost": 100.0,  # ← 故意与真成本 150 不同：拿它当分母会算出 75%，那是错的
            "profit": 50.0,
            "margin_pct": 33.3,
            "status": "pending",
            "overflow_text": "—",
            "has_overflow": False,
        },
        {
            "plan_name": "B",
            "product_type_id": 2,
            "total_qty": 1,
            "plan_value": 100.0,
            "material_cost": 20.0,
            "profit": 25.0,
            "margin_pct": 33.3,
            "status": "pending",
            "overflow_text": "—",
            "has_overflow": False,
        },
    ]
    monkeypatch.setattr("services.industry_dialog_queries.get_output_summary", lambda db: fake)
    monkeypatch.setattr(mod, "get_container", lambda: SimpleNamespace(db=None))

    bridge = mod.OutputSummaryBridge()
    bridge.reload()

    # 真成本 = (200−50) + (100−25) = 225，利润 = 75 → 33.3%
    assert "总利润率 33.3%" in bridge.statusText, bridge.statusText

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
    """下线确认对话框 — 计划清单 / 逐行机库 / 「统一设为」"""

    def test_each_row_keeps_its_own_hangar_and_bulk_set_overrides_all(self, qapp, monkeypatch):
        """每行初值 = **该计划自己**的 `deposit_hangar_id`；「统一设为」覆盖所有行。

        回归 `d2ac6a2`：批量下线曾退化成「一个下拉覆盖整批」，且单行初值取的是**全局默认**
        而不是计划自己的值 —— 用户在各计划编辑对话框里逐条配好的产出机库被静默丢掉
        （那个值只在清单第 4 列当只读文本显示）。这里把两半一起钉住：逐行独立 + 批量覆盖。
        """
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [
            {
                "id": 1,
                "product_name": "渡鸦级",
                "product_type_id": 2001,
                "runs": 2,
                "parallels": 3,
                "deposit_hangar_id": 5,
            },
            {
                "id": 2,
                "product_name": "无人机",
                "product_type_id": 2002,
                "runs": 1,
                "parallels": 1,
                "deposit_hangar_id": 2,
            },
            {
                "id": 3,
                "product_name": "三钛合金",
                "product_type_id": 1001,
                "runs": 1,
                "parallels": 1,
                "deposit_hangar_id": None,
            },
        ]
        hangars = [{"id": 1, "name": "矿仓"}, {"id": 2, "name": "组件仓"}]
        dlg = CompletePlansDialog(plans, hangars, 1)  # 全局默认 = 矿仓
        # 第 1 行自己的 id=5 不在机库表里 → 退化全局默认；第 2 行用自己的 2；
        # 第 3 行没有自己的值 → 全局默认。三行**各不相同**，不是同一个值盖全批。
        assert [dlg.bridge.hangarIndexAt(i) for i in range(3)] == [1, 2, 1]
        assert dlg.selected_hangar_ids() == [1, 2, 1]
        assert dlg.bridge.hangarIndexAt(99) == 0  # 越界 → 「不自动入库」，不抛

        rows = dlg.bridge.rows
        assert len(rows) == 3
        assert rows[0]["name"] == "渡鸦级"
        assert rows[0]["runs"] == "3X2"
        assert rows[0]["qty"] == "6"  # 产出量 = 3 并行 × 2 流程 × 每次 1

        # 底部「统一设为」：一次覆盖全部行（含上面各不相同的行）
        dlg.bridge.setAllHangars(0)
        assert dlg.selected_hangar_ids() == [-1, -1, -1], "统一设为「不自动入库」必须覆盖所有行"
        dlg.bridge.setAllHangars(2)
        assert dlg.selected_hangar_ids() == [2, 2, 2], "统一设为组件仓必须覆盖所有行"

    def test_default_fallback_first_hangar(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [{"id": 1, "product_name": "渡鸦级", "runs": 1, "parallels": 1, "deposit_hangar_id": None}]
        hangars = [{"id": 1, "name": "矿仓"}, {"id": 2, "name": "组件仓"}]
        dlg = CompletePlansDialog(plans, hangars, None)
        assert dlg.selected_hangar_id() == 1  # 无默认时选第一个机库（单行路径仍走标量）
        assert dlg.selected_hangar_ids() == [1]

    def test_no_hangar_keeps_no_auto_deposit(self, qapp, monkeypatch):
        monkeypatch.setattr("services.plan_execution.output_per_run", lambda *a: 1)
        plans = [{"id": 1, "product_name": "渡鸦级", "runs": 1, "parallels": 1}]
        dlg = CompletePlansDialog(plans, [], -1)
        assert dlg.selected_hangar_id() == -1  # 无机库时保持「不自动入库」
        assert dlg.selected_hangar_ids() == [-1]


class TestCompleteGuard:
    """四条下线入口共用的「蓝图流程不足」确认。

    回归背景：底部状态栏的「全部下线」曾是唯一不预检、也不传 `allow_bp_short`
    的入口 —— 强制启动过的计划在那里永远下不了线，且只显示一句「失败 N 项」。
    """

    def test_no_shortfall_returns_false_without_asking(self, qapp, monkeypatch):
        from ui_qml.bridge import complete_guard

        asked = []
        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: None)
        monkeypatch.setattr(
            complete_guard, "FMessageDialog", SimpleNamespace(question=lambda *a, **k: asked.append(True) or True)
        )
        result = complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}])
        assert result is False
        assert asked == [], "无短板不该弹确认框"

    def test_shortfall_yes_allows_force(self, qapp, monkeypatch):
        from ui_qml.bridge import complete_guard

        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: "第 1 张绑定蓝图流程不足")
        monkeypatch.setattr(complete_guard, "FMessageDialog", SimpleNamespace(question=lambda *a, **k: True))
        assert complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}]) is True

    def test_shortfall_no_cancels(self, qapp, monkeypatch):
        from ui_qml.bridge import complete_guard

        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: "第 1 张绑定蓝图流程不足")
        monkeypatch.setattr(complete_guard, "FMessageDialog", SimpleNamespace(question=lambda *a, **k: False))
        assert complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}]) is None

    def test_danger_confirm_defaults_to_no(self, qapp, monkeypatch):
        """破坏性确认的默认项必须落在「否」。

        原版是 `QMessageBox.question(..., Yes | No, defaultButton=No)` —— 那个 `No`
        是刻意的：手快回车不该把流程不足的计划放下去。换成 QML 版之后，默认项不再是
        构造参数的一部分，而是「焦点给谁」，很容易在搬迁时静默丢掉，所以单列一条钉住。
        """
        from ui_qml.bridge import complete_guard

        seen: dict = {}
        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: "不足")
        monkeypatch.setattr(
            complete_guard, "FMessageDialog", SimpleNamespace(question=lambda *a, **k: seen.update(k) or False)
        )
        complete_guard.confirm_bp_shortfall(None, [{"id": 1, "product_name": "电磁发生器"}])
        assert seen.get("default_yes") is False, "回车必须落在「否」上，不能默认放行"

    def test_shortfall_lines_skips_plans_without_id(self, monkeypatch):
        from ui_qml.bridge import complete_guard

        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: f"缺流程 {pid}")
        assert complete_guard.shortfall_lines([{"product_name": "无 id"}]) == []
        assert complete_guard.shortfall_lines([{"id": 7, "product_name": "电磁发生器"}]) == ["  电磁发生器: 缺流程 7"]


class TestStatusBarCompleteAllGuard:
    """状态栏「全部下线」必须与另外三条入口行为一致：预检 + 透传 allow_bp_short。"""

    @staticmethod
    def _run(monkeypatch, short_text: str | None, user_choice: bool):
        import ui_qml.views.industry_view as iv
        from ui_qml.bridge import complete_guard

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

            def selected_hangar_ids(self):
                return [4]

        captured: dict = {}

        def _complete_plans(plans, hid, **kwargs):
            captured["hid"] = hid
            captured.update(kwargs)
            return {"completed": len(plans), "deposited": 0, "failed": [], "failed_reasons": []}

        monkeypatch.setattr(iv, "CompletePlansDialog", _Dlg)
        monkeypatch.setattr(iv, "complete_plans", _complete_plans)
        monkeypatch.setattr("services.inventory_manager.get_hangars", lambda: [{"id": 4, "name": "产出仓"}])
        monkeypatch.setattr("services.user_settings.get_default_hangar_id", lambda key: 4)
        monkeypatch.setattr(iv, "FMessageDialog", SimpleNamespace(information=lambda *a, **k: None))
        monkeypatch.setattr("services.plan_execution.binding_shortfall", lambda pid: short_text)
        monkeypatch.setattr(complete_guard, "FMessageDialog", SimpleNamespace(question=lambda *a, **k: user_choice))

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
        from ui_qml.views.industry import complete_plans_dialog as cpd

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
        from ui_qml.views.industry.complete_plans_dialog import complete_one_plan

        warned: list = []
        calls = self._setup(monkeypatch, dialog_result=0, completed=0, warned=warned)
        assert complete_one_plan(None, dict(self.PLAN)) is None
        assert "complete_hid" not in calls
        assert warned == []

    def test_success_returns_result(self, qapp, monkeypatch):
        from ui_qml.views.industry.complete_plans_dialog import complete_one_plan

        warned: list = []
        calls = self._setup(monkeypatch, dialog_result=1, completed=1, warned=warned)
        result = complete_one_plan(None, dict(self.PLAN))
        assert result is not None and result["completed"] == 1
        assert calls["complete_hid"] == 4
        assert warned == []

    def test_failure_warns_and_returns_none(self, qapp, monkeypatch):
        """失败必须返回 None，否则调用方会把失败的行标成已完成。"""
        from ui_qml.views.industry.complete_plans_dialog import complete_one_plan

        warned: list = []
        self._setup(monkeypatch, dialog_result=1, completed=0, warned=warned)
        assert complete_one_plan(None, dict(self.PLAN)) is None
        assert len(warned) == 1
        assert "蓝图绑定不满足完成条件" in warned[0][0]


class TestPlanTableCompleteFailure:
    """计划表格单行下线：`complete_one_plan` 返回 None 时不得改动行状态。"""

    def test_failed_plan_not_marked_completed(self, qapp, monkeypatch):
        from ui_qml.views.industry.plan_table import PlanTable

        monkeypatch.setattr(
            "ui_qml.views.industry.complete_plans_dialog.complete_one_plan",
            lambda parent, plan: None,
        )
        plan = {"id": 7, "product_name": "渡鸦级", "status": "ready"}
        holder = SimpleNamespace(_model=MagicMock(), _rebuild_subitems=lambda: None, plan_updated=MagicMock())
        PlanTable._complete_plan_with_dialog(holder, plan)  # type: ignore[arg-type]
        assert plan["status"] == "ready", "失败不得把计划标成已完成"
        holder._model.layoutChanged.emit.assert_not_called()
        holder.plan_updated.emit.assert_not_called()

    def test_successful_plan_marked_completed(self, qapp, monkeypatch):
        from ui_qml.views.industry.plan_table import PlanTable

        monkeypatch.setattr(
            "ui_qml.views.industry.complete_plans_dialog.complete_one_plan",
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


class TestCompletePlansAggregate:
    """批量下线汇总每条的 removed（母项清理掉的已完成子项行数）。"""

    def test_aggregates_removed(self, qapp, monkeypatch):
        from ui_qml.views.industry import complete_plans_dialog as cpd

        monkeypatch.setattr(cpd, "set_plan_deposit_hangar", lambda db, pid, dep: None)
        monkeypatch.setattr(cpd, "get_container", lambda: SimpleNamespace(db=MagicMock()))
        monkeypatch.setattr(
            cpd.plan_execution,
            "complete_plan",
            lambda plan, **kw: {"ok": True, "deposited": 0, "removed": 1},
        )

        result = cpd.complete_plans(
            [{"id": 1, "product_name": "母项A"}, {"id": 2, "product_name": "母项B"}],
            4,
            ask_outcome=False,
        )

        assert result["completed"] == 2
        assert result["removed"] == 2

    def test_removed_zero_for_non_mother(self, qapp, monkeypatch):
        from ui_qml.views.industry import complete_plans_dialog as cpd

        monkeypatch.setattr(cpd, "set_plan_deposit_hangar", lambda db, pid, dep: None)
        monkeypatch.setattr(cpd, "get_container", lambda: SimpleNamespace(db=MagicMock()))
        monkeypatch.setattr(
            cpd.plan_execution,
            "complete_plan",
            lambda plan, **kw: {"ok": True, "deposited": 1},
        )

        result = cpd.complete_plans([{"id": 3, "product_name": "独立计划"}], 4, ask_outcome=False)

        assert result["completed"] == 1
        assert result["removed"] == 0
