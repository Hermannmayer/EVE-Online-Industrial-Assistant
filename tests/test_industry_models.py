"""工业制造 Table Model 单元测试 — ui_pyside6/models/industry_models.py

测试覆盖:
  - RankTableModel: 利润排行表模型
  - PlanTableModel: 生产计划表模型
  - MaterialTableModel: 材料清单表模型
  - ProcurementTableModel: 采购表模型
"""

from PySide6.QtCore import Qt

from ui_pyside6.models.industry_models import (
    MaterialTableModel,
    PlanTableModel,
    ProcurementTableModel,
    ProductionTableModel,
    RankTableModel,
)

# ══════════════════════════════════════
#  RankTableModel
# ══════════════════════════════════════


class TestRankTableModel:
    def test_construction(self):
        """可构造，行数列数正确"""
        rows = [
            {
                "_type_id": 2001,
                "_name": "渡鸦级",
                "profit_per_run": 5_000_000,
                "margin_pct": 15.5,
                "isk_per_hour": 1_200_000,
                "score": 85,
                "cost_per_unit": 30_000_000,
                "hours_per_run": 4.0,
            },
        ]
        model = RankTableModel(rows)
        assert model.rowCount() == 1
        assert model.columnCount() == 7

    def test_empty_rows(self):
        """空数据构造"""
        model = RankTableModel([])
        assert model.rowCount() == 0
        assert model.columnCount() == 7

    def test_header_data(self):
        """表头正确"""
        model = RankTableModel([])
        headers = ["成品", "利润/run", "利润率%", "ISK/h", "评分", "成本/unit", "时/run"]
        for i, h in enumerate(headers):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

    def test_data_display(self, qapp):
        """数据展示格式正确"""
        rows = [
            {
                "_type_id": 2001,
                "_name": "渡鸦级",
                "profit_per_run": 5_000_000,
                "margin_pct": 15.5,
                "isk_per_hour": 1_200_000,
                "score": 85,
                "cost_per_unit": 30_000_000,
                "hours_per_run": 4.0,
            },
        ]
        model = RankTableModel(rows)
        idx = model.index(0, 0)
        assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "渡鸦级"
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "5,000,000"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "15.5"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "1,200,000"

    def test_data_foreground_profit_positive(self, qapp):
        """利润为正时绿色"""
        from ui_pyside6 import theme

        rows = [{"_type_id": 2001, "profit_per_run": 1000, "score": 80}]
        model = RankTableModel(rows)
        color = model.data(model.index(0, 1), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.GREEN

    def test_data_foreground_profit_negative(self, qapp):
        """利润为负时红色"""
        from ui_pyside6 import theme

        rows = [{"_type_id": 2001, "profit_per_run": -100, "score": 20}]
        model = RankTableModel(rows)
        color = model.data(model.index(0, 1), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.RED

    def test_data_foreground_score_high(self, qapp):
        """评分 >= 70 绿色"""
        from ui_pyside6 import theme

        rows = [{"_type_id": 2001, "score": 85}]
        model = RankTableModel(rows)
        color = model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.GREEN

    def test_data_foreground_score_low(self, qapp):
        """评分 < 30 红色"""
        from ui_pyside6 import theme

        rows = [{"_type_id": 2001, "score": 15}]
        model = RankTableModel(rows)
        color = model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.RED

    def test_data_foreground_score_mid(self, qapp):
        """评分 30~70 用 PRIMARY"""
        from ui_pyside6 import theme

        rows = [{"_type_id": 2001, "score": 50}]
        model = RankTableModel(rows)
        color = model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.PRIMARY

    def test_get_row(self):
        """get_row 返回正确行数据"""
        rows = [{"_type_id": 2001, "_name": "渡鸦级"}]
        model = RankTableModel(rows)
        assert model.get_row(0)["_type_id"] == 2001
        assert model.get_row(1) == {}  # 越界返回空 dict


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
            order = [model.data(model.index(r, 3), Qt.ItemDataRole.DisplayRole) for r in range(3)]
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


# ══════════════════════════════════════
#  MaterialTableModel
# ══════════════════════════════════════


class TestMaterialTableModel:
    def test_construction(self):
        """可构造"""
        rows = [{"name": "三钛合金", "need": 10000, "price": 5.0, "total": 50000.0}]
        model = MaterialTableModel(rows)
        assert model.rowCount() == 1
        assert model.columnCount() == 4

    def test_header_data(self, qapp):
        """表头正确"""
        model = MaterialTableModel([])
        assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "材料"
        assert model.headerData(3, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "总价"

    def test_data_display(self, qapp):
        """数据展示"""
        rows = [{"name": "三钛合金", "need": 10000, "price": 5.1234, "total": 51234.0}]
        model = MaterialTableModel(rows)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "三钛合金"
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "10000"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "5.12"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "51,234.00"

    def test_empty_rows(self):
        """空数据"""
        model = MaterialTableModel([])
        assert model.rowCount() == 0


# ══════════════════════════════════════
#  ProductionTableModel
# ══════════════════════════════════════


class TestProductionTableModel:
    """ProductionTableModel — 生产执行跟踪表"""

    def test_construction(self):
        """可构造，行列数正确"""
        plans = [
            {
                "product_type_id": 2001,
                "product_name": "渡鸦级",
                "runs": 10,
                "parallels": 2,
                "material_cost": 300_000_000,
                "profit": 50_000_000,
                "margin": 16.7,
                "score": 85,
                "iskph": 12_500_000,
                "status": "running",
                "created_at": "2026-06-01 10:00:00",
            }
        ]
        model = ProductionTableModel(plans)
        assert model.rowCount() == 1
        assert model.columnCount() == 8  # 8 列

    def test_header_data(self):
        """表头正确"""
        model = ProductionTableModel([])
        headers = ["产品", "材料成本", "利润", "利润率", "评分", "时均产量", "状态", "创建时间"]
        for i, h in enumerate(headers):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

    def test_data_display(self, qapp):
        """数据展示与格式化正确"""
        plans = [
            {
                "product_type_id": 2001,
                "product_name": "渡鸦级",
                "runs": 10,
                "parallels": 2,
                "material_cost": 300_000_000,
                "profit": 50_000_000,
                "margin": 16.7,
                "score": 85,
                "iskph": 12_500_000,
                "status": "running",
                "created_at": "2026-06-01 10:00:00",
            }
        ]
        model = ProductionTableModel(plans)

        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "渡鸦级"
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "300,000,000"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "50,000,000"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "16.7%"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "85"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "12,500,000"
        assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "运行"  # running → 运行
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "2026-06-01 10:00:00"

    def test_data_fallback_display(self, qapp):
        """字段缺失时的回退显示"""
        plans = [{"product_type_id": 2001, "profit": 0, "margin": 0, "score": 0, "status": "unknown"}]
        model = ProductionTableModel(plans)

        # product_name 缺失 → ID:2001
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "ID:2001"
        # material_cost 缺失 → "-"
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "-"
        # profit = 0 → "0"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "0"
        # margin = 0 → "-" (falsy → "-")
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "-"
        # score = 0 → "-" (falsy → "-")
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "-"
        # iskph 缺失 → "-"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "-"
        # 未知状态 → 原样返回
        assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "unknown"
        # created_at 缺失 → "-"
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "-"

    def test_data_foreground(self, qapp):
        """利润/评分前景色正确"""
        from ui_pyside6 import theme

        # 利润 > 0 绿色, 利润 < 0 红色
        pos = ProductionTableModel([{"profit": 1000, "score": 80}])
        neg = ProductionTableModel([{"profit": -500, "score": 20}])
        assert pos.data(pos.index(0, 2), Qt.ItemDataRole.ForegroundRole).name() == theme.GREEN
        assert neg.data(neg.index(0, 2), Qt.ItemDataRole.ForegroundRole).name() == theme.RED

        # 评分 ≥ 70 → 绿色, < 30 → 红色, 中间 → PRIMARY
        high = ProductionTableModel([{"profit": 0, "score": 85}])
        mid = ProductionTableModel([{"profit": 0, "score": 50}])
        low = ProductionTableModel([{"profit": 0, "score": 15}])
        assert high.data(high.index(0, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.GREEN
        assert mid.data(mid.index(0, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.PRIMARY
        assert low.data(low.index(0, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.RED

    def test_get_plan(self):
        """get_plan 返回正确行数据，越界返回空 dict"""
        plans = [
            {"product_type_id": 2001, "product_name": "渡鸦级"},
            {"product_type_id": 2002, "product_name": "无人机"},
        ]
        model = ProductionTableModel(plans)
        assert model.get_plan(0)["product_type_id"] == 2001
        assert model.get_plan(1)["product_name"] == "无人机"
        assert model.get_plan(99) == {}

    def test_empty_plans(self):
        """空列表构造"""
        model = ProductionTableModel([])
        assert model.rowCount() == 0
        assert model.columnCount() == 8
        assert model.get_plan(0) == {}

    def test_status_labels(self, qapp):
        """所有状态映射正确"""
        status_cases = [
            ("pending", "待排"),
            ("running", "运行"),
            ("done", "完成"),
            ("paused", "暂停"),
            ("cancelled", "cancelled"),  # 未知 → 原样
        ]
        for raw, expected in status_cases:
            plans = [{"product_name": "测试", "runs": 1, "status": raw}]
            model = ProductionTableModel(plans)
            assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == expected


#  ProcurementTableModel
# ══════════════════════════════════════


class TestProcurementTableModel:
    def test_construction(self):
        """可构造"""
        items = [
            {
                "item_name": "三钛合金",
                "type_id": 34,
                "quantity": 50000,
                "hub": "Jita",
                "priority": "high",
                "status": "pending",
                "notes": "",
                "created_at": "2026-01-01",
            }
        ]
        model = ProcurementTableModel(items)
        assert model.rowCount() == 1
        assert model.columnCount() == 9

    def test_header_data(self, qapp):
        """表头"""
        model = ProcurementTableModel([])
        assert model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "物品名"
        assert model.headerData(4, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == "状态"

    def test_data_display(self, qapp):
        """数据展示与标签映射"""
        items = [
            {
                "item_name": "三钛合金",
                "type_id": 34,
                "quantity": 50000,
                "hub": "Jita",
                "priority": "urgent",
                "status": "ordered",
                "notes": "急用",
                "created_at": "2026-06-01",
            }
        ]
        model = ProcurementTableModel(items)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "三钛合金"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "紧急"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "已下单"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "急用"
        assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "2026-06-01"

    def test_priority_foreground(self, qapp):
        """优先级列颜色: urgent→red, high→orange, low→secondary"""
        from ui_pyside6 import theme

        items = [
            {"priority": "urgent", "status": "pending"},
            {"priority": "high", "status": "pending"},
            {"priority": "normal", "status": "pending"},
            {"priority": "low", "status": "pending"},
        ]
        model = ProcurementTableModel(items)
        assert model.data(model.index(0, 3), Qt.ItemDataRole.ForegroundRole).name() == theme.RED
        assert model.data(model.index(1, 3), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_ORANGE
        assert model.data(model.index(2, 3), Qt.ItemDataRole.ForegroundRole) is None  # normal → None
        assert model.data(model.index(3, 3), Qt.ItemDataRole.ForegroundRole).name() == theme.TEXT_SECONDARY

    def test_status_foreground(self, qapp):
        """状态列颜色: received→green, ordered→primary"""
        from ui_pyside6 import theme

        items = [
            {"priority": "normal", "status": "received"},
            {"priority": "normal", "status": "ordered"},
            {"priority": "normal", "status": "pending"},
        ]
        model = ProcurementTableModel(items)
        assert model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.GREEN
        assert model.data(model.index(1, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.PRIMARY
        assert model.data(model.index(2, 4), Qt.ItemDataRole.ForegroundRole) is None

    def test_get_item(self):
        """get_item 返回正确"""
        items = [{"type_id": 34, "item_name": "三钛合金"}]
        model = ProcurementTableModel(items)
        assert model.get_item(0)["type_id"] == 34
        assert model.get_item(9) == {}

    def test_empty_items(self):
        """空列表构造"""
        model = ProcurementTableModel([])
        assert model.rowCount() == 0
        assert model.columnCount() == 9
        assert model.get_item(0) == {}

    def test_fallback_display(self, qapp):
        """字段缺失时的回退显示"""
        items = [
            {
                "type_id": 34,  # 无 item_name
                "quantity": 0,
                # hub key omitted — tests default fallback
                "notes": "",
                "created_at": "",
            }
        ]
        model = ProcurementTableModel(items)
        # item_name 缺失 → ID:{type_id}
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "ID:34"
        # quantity = 0
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "0"
        # hub 空 → Jita (默认值)
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "Jita"
        # 优先级/状态无 → 原样显示（空字符串）
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == ""
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == ""
        # notes 空 → "-"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "-"
        # created_at 空 → "-"
        assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "-"

    def test_unknown_labels(self, qapp):
        """未知优先级/状态保持原样"""
        items = [{"type_id": 34, "priority": "critical", "status": "shipped"}]
        model = ProcurementTableModel(items)
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "critical"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "shipped"

    def test_foreground_none_for_unknown(self, qapp):
        """未知优先级/状态 → ForegroundRole 返回 None"""
        items = [
            {"priority": "unknown_pri", "status": "unknown_st"},
        ]
        model = ProcurementTableModel(items)
        assert model.data(model.index(0, 3), Qt.ItemDataRole.ForegroundRole) is None
        assert model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole) is None
