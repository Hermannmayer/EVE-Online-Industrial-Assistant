"""工业制造 Table Model 单元测试 — ui_pyside6/models/industry_models.py

测试覆盖:
  - PlanTableModel: 生产计划表模型
"""

import pytest
from PySide6.QtCore import Qt

from ui_pyside6.models.industry_models import PlanTableModel

pytestmark = pytest.mark.ui

# ══════════════════════════════════════
#  PlanTableModel
# ══════════════════════════════════════


class TestPlanTableModel:
    def test_construction(self):
        """可构造，行数列数正确"""
        plans = [
            {
                "product_type_id": 2001,
                "product_name": "渡鸦级",
                "batch": 5,
                "parallels": 2,
                "me_level": 10,
                "te_level": 20,
                "mat_hub": "Jita",
                "char_name": "Test",
                "profit": 10_000_000,
                "margin": 20.0,
                "score": 90,
                "iskph": 2_500_000,
                "status": "pending",
            },
        ]
        model = PlanTableModel(plans)
        assert model.rowCount() == 1
        assert model.columnCount() == 21

    def test_header_data(self, qapp):
        """表头正确"""
        model = PlanTableModel([])
        headers = [
            "☐",
            "类别",
            "图标",
            "产品",
            "备注",
            "组号",
            "子级",
            "状态",
            "人物",
            "流程",
            "蓝图",
            "时长",
            "产能",
            "设施",
            "输出",
            "成本",
            "利润",
            "市场利润率%",
            "个人利润率%",
            "成功率%",
            "解码器",
        ]
        for i, h in enumerate(headers):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

    def test_research_columns_display(self, qapp):
        """科研列：发明行显示成功率与解码器，制造行显示 —。"""
        plans = [
            {
                "product_type_id": 2001,
                "product_name": "T2 产物",
                "activity": "invention",
                "success_rate": 0.42,
                "decryptor_type_id": 34203,
                "status": "pending",
            },
            {
                "product_type_id": 2002,
                "product_name": "普通制造品",
                "activity": "manufacturing",
                "status": "pending",
            },
        ]
        model = PlanTableModel(plans)
        # 发明行：手填成功率优先
        assert model.data(model.index(0, 19)) == "42.0%"
        assert model.data(model.index(0, 20)) == "放大装置解码器"
        # 制造行：不适用
        assert model.data(model.index(1, 19)) == "—"
        assert model.data(model.index(1, 20)) == "—"

    def test_research_columns_fall_back_to_computed_rate(self, qapp):
        """未手填时显示评分算出的成功率，并标「预计」；回填后切「实产」。"""
        base = {"product_type_id": 2001, "product_name": "T2", "activity": "invention", "status": "pending"}
        model = PlanTableModel([{**base, "breakdown": {"success_rate": 0.34}}])
        assert model.data(model.index(0, 19)) == "预计 34.0%"
        model.set_plans([{**base, "actual_output_runs": 7}])
        assert model.data(model.index(0, 19)) == "实产 7"

    def test_data_display(self, qapp):
        """数据展示"""
        plans = [
            {
                "product_type_id": 2001,
                "product_name": "渡鸦级",
                "me_level": 10,
                "te_level": 20,
                "profit": 5_000_000,
                "status": "in_progress",
            }
        ]
        model = PlanTableModel(plans)
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "渡鸦级"
        assert model.data(model.index(0, 16), Qt.ItemDataRole.DisplayRole) == "5,000,000"
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "生产中"

    def test_category_column_symbol(self, qapp):
        """类别列符号与行底色"""
        plans = [
            {"product_type_id": 1, "category": "invention", "status": "pending"},
            {"product_type_id": 2, "category": "reaction", "status": "pending"},
            {"product_type_id": 3, "category": "manufacturing", "status": "pending"},
        ]
        model = PlanTableModel(plans)
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "💡"
        assert model.data(model.index(1, 1), Qt.ItemDataRole.DisplayRole) == "⚗"
        # 制造默认无底色
        assert model.data(model.index(2, 1), Qt.ItemDataRole.BackgroundRole) is None

    def test_status_label_mapping(self, qapp):
        """状态映射: pending→待生产, in_progress→生产中, completed→已完成"""
        plans = [
            {"product_type_id": 1, "batch": 1, "parallels": 1, "me_level": 0, "te_level": 0, "status": "pending"},
            {"product_type_id": 2, "batch": 1, "parallels": 1, "me_level": 0, "te_level": 0, "status": "in_progress"},
            {"product_type_id": 3, "batch": 1, "parallels": 1, "me_level": 0, "te_level": 0, "status": "completed"},
        ]
        model = PlanTableModel(plans)
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "待生产"
        assert model.data(model.index(1, 7), Qt.ItemDataRole.DisplayRole) == "生产中"
        assert model.data(model.index(2, 7), Qt.ItemDataRole.DisplayRole) == "已完成"

    def test_checkbox_column_check_state(self, qapp):
        """备料勾选列由 PlanTableDelegate 渲染为真实复选框（勾选/未勾选），DisplayRole 为空"""
        from PySide6.QtWidgets import QStyleOptionViewItem

        from ui_pyside6.views.industry.plan_table import PlanTableDelegate

        plans = [
            {"product_type_id": 1, "materials_ready": 1, "status": "pending"},
            {"product_type_id": 2, "materials_ready": 0, "status": "pending"},
        ]
        model = PlanTableModel(plans)
        delegate = PlanTableDelegate()
        opt = QStyleOptionViewItem()
        delegate.initStyleOption(opt, model.index(0, 0))
        assert opt.features & QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        assert opt.checkState == Qt.CheckState.Checked
        opt2 = QStyleOptionViewItem()
        delegate.initStyleOption(opt2, model.index(1, 0))
        assert opt2.checkState == Qt.CheckState.Unchecked
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == ""

    def test_get_plan(self):
        """get_plan 返回正确"""
        plans = [{"product_type_id": 2001}]
        model = PlanTableModel(plans)
        assert model.get_plan(0)["product_type_id"] == 2001
        assert model.get_plan(99) == {}

    def test_output_column_displays_output_hangar(self, qapp):
        """输出列显示输出机库名称，无则 '-'"""
        plans = [
            {"product_type_id": 1, "output_hangar": "成品仓库", "status": "pending"},
            {"product_type_id": 2, "status": "pending"},
        ]
        model = PlanTableModel(plans)
        assert model.data(model.index(0, 14), Qt.ItemDataRole.DisplayRole) == "成品仓库"
        assert model.data(model.index(1, 14), Qt.ItemDataRole.DisplayRole) == "-"

    def test_output_column_not_editable(self, qapp):
        """输出列为派生值（输出机库），不可行内编辑"""
        plans = [{"product_type_id": 1, "status": "pending"}]
        model = PlanTableModel(plans)
        flags = model.flags(model.index(0, 14))
        assert not (flags & Qt.ItemFlag.ItemIsEditable)

    def test_setdata_output_column_rejected(self, qapp):
        """输出列 setData 被拒绝，不改数据"""
        plans = [{"product_type_id": 1, "output_hangar": "成品仓库", "status": "pending"}]
        model = PlanTableModel(plans)
        assert model.setData(model.index(0, 14), "其它仓库", Qt.ItemDataRole.EditRole) is False
        assert model.get_plan(0)["output_hangar"] == "成品仓库"

    def test_output_column_sorts_by_hangar_name(self, qapp):
        """按输出列排序：以 output_hangar 文本排序（空串最小）"""
        plans = [
            {"product_type_id": 1, "product_name": "A", "output_hangar": "Zeta", "status": "pending"},
            {"product_type_id": 2, "product_name": "B", "output_hangar": "Alpha", "status": "pending"},
            {"product_type_id": 3, "product_name": "C", "output_hangar": "", "status": "pending"},
        ]
        model = PlanTableModel(plans)
        model.sort(14, Qt.SortOrder.AscendingOrder)
        order = [model.data(model.index(r, 3), Qt.ItemDataRole.DisplayRole) for r in range(3)]
        assert order == ["C", "B", "A"]

    def test_sort_int_columns_no_crash(self, qapp):
        """int 列（子级/流程/蓝图）排序按数值序，不抛 .lower() on int（回归）"""
        plans = [
            {
                "product_type_id": 1,
                "product_name": "A",
                "child_level": 10,
                "_runs": 100,
                "_me_level": 5,
                "status": "pending",
            },
            {
                "product_type_id": 2,
                "product_name": "B",
                "child_level": 2,
                "_runs": 3,
                "_me_level": 10,
                "status": "pending",
            },
            {
                "product_type_id": 3,
                "product_name": "C",
                "child_level": 0,
                "_runs": 30,
                "_me_level": 0,
                "status": "pending",
            },
        ]
        model = PlanTableModel(plans)
        # 列 6(子级)/9(流程)/10(蓝图) 均为 int，升序应按数值序
        expected = {6: ["C", "B", "A"], 9: ["B", "C", "A"], 10: ["C", "A", "B"]}
        for col, order_names in expected.items():
            model.sort(col, Qt.SortOrder.AscendingOrder)
            # 子项 product_name 带层级缩进（child_level>0），strip 后比对排序顺序
            order = [model.data(model.index(r, 3), Qt.ItemDataRole.DisplayRole).strip() for r in range(3)]
            assert order == order_names, f"col {col}"

    def test_sort_text_column_mixed_types_no_crash(self, qapp):
        """非数值列混入 int/None 值排序不崩溃（_sort_key 容错）"""
        plans = [
            {"product_type_id": 1, "product_name": "A", "notes": 123, "status": "pending"},
            {"product_type_id": 2, "product_name": "B", "notes": "b", "status": "pending"},
            {"product_type_id": 3, "product_name": "C", "notes": None, "status": "pending"},
        ]
        model = PlanTableModel(plans)
        model.sort(4, Qt.SortOrder.AscendingOrder)  # 备注列：int/str/None 混合
        order = [model.data(model.index(r, 3), Qt.ItemDataRole.DisplayRole) for r in range(3)]
        assert order == ["A", "C", "B"]  # 数值组排前，None 与文本按小写


