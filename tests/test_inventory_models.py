"""蓝图表「蓝图成本」列（T2/T3 发明 BPC 的期望单流程成本）。

需求：机库蓝图管理表新增「蓝图成本」列；仅 T2/T3 蓝图拷贝显示数值，T1/原图显示 —。
不写外观断言（不测宽度/颜色），只测 display 契约（按判定表：模型列不做外观断言）。
"""

import pytest
from PySide6.QtCore import Qt

from ui_qml.models.inventory_helpers import BlueprintTableModel
from ui_qml.models.inventory_qml_models import BlueprintQmlModel

pytestmark = pytest.mark.ui

ROWS = [
    # T2 BPC：有成本 → 显示数值
    {"blueprint_type_id": 3001, "is_bpo": False, "tech_level": 2, "runs": 10, "cost_per_run": 1234.0},
    # T1：即使手填了 cost_per_run 也不显示（T1 没有发明成本口径）
    {"blueprint_type_id": 3002, "is_bpo": False, "tech_level": 1, "runs": 10, "cost_per_run": 1234.0},
    # T2 原图：BPO 没有「每流程」概念 → —
    {"blueprint_type_id": 3003, "is_bpo": True, "tech_level": 2, "runs": 0, "cost_per_run": 1234.0},
    # T2 BPC 但还没填成本 → —
    {"blueprint_type_id": 3004, "is_bpo": False, "tech_level": 2, "runs": 10, "cost_per_run": 0.0},
    # T3 BPC：与 T2 同口径显示数值（战略巡洋舰/子系统蓝图）
    {"blueprint_type_id": 3005, "is_bpo": False, "tech_level": 3, "runs": 20, "cost_per_run": 2345.0},
    # T3 原图：BPO 仍然 —（与原图无关科技等级）
    {"blueprint_type_id": 3006, "is_bpo": True, "tech_level": 3, "runs": 0, "cost_per_run": 2345.0},
]


def test_column_count_and_header(qapp):
    model = BlueprintTableModel(ROWS)
    assert model.columnCount() == 14
    assert model.headerData(13, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "蓝图成本"


@pytest.mark.parametrize(
    "row, expected",
    [(0, "1,234 ISK"), (1, "—"), (2, "—"), (3, "—"), (4, "2,345 ISK"), (5, "—")],
)
def test_only_t2_t3_bpc_shows_cost(qapp, row, expected):
    model = BlueprintTableModel(ROWS)
    assert model.data(model.index(row, 13), Qt.ItemDataRole.DisplayRole) == expected


def test_qml_model_uses_same_display_rule(qapp):
    model = BlueprintQmlModel(ROWS)
    text_role = int(Qt.ItemDataRole.UserRole) + 1  # BP_ROLE_NAMES 的 "text"
    assert model.data(model.index(0, 13), text_role) == "1,234 ISK"
    assert model.data(model.index(1, 13), text_role) == "—"
    assert model.data(model.index(4, 13), text_role) == "2,345 ISK"
    assert 13 in BlueprintQmlModel.SORTABLE


def test_cost_column_sorts_by_value(qapp):
    model = BlueprintTableModel(
        [
            {"blueprint_type_id": 1, "is_bpo": False, "tech_level": 2, "cost_per_run": 500.0},
            {"blueprint_type_id": 2, "is_bpo": False, "tech_level": 2, "cost_per_run": 100.0},
        ]
    )
    model.sort(13, Qt.SortOrder.AscendingOrder)
    assert model.row_at(0)["blueprint_type_id"] == 2
