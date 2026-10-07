"""个人利润率%（personal_margin）计算测试

覆盖：
- 与市场列同口径（无库存 = 市场利润率）
- 全库存 / 部分库存 / 零成本库存 / runs·parallels 缩放的混合成本
- 无材料 / 收入 0 / 异常回退
- calculate_plan_metrics 端到端透传、prod_qty>1、ME 单件豁免
- 旧坏 SQL 根因（blueprint_activities 无 quantity 列）回归
- worker 层（库存快照只取一次）
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.cache import TtlLRUCache
from services.plan_metrics import SubitemCost, mother_subitem_cost_map
from services.scoring_service import ScoringService

pytestmark = pytest.mark.ui

# ════════════════════════════════════════════════════════════════
#  辅助 fixture / 构造器
# ════════════════════════════════════════════════════════════════


@pytest.fixture
def svc(temp_db):
    """绑定临时数据库的评分服务（函数级作用域，每个测试独立）"""
    return ScoringService(temp_db, TtlLRUCache(max_size=10))


def _per_run_result(svc, char_config, type_id: int = 2001, **kw) -> dict:
    """调用 calc_manufacturing_score 构造与 calculate_plan_metrics 同构的 result 字典。

    calc_manufacturing_score 内部已写入 revenue_per_run / fees_per_run / materials，
    这里只提取个人利润率需要的字段。
    """
    per_run = svc.calc_manufacturing_score(
        type_id=type_id,
        char_config=char_config,
        mat_source_hub="Jita",
        sell_hub="Jita",
        facility_tax_pct=0.0,
        price_type_mat="sell",
        price_type_prod="sell",
        **kw,
    )
    return {
        "margin": per_run.get("margin_pct", 0),
        "revenue_per_run": per_run.get("revenue_per_run", 0),
        "fees_per_run": per_run.get("fees_per_run", 0),
        "materials": per_run.get("materials", []),
    }


# ════════════════════════════════════════════════════════════════
#  纯函数 calculate_personal_margin
# ════════════════════════════════════════════════════════════════


def test_no_inventory_equals_market_margin(svc, sample_char_config):
    """无库存 = 市场利润率（问题 1 回归核心：旧实现 SQL 抛异常被吞、恒等于市场列）"""
    result = _per_run_result(svc, sample_char_config)  # 渡鸦 2001
    assert result["margin"] > 0
    # 材料条目带 type_id（问题 1 数据源修正）
    assert {m["type_id"] for m in result["materials"]} == {1001, 1002}
    personal = ScoringService.calculate_personal_margin(result, {}, 1, 1)
    assert personal == pytest.approx(result["margin"], abs=0.005)


def test_full_inventory_lower_cost_raises_margin(svc, sample_char_config):
    """全库存低成本 → 利润率更高，且数值精确匹配公式"""
    result = _per_run_result(svc, sample_char_config)
    inv = {1001: (1000, 4.0), 1002: (500, 8.0)}  # 恰好覆盖，成本低于市场 5.0/9.0
    personal = ScoringService.calculate_personal_margin(result, inv, 1, 1)
    exp_cost = 1000 * 4.0 + 500 * 8.0 + result["fees_per_run"]
    expected = (result["revenue_per_run"] - exp_cost) / exp_cost * 100
    assert personal == pytest.approx(expected, abs=0.005)
    assert personal > result["margin"]


def test_expensive_inventory_lowers_margin(svc, sample_char_config):
    """材料降价后库存成本高于市场价 → 个人利润率低于市场利润率（真实成本视角）"""
    result = _per_run_result(svc, sample_char_config)
    inv = {1001: (1000, 10.0), 1002: (500, 18.0)}  # 买入价高于当前市场 5.0/9.0
    personal = ScoringService.calculate_personal_margin(result, inv, 1, 1)
    exp_cost = 1000 * 10.0 + 500 * 18.0 + result["fees_per_run"]
    expected = (result["revenue_per_run"] - exp_cost) / exp_cost * 100
    assert personal == pytest.approx(expected, abs=0.005)
    assert personal < result["margin"]


def test_partial_inventory_mixes_cost(svc, sample_char_config):
    """部分库存混合成本，利润率介于市场与全库存之间"""
    result = _per_run_result(svc, sample_char_config)
    inv = {1001: (400, 4.0)}  # 1001 需 1000 仅 400，补齐 600×市场价 5.0
    personal = ScoringService.calculate_personal_margin(result, inv, 1, 1)
    mat_cost = 400 * 4.0 + 600 * 5.0 + 500 * 9.0  # 4600 + 4500
    exp_cost = mat_cost + result["fees_per_run"]
    expected = (result["revenue_per_run"] - exp_cost) / exp_cost * 100
    assert personal == pytest.approx(expected, abs=0.005)
    # 成本 9100 介于市场 9500 与全库存 8000 之间 → 利润率亦介于两者之间
    full_margin = ScoringService.calculate_personal_margin(result, {1001: (1000, 4.0), 1002: (500, 8.0)}, 1, 1)
    assert result["margin"] < personal < full_margin


def test_zero_cost_stock_counts_as_inventory(svc, sample_char_config):
    """零成本库存算库存（问题 5 语义回归：不回落市场价）"""
    result = _per_run_result(svc, sample_char_config)
    inv = {1001: (1000, 0.0)}  # 全部覆盖但成本 0
    personal = ScoringService.calculate_personal_margin(result, inv, 1, 1)
    mat_cost = 1000 * 0.0 + 500 * 9.0  # 4500，绝不是 500×9+1000×5=9500
    exp_cost = mat_cost + result["fees_per_run"]
    expected = (result["revenue_per_run"] - exp_cost) / exp_cost * 100
    assert personal == pytest.approx(expected, abs=0.005)


def test_runs_parallels_scaling(svc, sample_char_config):
    """runs/parallels 缩放：无库存仍等于市场利润率；有库存按 total_mult 混合"""
    result = _per_run_result(svc, sample_char_config)
    personal_empty = ScoringService.calculate_personal_margin(result, {}, 3, 2)
    assert personal_empty == pytest.approx(result["margin"], abs=0.005)  # 比值与 total_mult 无关

    inv = {1001: (1000, 4.0)}  # 1001 需 6000 仅 1000
    personal = ScoringService.calculate_personal_margin(result, inv, 3, 2)
    mat_cost = 1000 * 4.0 + 5000 * 5.0 + 3000 * 9.0
    exp_cost = mat_cost + result["fees_per_run"] * 6
    expected = (result["revenue_per_run"] * 6 - exp_cost) / exp_cost * 100
    assert personal == pytest.approx(expected, abs=0.005)


def test_empty_materials_falls_back():
    """无材料 → 回退市场 margin"""
    result = {"margin": 12.5, "revenue_per_run": 100.0, "fees_per_run": 10.0, "materials": []}
    assert ScoringService.calculate_personal_margin(result, {}, 1, 1) == 12.5


def test_zero_revenue_falls_back():
    """收入 0 → 回退市场 margin"""
    result = {
        "margin": 12.5,
        "revenue_per_run": 0.0,
        "fees_per_run": 10.0,
        "materials": [{"type_id": 1, "qty": 5, "unit_price": 2.0}],
    }
    assert ScoringService.calculate_personal_margin(result, {}, 1, 1) == 12.5


def test_bad_inv_map_falls_back():
    """inv_map 值非法（解包异常）→ 回退市场 margin"""
    result = {
        "margin": 12.5,
        "revenue_per_run": 100.0,
        "fees_per_run": 10.0,
        "materials": [{"type_id": 1, "qty": 5, "unit_price": 2.0}],
    }
    assert ScoringService.calculate_personal_margin(result, {1: "bad"}, 1, 1) == 12.5


# ════════════════════════════════════════════════════════════════
#  calculate_plan_metrics 端到端透传
# ════════════════════════════════════════════════════════════════


def test_calculate_plan_metrics_exposes_personal_inputs(svc, sample_char_config):
    """calculate_plan_metrics 返回个人利润率输入 + 无库存端到端相等"""
    plan = {
        "product_type_id": 2001,
        "runs": 1,
        "parallels": 1,
        "me_level": 0,
        "te_level": 0,
        "mat_hub": "Jita",
        "sell_hub": "Jita",
    }
    with patch("core.container.get_container") as mock_cont:
        mock_cont.return_value.scoring_service.return_value = svc
        result = ScoringService.calculate_plan_metrics(
            plan, sample_char_config, price_type_mat="sell", price_type_prod="sell"
        )
    assert result["revenue"] == pytest.approx(55_000_000, abs=0.01)  # 55M×1×1
    assert result["revenue_per_run"] == pytest.approx(55_000_000, abs=0.01)
    assert result["fees_per_run"] > 0 and result["fees"] > 0
    assert result["materials"] and all("type_id" in m for m in result["materials"])
    assert ScoringService.calculate_personal_margin(result, {}, 1, 1) == pytest.approx(result["margin"], abs=0.005)


def test_prod_qty_gt_one_revenue_included(svc, sample_char_config):
    """产物数量 > 1（问题 2 回归：收入必须含 prod_qty）"""
    with svc._db.connect("bp") as conn:
        conn.execute(
            "UPDATE blueprint_products SET quantity = 5 WHERE blueprint_type_id = 3002 AND product_type_id = 2002"
        )
    result = _per_run_result(svc, sample_char_config, type_id=2002)  # 无人机
    assert result["revenue_per_run"] == pytest.approx(120_000 * 5, abs=0.01)
    assert ScoringService.calculate_personal_margin(result, {}, 1, 1) == pytest.approx(result["margin"], abs=0.005)


def test_single_item_material_exemption(svc, sample_char_config):
    """单件材料（基础量=1）不受 ME 影响（问题 4 回归：口径与市场列一致）"""
    with svc._db.connect("bp") as conn:
        conn.execute("INSERT INTO blueprint_materials VALUES (3001, 'manufacturing', 2002, 1, 10)")
    per_run = svc.calc_manufacturing_score(
        type_id=2001,
        char_config=sample_char_config,
        mat_source_hub="Jita",
        sell_hub="Jita",
        bp_me=10,
    )
    m = next(x for x in per_run["materials"] if x["type_id"] == 2002)
    assert m["qty"] == 1 and m["is_whole_item"] is True  # ME10 也不削减


# ════════════════════════════════════════════════════════════════
#  旧坏 SQL 根因回归
# ════════════════════════════════════════════════════════════════


def test_blueprint_activities_has_no_quantity_column(temp_db):
    """旧实现 SELECT ba.quantity 必然抛异常被吞掉（生产/测试 schema 一致）"""
    with temp_db.connect("bp") as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(blueprint_activities)")]
    assert "quantity" not in cols


# ════════════════════════════════════════════════════════════════
#  worker 层回归
# ════════════════════════════════════════════════════════════════


def test_worker_personal_margin(qapp, sample_char_config):
    """worker 的 _calc_personal_margin 走 result + 库存快照，不再直连蓝图库"""
    from ui_qml.workers.industry_workers import BatchPlanCalcWorker

    w = BatchPlanCalcWorker(
        [],
        sample_char_config,
        mat_hub="Jita",
        mat_price_type="sell",
        prod_hub="Jita",
        prod_price_type="sell",
    )
    result = {
        "margin": 12.5,
        "revenue_per_run": 1000.0,
        "fees_per_run": 100.0,
        "materials": [{"type_id": 1001, "qty": 10, "unit_price": 5.0}],
    }
    with patch(
        "services.inventory_manager.get_inventory_cost_map",
        return_value={1001: (10, 4.0)},
    ):
        personal = w._calc_personal_margin({"runs": 1, "parallels": 1}, result)
    # 成本 = 10×4(库存) + 100(费用) = 140
    assert personal == pytest.approx((1000 - 140) / 140 * 100, abs=0.005)
    assert w._inv_map is not None  # 快照只取一次


def test_mother_subitem_override_feeds_cost_and_profit(qapp, sample_char_config, temp_db, monkeypatch):
    """拆解母项：子项自制价既进 overrides（供个人利润率），也**折算进成本/利润/利润率**。

    用户 2026-10-07 拍板：成本/利润 改个人口径（10-03 曾定市场口径），所以这里返回的是
    「(成本, 利润, 利润率, overrides)」四元组，`result` 本身仍不被修改。
    子项产线的**产出量**走 `output_qty_by_plan`（这里 2 轮×1 件 = 2 件）→ 制造价摊成单件。
    """
    from ui_qml.workers.industry_workers import BatchPlanCalcWorker

    w = BatchPlanCalcWorker(
        [],
        sample_char_config,
        mat_hub="Jita",
        mat_price_type="sell",
        prod_hub="Jita",
        prod_price_type="sell",
    )
    # 子项每轮产出查蓝图库（无人机 2002 = 1 件/轮）
    monkeypatch.setattr(
        "ui_qml.workers.industry_workers.get_container",
        lambda: SimpleNamespace(db=temp_db),
    )
    mother = {"id": 1, "group_id": 10, "child_level": 0, "runs": 1, "parallels": 1}
    result = {
        "materials": [
            {"type_id": 1001, "qty": 10, "unit_price": 5.0},  # 未拆解 → 10×5=50
            {"type_id": 2002, "qty": 2, "unit_price": 999.0},  # 子项自制 → 整线制造价 5000
        ],
        "revenue": 20000.0,
        "fees": 100.0,
        "material_cost": 2048.0,
        "profit": 20000.0 - 2048.0 - 100.0,
        "margin": (20000.0 - 2048.0 - 100.0) / (2048.0 + 100.0) * 100.0,
    }
    base_results = {
        1: (mother, result),
        2: (
            {
                "id": 2,
                "group_id": 10,
                "child_level": 1,
                "product_type_id": 2002,
                "runs": 2,
                "parallels": 1,
            },
            {"material_cost": 4800.0, "breakdown": {"installation_fee": 100.0}},
        ),
    }
    mat, profit, margin, overrides = w._apply_mother_subitem_cost(mother, result, base_results)
    # 子项制造价 = 材料 4800 + 作业费 100×2 runs = 5000（整线），产出 2 件 → 单件 2500
    assert overrides == {2002: SubitemCost(unit_cost=2500.0, covered_qty=2.0)}
    # 个人口径成本 = 50（未拆解的料）+ 2×2500（子项自制件）；利润/利润率随之重算
    assert mat == pytest.approx(5050.0, abs=0.01)
    assert profit == pytest.approx(20000.0 - 5050.0 - 100.0, abs=0.01)
    assert margin == pytest.approx(profit / (mat + 100.0) * 100, abs=0.01)
    # 入参 result 不被修改（调用方还要拿它留存市场口径）
    assert result["material_cost"] == pytest.approx(2048.0, abs=0.01)
    assert result["profit"] == pytest.approx(17852.0, abs=0.01)


def test_ungrouped_mother_not_adjusted(qapp, sample_char_config):
    """无子项的普通计划不受子项分摊影响：四个返回值都原样回吐 result 的口径。"""
    from ui_qml.workers.industry_workers import BatchPlanCalcWorker

    w = BatchPlanCalcWorker(
        [],
        sample_char_config,
        mat_hub="Jita",
        mat_price_type="sell",
        prod_hub="Jita",
        prod_price_type="sell",
    )
    plan = {"id": 1, "group_id": 0, "child_level": 0, "runs": 1, "parallels": 1}
    result = {
        "materials": [{"type_id": 1001, "qty": 10, "unit_price": 5.0}],
        "revenue": 1000.0,
        "fees": 100.0,
        "material_cost": 0,
        "profit": 0,
        "margin": 0,
    }
    mat, profit, margin, overrides = w._apply_mother_subitem_cost(plan, result, {1: (plan, result)})
    assert (mat, profit, margin, overrides) == (0, 0, 0, {})


def test_personal_margin_uses_cost_override(qapp):
    """子项自制件按其**自制单件价**计：覆盖到的按自制价，**缺口仍按市价**（不再当 0 成本）。"""
    from services.scoring_service import ScoringService

    result = {
        "margin": 12.5,
        "revenue_per_run": 10000.0,
        "fees_per_run": 100.0,
        "materials": [{"type_id": 2002, "qty": 4, "unit_price": 999.0}],
    }
    # 自制单件 500、覆盖 3 件（子项产线只排了净需求）；缺的 1 件无库存 → 按市价 999
    personal = ScoringService.calculate_personal_margin(
        result, {}, 1, 1, cost_overrides={2002: SubitemCost(unit_cost=500.0, covered_qty=3.0)}
    )
    exp_cost = 3 * 500.0 + 1 * 999.0 + 100.0
    assert personal == pytest.approx((10000.0 - exp_cost) / exp_cost * 100, abs=0.005)


def test_child_manufacturing_cost_includes_job_fee():
    """子项制造价 = 材料成本 + 作业费 × runs × parallels。"""
    from services.scoring_service import ScoringService

    plan = {"runs": 2, "parallels": 3}
    metrics = {"material_cost": 1000.0, "breakdown": {"installation_fee": 50.0}}
    assert ScoringService.child_manufacturing_cost(plan, metrics) == pytest.approx(1300, abs=0.01)
    # breakdown 缺失时兜底仅材料成本
    assert ScoringService.child_manufacturing_cost(plan, {"material_cost": 1000.0}) == pytest.approx(1000, abs=0.01)


def test_child_manufacturing_cost_zero_runs_is_free_and_excluded_from_map():
    """runs=0 的子项产线一个都不产出（回归：曾被当 1 轮×parallels 计成 150）。

    制造价必须是 0，且不能进 mother_subitem_cost_map —— 否则「自制件成本 0 ISK」
    会被 adjust_mother_metrics 当成真实成本写进母项，母项材料成本被凭空调低。
    runs 缺失仍保留 1 轮兜底。
    """
    from services.scoring_service import ScoringService

    metrics = {"material_cost": 1000.0, "breakdown": {"installation_fee": 50.0}}
    assert ScoringService.child_manufacturing_cost({"runs": 0, "parallels": 3}, metrics) == pytest.approx(0.0, abs=0.01)
    # runs 缺失（不是字面 0）→ 保留 max(...,1) 兜底
    assert ScoringService.child_manufacturing_cost({"parallels": 3}, metrics) == pytest.approx(1150, abs=0.01)

    base = {
        320: (
            {"id": 320, "product_type_id": 41484, "group_number": 1, "sub_level": 1, "runs": 0, "parallels": 3},
            metrics,
        )
    }
    assert mother_subitem_cost_map(base, {"id": 311, "group_number": 1, "sub_level": 0}) == {}


def test_adjust_mother_metrics_does_not_mutate_input():
    """adjust_mother_metrics：自制子项按制造价计，返回 overrides，不改入参。"""
    from services.scoring_service import ScoringService

    metrics = {
        "materials": [
            {"type_id": 1001, "qty": 10, "unit_price": 5.0},
            {"type_id": 2002, "qty": 2, "unit_price": 999.0},
        ],
        "revenue": 20000.0,
        "fees": 100.0,
    }
    mat, profit, margin, overrides = ScoringService.adjust_mother_metrics(
        metrics, {2002: SubitemCost(unit_cost=2500.0, covered_qty=2.0)}, 1
    )
    assert mat == pytest.approx(5050, abs=0.01)  # 50(三钛) + 2×2500(子项自制单件价)
    assert profit == pytest.approx(14850, abs=0.01)
    assert margin == pytest.approx(14850 / 5150 * 100, abs=0.01)
    assert overrides == {2002: SubitemCost(unit_cost=2500.0, covered_qty=2.0)}
    assert "material_cost" not in metrics  # 入参未被修改


def test_worker_run_uses_personal_basis_for_cost_profit(qapp, sample_char_config, temp_db, monkeypatch):
    """run()：成本/利润/利润率/ISK/h 走**个人口径**（同组自制件按自制单件价），市场口径另存 market_margin。

    用户 2026-10-07 拍板：之前成本/利润按市场口径（自制件按买入市价），于是同一行会出现
    「利润 −2.88 亿」+「个人利润率 +21%」自相矛盾、核算对话框也跟大表对不上。
    """
    from unittest.mock import patch

    from ui_qml.workers.industry_workers import BatchPlanCalcWorker

    # 子项每轮产出按蓝图查（无人机 2002 = 1 件/轮 × 2 轮 = 2 件）
    monkeypatch.setattr(
        "ui_qml.workers.industry_workers.get_container",
        lambda: SimpleNamespace(db=temp_db),
    )
    mother = {"id": 1, "group_id": 10, "child_level": 0, "runs": 1, "parallels": 1}
    child = {"id": 2, "group_id": 10, "child_level": 1, "product_type_id": 2002, "runs": 2, "parallels": 1}
    w = BatchPlanCalcWorker(
        [mother, child],
        sample_char_config,
        mat_hub="Jita",
        mat_price_type="sell",
        prod_hub="Jita",
        prod_price_type="sell",
    )
    # 市场口径: 材料 10×5 + 2×999 = 2048；子项制造价 = 1100 + 50×2 = 1200 < 市场买入 1998
    mother_result = {
        "materials": [
            {"type_id": 1001, "qty": 10, "unit_price": 5.0},
            {"type_id": 2002, "qty": 2, "unit_price": 999.0},
        ],
        "revenue": 20000.0,
        "fees": 100.0,
        "material_cost": 2048.0,
        "profit": 20000.0 - 2048.0 - 100.0,
        "margin": (20000.0 - 2048.0 - 100.0) / (2048.0 + 100.0) * 100.0,
        "revenue_per_run": 20000.0,
        "fees_per_run": 100.0,
        "score": 0,
        "iskph": 0,
        "calculated_time": 3600,
        "daily_output": 0,
    }
    child_result = {
        "material_cost": 1100.0,
        "breakdown": {"installation_fee": 50.0},
        "margin": 0,
        "score": 0,
        "iskph": 0,
        "calculated_time": 3600,
        "daily_output": 0,
    }
    captured: list = []
    w.finished_signal.connect(captured.append)
    with (
        patch.object(
            BatchPlanCalcWorker,
            "_calc_base",
            side_effect=lambda item: {1: mother_result, 2: child_result}.get(item.get("id"), {}),
        ),
        patch("services.inventory_manager.get_inventory_cost_map", return_value={}),
    ):
        w.run()
    by_id = {r[0]: r for r in captured[0]}
    mother_out = by_id[1]
    market_margin = (20000.0 - 2048.0 - 100.0) / (2048.0 + 100.0) * 100.0
    personal_material = 10 * 5.0 + 2 * 600.0  # 子项 2 件按自制单件价 600（1200 整线 ÷ 2 件）
    personal_profit = 20000.0 - personal_material - 100.0
    personal_margin = personal_profit / (personal_material + 100.0) * 100.0
    # 市场利润率列 = 调整前留存的市场口径
    assert mother_out[9] == pytest.approx(market_margin, abs=0.01)
    # 成本/利润/利润率列 = 个人口径（自制件按自制价，不再按 999 的买入市价）
    assert mother_out[5] == pytest.approx(personal_material, abs=0.01)
    assert mother_out[1] == pytest.approx(personal_profit, abs=0.01)
    assert mother_out[2] == pytest.approx(personal_margin, abs=0.005)
    # ISK/h 与利润同口径：耗时 1h → 就是利润本身（旧写法取市场口径的 iskph）
    assert mother_out[4] == pytest.approx(personal_profit, abs=0.01)
    # 个人利润率（库存成本口径；本用例无库存 → 与利润率列同值）
    assert mother_out[8] == pytest.approx(personal_margin, abs=0.01)
    assert mother_out[8] > market_margin


# ════════════════════════════════════════════════════════════════
#  mother_subitem_cost_map（母项子项制造价映射，纯函数）
# ════════════════════════════════════════════════════════════════


def test_mother_subitem_cost_map_basic():
    """母项同组更深子项 → {子项 product_type_id: SubitemCost}。

    给了 `output_qty_by_plan`（子项产线实际产出量）就摊成**单件**制造价 + 覆盖数量；
    没给则退回旧口径（`covered_qty=None` = 消费方按「覆盖全部需求」处理）。
    """
    base = {
        2: (
            {"id": 2, "product_type_id": 42527, "group_number": 1, "sub_level": 1, "runs": 2, "parallels": 1},
            {"material_cost": 1000.0, "breakdown": {"installation_fee": 10.0}},
        )
    }
    mother = {"id": 1, "group_number": 1, "sub_level": 0}
    assert mother_subitem_cost_map(base, mother) == {42527: SubitemCost(unit_cost=1020.0, covered_qty=None)}
    # 整线制造价 1020、产出 4 件 → 单件 255，覆盖 4 件
    assert mother_subitem_cost_map(base, mother, output_qty_by_plan={2: 4}) == {
        42527: SubitemCost(unit_cost=255.0, covered_qty=4.0)
    }


def test_mother_subitem_cost_map_no_group():
    """母项无 group → 返回空 dict（不改动）。"""
    base = {
        2: (
            {"id": 2, "product_type_id": 42527, "group_number": 1, "sub_level": 1, "runs": 1, "parallels": 1},
            {"material_cost": 1000.0, "breakdown": {"installation_fee": 10.0}},
        )
    }
    assert mother_subitem_cost_map(base, {"id": 1, "sub_level": 0}) == {}


def test_mother_subitem_cost_map_no_deeper_sub():
    """同组无更深子项（子项 sub_level 不高于母项）→ 空 dict。"""
    base = {
        2: (
            {"id": 2, "product_type_id": 42527, "group_number": 1, "sub_level": 0, "runs": 1, "parallels": 1},
            {"material_cost": 1000.0, "breakdown": {"installation_fee": 10.0}},
        )
    }
    mother = {"id": 1, "group_number": 1, "sub_level": 0}
    assert mother_subitem_cost_map(base, mother) == {}