class TestMeTeColumnWithPerLineLevels:
    """ME/TE 列在「各并行线等级不一致」时的展示（逐线计算上线后）。"""

    _BASE = {
        "id": 1,
        "product_name": "渡鸦级",
        "me_level": 0,
        "te_level": 0,
        "has_image": True,
        "bound_blueprint_ids": [],
        "need_blueprints": 1,
        "status": "pending",
    }

    @staticmethod
    def _text(plan: dict) -> str:
        m = PlanTableModel([plan])
        return str(m.data(m.index(0, 10), Qt.ItemDataRole.DisplayRole))

    def test_uniform_shows_plan_level_without_marker(self):
        """各线与计划级一致 → 显示计划级、无标记（逐值不变）。"""
        text = self._text({**self._BASE, "me_level": 10, "te_level": 20, "line_levels": [(10, 20), (10, 20)]})
        assert text.startswith("10-20[")
        assert "≠" not in text

    def test_no_line_levels_uses_plan_level(self):
        assert self._text(self._BASE).startswith("0-0[")

    def test_mixed_shows_lowest_with_marker(self):
        """不一致 → 显示**最低那组** + `≠` 标记。"""
        text = self._text({**self._BASE, "me_level": 10, "te_level": 20, "line_levels": [(10, 20), (8, 15), (12, 25)]})
        assert text.startswith("8-15≠[")

    def test_tooltip_lists_each_line(self):
        plan = {**self._BASE, "me_level": 10, "te_level": 20, "line_levels": [(10, 20), (8, 15)]}
        m = PlanTableModel([plan])
        tip = m.data(m.index(0, 10), Qt.ItemDataRole.ToolTipRole)
        assert "第 1 条线" in tip and "第 2 条线" in tip

    def test_tooltip_empty_when_uniform(self):
        plan = {**self._BASE, "me_level": 10, "te_level": 20, "line_levels": [(10, 20), (10, 20)]}
        m = PlanTableModel([plan])
        assert m.data(m.index(0, 10), Qt.ItemDataRole.ToolTipRole) == ""

    def test_uniform_lines_differing_from_plan_level_no_marker(self):
        """各线一致（都 10/20）但计划级写着 0/0 → 列里显示**实际生效**的 10-20，**不加** `≠`。

        `≠` 的语义是「各线之间不一致」，不是「与计划级不同」—— 否则每个绑了蓝图的计划
        都会带标记，噪声过大。
        """
        text = self._text({**self._BASE, "me_level": 0, "te_level": 0, "line_levels": [(10, 20), (10, 20)]})
        assert text.startswith("10-20[")
        assert "≠" not in text
