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
        assert model.columnCount() == 20

    def test_header_data(self, qapp):
        """表头正确"""
        model = PlanTableModel([])
        headers = [
            "☐",
            "图标",
            "产品",
            "备注",
            "批次",
            "并行",
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
                "batch": 5,
                "parallels": 2,
                "me_level": 10,
                "te_level": 20,
                "profit": 5_000_000,
                "status": "in_progress",
            }
        ]
        model = PlanTableModel(plans)
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "渡鸦级"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "5"
        assert model.data(model.index(0, 17), Qt.ItemDataRole.DisplayRole) == "5,000,000"
        assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == "生产中"

    def test_status_label_mapping(self, qapp):
        """状态映射: pending→待生产, in_progress→生产中, completed→已完成"""
        plans = [
            {"product_type_id": 1, "batch": 1, "parallels": 1, "me_level": 0, "te_level": 0, "status": "pending"},
            {"product_type_id": 2, "batch": 1, "parallels": 1, "me_level": 0, "te_level": 0, "status": "in_progress"},
            {"product_type_id": 3, "batch": 1, "parallels": 1, "me_level": 0, "te_level": 0, "status": "completed"},
        ]
        model = PlanTableModel(plans)
        assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == "待生产"
        assert model.data(model.index(1, 8), Qt.ItemDataRole.DisplayRole) == "生产中"
        assert model.data(model.index(2, 8), Qt.ItemDataRole.DisplayRole) == "已完成"

    def test_get_plan(self):
        """get_plan 返回正确"""
        plans = [{"product_type_id": 2001}]
        model = PlanTableModel(plans)
        assert model.get_plan(0)["product_type_id"] == 2001
        assert model.get_plan(99) == {}


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
