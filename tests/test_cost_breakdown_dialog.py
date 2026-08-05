"""成本明细弹窗测试 — cost_breakdown_dialog.py

覆盖：拆解母项的子项制造价计算（材料 + 作业费）、嵌套拆解自底向上。
"""

from unittest.mock import patch

import pytest

from services.repositories.plan_repository import PlanRepository
from ui_pyside6.views.industry.cost_breakdown_dialog import CostBreakdownDialog


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
            {"id": 1, "product_type_id": 2001, "product_name": "母项", "runs": 1, "parallels": 1, "group_number": 7, "sub_level": 0},
            {"id": 2, "product_type_id": 2002, "product_name": "子项", "runs": 2, "parallels": 1, "group_number": 7, "sub_level": 1},
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
            {"id": 1, "product_type_id": 2001, "product_name": "母项", "runs": 1, "parallels": 1, "group_number": 7, "sub_level": 0},
            {"id": 2, "product_type_id": 2002, "product_name": "子项", "runs": 1, "parallels": 1, "group_number": 7, "sub_level": 1},
            {"id": 3, "product_type_id": 3003, "product_name": "孙项", "runs": 1, "parallels": 1, "group_number": 7, "sub_level": 2},
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
