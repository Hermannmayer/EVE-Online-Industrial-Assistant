"""仓库视图单元测试 — InvTableModel + BlueprintTableModel

测试覆盖:
  - InvTableModel: 机库物品表格模型
  - BlueprintTableModel: 蓝图表格模型
  - 空数据 / 边界情况 / 格式化
"""

import pytest
from PySide6.QtCore import Qt

from ui_pyside6.views.inventory.inventory_helpers import BlueprintTableModel, InvTableModel

pytestmark = pytest.mark.ui

# ══════════════════════════════════════
#  InvTableModel
# ══════════════════════════════════════


class TestInvTableModel:
    """机库物品表格模型"""

    SAMPLE_ITEMS = [
        {
            "type_id": 1001,
            "zh_name": "三钛合金",
            "en_name": "Tritanium",
            "quantity": 50000,
            "cost_price": 5.12,
            "plan_usage": 1000,
            "plan_active": 500,
            "plan_remain": 49000,
            "sell_price": 5.50,
        },
        {
            "type_id": 1002,
            "zh_name": "类银超金属",
            "en_name": "Pyerite",
            "quantity": 10000,
            "cost_price": 10.50,
            "plan_usage": 0,
            "plan_active": 0,
            "plan_remain": 10000,
            "sell_price": 11.00,
        },
        {
            "type_id": 2001,
            "zh_name": "",
            "en_name": "Raven",
            "quantity": 1,
            "cost_price": 0,
            "plan_usage": None,
            "plan_active": None,
            "plan_remain": None,
            "sell_price": None,
        },
    ]

    def test_construction(self, qapp):
        """可构造，行数列数正确"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        assert model.rowCount() == 3
        assert model.columnCount() == 8

    def test_empty_rows(self, qapp):
        """空数据构造"""
        model = InvTableModel([])
        assert model.rowCount() == 0
        assert model.columnCount() == 8

    def test_header_data(self, qapp):
        """表头信息正确（已移除「生产中投入」）"""
        model = InvTableModel([])
        expected = ["图标", "名称", "库存数量", "单个成本记录", "规划占用", "规划剩余", "按卖单总价值", "拷贝/发明成本"]
        for i, h in enumerate(expected):
            actual = model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            assert actual == h, f"列 {i} 表头应为 '{h}', 得到 '{actual}'"

    def test_name_display_zh(self, qapp):
        """中文名称优先显示"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 1)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "三钛合金"

    def test_name_display_en_fallback(self, qapp):
        """无中文名时显示英文名"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(2, 1)  # zh_name is ""
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "Raven"

    def test_quantity_format(self, qapp):
        """数量格式化为千位分隔"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "50,000"

    def test_cost_price_format(self, qapp):
        """成本价格保留两位小数"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 3)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "5.12"

    def test_cost_price_zero_returns_dash(self, qapp):
        """无成本时显示横线"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(2, 3)  # cost_price = 0
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_plan_usage_format(self, qapp):
        """规划占用格式化"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 4)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "1,000"

    def test_plan_usage_none(self, qapp):
        """规划占用为 None 时显示 '0'"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(2, 4)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "0"

    def test_plan_remain_with_value(self, qapp):
        """规划剩余正常显示"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 5)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "49,000"

    def test_plan_remain_fallback_to_quantity(self, qapp):
        """规划剩余为 None 时回退为库存数量"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(2, 5)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "1"

    def test_plan_remain_zero_when_equal_to_quantity(self, qapp):
        """规划剩余为 0（库存=规划占用）时显示 '0' 而非回退库存量"""
        rows = [
            {"type_id": 1, "quantity": 100, "cost_price": 0, "plan_usage": 100, "plan_remain": 0, "sell_price": None}
        ]
        model = InvTableModel(rows)
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "0"

    def test_total_value_with_sell_price(self, qapp):
        """总价值 = 库存数 × 卖单价"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 6)
        expected = f"{50000 * 5.50:,.0f}"
        assert idx.data(Qt.ItemDataRole.DisplayRole) == expected

    def test_total_value_no_sell_price(self, qapp):
        """无卖价时显示横线"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(2, 6)  # sell_price is None
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_name_display_name_priority(self, qapp):
        """display_name 优先（terminology override 等场景 zh/en 为空）"""
        rows = [
            {
                "type_id": 34,
                "zh_name": "",
                "en_name": "",
                "display_name": "三钛合金",
                "quantity": 1,
                "cost_price": 0,
                "plan_usage": None,
                "plan_active": None,
                "plan_remain": None,
                "sell_price": None,
            }
        ]
        model = InvTableModel(rows)
        idx = model.index(0, 1)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "三钛合金"

    def test_tooltip_plan_usage(self, qapp):
        """规划占用列提示待启动计划预留"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        assert model.data(model.index(0, 4), Qt.ItemDataRole.ToolTipRole) == "待启动计划预留"

    def test_icon_size_hint(self, qapp):
        """图标列返回固定 SizeHint（与工业制造一致，约束列宽）"""
        from PySide6.QtCore import QSize

        model = InvTableModel(self.SAMPLE_ITEMS)
        hint = model.data(model.index(0, 0), Qt.ItemDataRole.SizeHintRole)
        assert hint == QSize(36, 36)

    def test_sort_quantity(self, qapp):
        """按库存数量降序排序"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        model.sort(2, Qt.SortOrder.DescendingOrder)
        assert model.item_at(0)["quantity"] == 50000

    def test_sort_name(self, qapp):
        """按名称升序排序"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        model.sort(1, Qt.SortOrder.AscendingOrder)
        names = [model.item_at(i)["zh_name"] or model.item_at(i)["en_name"] for i in range(model.rowCount())]
        assert names == sorted(names)

    def test_text_alignment_numbers(self, qapp):
        """数量列为右对齐"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 2)
        align = idx.data(Qt.ItemDataRole.TextAlignmentRole)
        assert align == (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def test_icon_column_returns_none_when_no_file(self, qapp):
        """无图标文件时 DecorationRole 返回 None"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        idx = model.index(0, 0)
        assert idx.data(Qt.ItemDataRole.DecorationRole) is None

    def test_item_at_valid(self, qapp):
        """item_at 返回指定行数据"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        item = model.item_at(0)
        assert item["type_id"] == 1001
        assert item["zh_name"] == "三钛合金"

    def test_item_at_invalid(self, qapp):
        """item_at 越界返回 None"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        assert model.item_at(-1) is None
        assert model.item_at(999) is None

    def test_item_at_empty(self, qapp):
        """空模型 item_at 返回 None"""
        model = InvTableModel([])
        assert model.item_at(0) is None

    def test_set_rows_replaces_data(self, qapp):
        """set_model 替代旧数据"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        assert model.rowCount() == 3
        new_items = [self.SAMPLE_ITEMS[0]]
        model2 = InvTableModel(new_items)
        assert model2.rowCount() == 1

    # ── 空数据 / 缺字段 ──

    def test_name_fallback_to_en_when_zh_missing(self, qapp):
        """zh_name 缺失时使用 en_name"""
        rows = [{"type_id": 9999, "en_name": "TestItem", "quantity": 1, "cost_price": 0, "sell_price": None}]
        model = InvTableModel(rows)
        name = model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole)
        assert name == "TestItem"


