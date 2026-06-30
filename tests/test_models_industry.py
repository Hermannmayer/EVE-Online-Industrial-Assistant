"""工业制造 Table Model 单元测试 — 生产执行跟踪 + 代采购表重点覆盖

测试覆盖:
  - ProductionTableModel: 生产执行跟踪表（新增模型）
  - ProcurementTableModel: 代采购表（边界与回退场景）

配色铁律遵守检查: 所有颜色均从 ui_pyside6.theme 导入
"""

from PySide6.QtCore import Qt

from ui_pyside6.models.industry_models import (
    ProcurementTableModel,
    ProductionTableModel,
)

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
        assert model.columnCount() == 10  # 10 列

    def test_header_data(self):
        """表头正确"""
        model = ProductionTableModel([])
        headers = ["产品", "批次", "并行", "材料成本", "利润", "利润率", "评分", "时均/h", "状态", "创建时间"]
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
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "10"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "2"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "300,000,000"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "50,000,000"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "16.7%"
        assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "85"
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "12,500,000"
        assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == "运行"  # running → 运行
        assert model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole) == "2026-06-01 10:00:00"

    def test_data_fallback_display(self, qapp):
        """字段缺失时的回退显示"""
        plans = [{"product_type_id": 2001, "profit": 0, "margin": 0, "score": 0, "status": "unknown"}]
        model = ProductionTableModel(plans)

        # product_name 缺失 → ID:2001
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "ID:2001"
        # material_cost 缺失 → "-"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "-"
        # profit = 0 → "0"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "0"
        # margin = 0 → "-" (falsy → "-")
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "-"
        # score = 0 → "-" (falsy → "-")
        assert model.data(model.index(0, 6), Qt.ItemDataRole.DisplayRole) == "-"
        # iskph 缺失 → "-"
        assert model.data(model.index(0, 7), Qt.ItemDataRole.DisplayRole) == "-"
        # 未知状态 → 原样返回
        assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == "unknown"
        # created_at 缺失 → "-"
        assert model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole) == "-"

    def test_data_foreground(self, qapp):
        """利润/评分前景色正确"""
        from ui_pyside6 import theme

        # 利润 > 0 绿色, 利润 < 0 红色
        pos = ProductionTableModel([{"profit": 1000, "score": 80}])
        neg = ProductionTableModel([{"profit": -500, "score": 20}])
        assert pos.data(pos.index(0, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.GREEN
        assert neg.data(neg.index(0, 4), Qt.ItemDataRole.ForegroundRole).name() == theme.RED

        # 评分 ≥ 70 → 绿色, < 30 → 红色, 中间 → PRIMARY
        high = ProductionTableModel([{"profit": 0, "score": 85}])
        mid = ProductionTableModel([{"profit": 0, "score": 50}])
        low = ProductionTableModel([{"profit": 0, "score": 15}])
        assert high.data(high.index(0, 6), Qt.ItemDataRole.ForegroundRole).name() == theme.GREEN
        assert mid.data(mid.index(0, 6), Qt.ItemDataRole.ForegroundRole).name() == theme.PRIMARY
        assert low.data(low.index(0, 6), Qt.ItemDataRole.ForegroundRole).name() == theme.RED

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
        assert model.columnCount() == 10
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
            assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == expected


# ══════════════════════════════════════
#  ProcurementTableModel — 边界补充
# ══════════════════════════════════════


class TestProcurementTableModel:
    """ProcurementTableModel — 代采购表边界与回退"""

    def test_empty_items(self):
        """空列表构造"""
        model = ProcurementTableModel([])
        assert model.rowCount() == 0
        assert model.columnCount() == 7
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
