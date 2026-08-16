"""工业制造 Table Model 单元测试 — ui_pyside6/models/industry_models.py

测试覆盖:
  - PlanTableModel: 生产计划表模型
"""

from PySide6.QtCore import Qt

from ui_pyside6.models.industry_models import PlanTableModel

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
        assert model.columnCount() == 19

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
        ]
        for i, h in enumerate(headers):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

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