# ══════════════════════════════════════
#  BlueprintTableModel
# ══════════════════════════════════════


class TestBlueprintTableModel:
    """蓝图表格模型"""

    SAMPLE_ROWS = [
        {
            "blueprint_type_id": 3001,
            "zh_name": "渡鸦级蓝图",
            "display_name": None,
            "is_bpo": True,
            "me_level": 10,
            "te_level": 5,
            "product_name": "渡鸦级",
            "base_time": 3600,
            "runs": -1,
            "material_cost": 30000000.0,
            "revenue": 55000000.0,
            "margin": 83.33,
            "product_type_id": 2001,
            "product_quantity": 1,
        },
        {
            "blueprint_type_id": 3002,
            "zh_name": "",
            "display_name": "无人机蓝图 I",
            "is_bpo": False,
            "me_level": 0,
            "te_level": 0,
            "product_name": "无人机",
            "base_time": 600,
            "runs": 50,
            "material_cost": 500.0,
            "revenue": 120000.0,
            "margin": 23900.0,
            "product_type_id": 2002,
            "product_quantity": 1,
        },
    ]

    def test_construction(self, qapp):
        """可构造，行数列数正确"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        assert model.rowCount() == 2
        assert model.columnCount() == 11

    def test_header_data(self, qapp):
        """表头正确"""
        model = BlueprintTableModel([])
        expected = [
            "图标",
            "名称",
            "类型",
            "材料等级",
            "时间等级",
            "产物名称",
            "制造时间",
            "流程数量",
            "材料成本",
            "销售收入",
            "利润率",
        ]
        for i, h in enumerate(expected):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

    def test_empty_rows(self, qapp):
        """空数据构造"""
        model = BlueprintTableModel([])
        assert model.rowCount() == 0

    def test_name_zh(self, qapp):
        """中文名优先"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 1)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "渡鸦级蓝图"

    def test_name_display_fallback(self, qapp):
        """无 zh_name 时用 display_name"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(1, 1)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "无人机蓝图 I"

    def test_type_bpo(self, qapp):
        """原图类型"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "蓝图原图"

    def test_type_bpc(self, qapp):
        """拷贝类型"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(1, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "蓝图拷贝"

    def test_occupied_suffix(self, qapp):
        """被生产计划占用的蓝图类型显示「占用中」后缀"""
        rows = [dict(r) for r in self.SAMPLE_ROWS]
        rows[1]["occupied"] = True
        model = BlueprintTableModel(rows)
        idx = model.index(1, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "蓝图拷贝（占用中）"

    def test_occupied_foreground_orange(self, qapp):
        """占用中的类型列用前景色高亮（非 None）"""
        from PySide6.QtGui import QColor

        rows = [dict(r) for r in self.SAMPLE_ROWS]
        rows[1]["occupied"] = True
        model = BlueprintTableModel(rows)
        idx = model.index(1, 2)
        color = idx.data(Qt.ItemDataRole.ForegroundRole)
        assert isinstance(color, QColor)
        assert color.name().startswith("#")

    def test_unoccupied_no_suffix(self, qapp):
        """未占用蓝图不显示后缀（兼容旧数据）"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "蓝图原图"

    def test_me_level(self, qapp):
        """材料等级"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 3)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "10"

    def test_te_level(self, qapp):
        """时间等级"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 4)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "5"

    def test_product_name(self, qapp):
        """产物名称"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 5)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "渡鸦级"

    def test_time_format_hours(self, qapp):
        """制造时间格式: 1h 0m"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 6)  # 3600s = 1h
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "1h 0m"

    def test_time_format_minutes(self, qapp):
        """制造时间格式: 0h 10m"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(1, 6)  # 600s = 10m
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "0h 10m"

    def test_time_zero_returns_dash(self, qapp):
        """base_time=0 返回横线"""
        rows = [{"blueprint_type_id": 9999, "base_time": 0}]
        model = BlueprintTableModel(rows)
        idx = model.index(0, 6)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_runs_infinite(self, qapp):
        """流程数量 -1 显示 '无限'"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 7)  # runs = -1
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "无限"

    def test_runs_limited(self, qapp):
        """流程数量有限"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(1, 7)  # runs = 50
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "50"

    def test_material_cost_format(self, qapp):
        """材料成本带千位分隔和 ISK 单位"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 8)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "30,000,000 ISK"

    def test_material_cost_none(self, qapp):
        """无材料成本时显示横线"""
        rows = [{"blueprint_type_id": 9999}]
        model = BlueprintTableModel(rows)
        idx = model.index(0, 8)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_revenue_format(self, qapp):
        """销售收入格式化"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 9)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "55,000,000 ISK"

    def test_margin_positive(self, qapp):
        """正利润率显示带符号百分比"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 10)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "+83.3%"

    def test_margin_negative(self, qapp):
        """负利润率"""
        rows = [{"blueprint_type_id": 9999, "margin": -15.5}]
        model = BlueprintTableModel(rows)
        idx = model.index(0, 10)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-15.5%"

    def test_margin_none(self, qapp):
        """无利润率显示横线"""
        rows = [{"blueprint_type_id": 9999}]
        model = BlueprintTableModel(rows)
        idx = model.index(0, 10)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_margin_foreground_positive_green(self, qapp):
        """正利润率绿色"""
        from ui_pyside6 import theme

        model = BlueprintTableModel(self.SAMPLE_ROWS)
        color = model.data(model.index(0, 10), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.ACCENT_GREEN

    def test_margin_foreground_negative_red(self, qapp):
        """负利润率红色"""
        rows = [{"blueprint_type_id": 9999, "margin": -10.0}]
        model = BlueprintTableModel(rows)
        color = model.data(model.index(0, 10), Qt.ItemDataRole.ForegroundRole)
        from ui_pyside6 import theme

        assert color.name() == theme.ACCENT_RED

    def test_margin_foreground_none(self, qapp):
        """无利润率返回 None"""
        rows = [{"blueprint_type_id": 9999}]
        model = BlueprintTableModel(rows)
        assert model.data(model.index(0, 10), Qt.ItemDataRole.ForegroundRole) is None

    def test_text_alignment(self, qapp):
        """数据列右对齐"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        idx = model.index(0, 3)
        align = idx.data(Qt.ItemDataRole.TextAlignmentRole)
        assert align == (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def test_row_at_valid(self, qapp):
        """row_at 返回正确行数据"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        row = model.row_at(0)
        assert row["blueprint_type_id"] == 3001

    def test_row_at_invalid(self, qapp):
        """row_at 越界返回 None"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        assert model.row_at(-1) is None
        assert model.row_at(999) is None

    def test_sort_by_me_level(self, qapp):
        """按材料等级排序"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        model.sort(3, Qt.SortOrder.AscendingOrder)
        assert model.row_at(0)["me_level"] == 0  # 无人机蓝图

    def test_sort_by_margin(self, qapp):
        """按利润率降序"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        model.sort(10, Qt.SortOrder.AscendingOrder)
        margins = [r["margin"] for r in model._rows if r.get("margin") is not None]
        assert margins == sorted(margins), "应为升序排列"

    def test_sort_by_name(self, qapp):
        """按名称排序"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        model.sort(1, Qt.SortOrder.AscendingOrder)
        name0 = model.row_at(0).get("zh_name") or model.row_at(0).get("display_name", "")
        name1 = model.row_at(1).get("zh_name") or model.row_at(1).get("display_name", "")
        assert name0 <= name1  # 按字典序


# ══════════════════════════════════════
#  BatchCostPriceDialog
# ══════════════════════════════════════


class TestBatchCostPriceDialog:
    """批量设置成本价对话框 — 价格来源切换 / 折扣 / 手动输入"""

    def test_defaults(self, qapp):
        """默认吉他卖价 + 9 折，折扣可见、手动隐藏"""
        from ui_pyside6.views.inventory.hangar_tab import BatchCostPriceDialog

        dlg = BatchCostPriceDialog()
        assert dlg.price_type() == "sell"
        assert dlg.discount() == 0.9
        assert not dlg._discount.isHidden()
        assert dlg._manual.isHidden()

    def test_switch_to_manual(self, qapp):
        """切到手动输入：折扣隐藏、手动价格可见"""
        from ui_pyside6.views.inventory.hangar_tab import BatchCostPriceDialog

        dlg = BatchCostPriceDialog()
        dlg._source.setCurrentIndex(3)
        assert dlg.price_type() == "manual"
        assert dlg._discount.isHidden()
        assert not dlg._manual.isHidden()

    def test_discount_roundtrip(self, qapp):
        from ui_pyside6.views.inventory.hangar_tab import BatchCostPriceDialog

        dlg = BatchCostPriceDialog()
        dlg._discount.setValue(0.8)
        assert dlg.discount() == 0.8

    def test_manual_price_roundtrip(self, qapp):
        from ui_pyside6.views.inventory.hangar_tab import BatchCostPriceDialog

        dlg = BatchCostPriceDialog()
        dlg._source.setCurrentIndex(3)
        dlg._manual.setValue(1234.56)
        assert dlg.manual_price() == 1234.56
