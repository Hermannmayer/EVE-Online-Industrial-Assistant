"""仓库视图单元测试 — InvTableModel + BlueprintTableModel

测试覆盖:
  - InvTableModel: 机库物品表格模型
  - BlueprintTableModel: 蓝图表格模型
  - 空数据 / 边界情况 / 格式化
"""

import pytest
from PySide6.QtCore import Qt

from ui_qml.models.inventory_helpers import BlueprintTableModel, InvTableModel

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
        """可构造，行数列数正确；列数恒定"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        assert model.rowCount() == 3
        assert model.columnCount() == 10
        empty = InvTableModel([])
        assert empty.rowCount() == 0
        assert empty.columnCount() == 10

    def test_header_data(self, qapp):
        """表头信息正确（已移除「生产中投入」与「拷贝/发明成本」，新增「缺口」「占用资金」「估值可信」）"""
        model = InvTableModel([])
        expected = [
            "图标",
            "名称",
            "库存数量",
            "单个成本记录",
            "规划占用",
            "规划剩余",
            "缺口",
            "占用资金",
            "按卖单总价值",
            "估值可信",
        ]
        for i, h in enumerate(expected):
            actual = model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            assert actual == h, f"列 {i} 表头应为 '{h}', 得到 '{actual}'"

    # (row, col) → 期望 DisplayRole。含 zh/en 回退、千位分隔、零/None → "-" 的边界。
    DISPLAY = {
        (0, 1): "三钛合金",
        (2, 1): "Raven",  # zh_name 为空 → en_name
        (0, 2): "50,000",
        (0, 3): "5.12",
        (2, 3): "-",  # cost_price = 0
        (0, 4): "1,000",
        (2, 4): "0",  # plan_usage = None
        (0, 5): "49,000",
        (2, 5): "1",  # plan_remain = None → 回退库存量
        (0, 6): "-",  # 规划占用 1,000 < 库存 50,000 → 无缺口
        (0, 7): "256,000",  # 5.12 × 50,000
        (2, 7): "-",  # cost_price = 0
        (0, 8): "275,000",  # 50000 × 5.50
        (2, 8): "-",  # 无卖价
        (0, 9): "-",  # 样本没带 price_credible → 三态里的「无价」，不该谎报可信
        (2, 9): "-",
    }

    def test_display_values(self, qapp):
        model = InvTableModel(self.SAMPLE_ITEMS)
        for (row, col), expected in self.DISPLAY.items():
            actual = model.data(model.index(row, col), Qt.ItemDataRole.DisplayRole)
            assert actual == expected, f"({row}, {col}) 期望 {expected!r} 得到 {actual!r}"

    def test_plan_remain_zero_when_equal_to_quantity(self, qapp):
        """规划剩余为 0（库存=规划占用）时显示 '0' 而非回退库存量"""
        rows = [
            {"type_id": 1, "quantity": 100, "cost_price": 0, "plan_usage": 100, "plan_remain": 0, "sell_price": None}
        ]
        model = InvTableModel(rows)
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "0"

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

    def test_gap_and_locked_isk_sort_by_value(self, qapp):
        """「缺口」「占用资金」按**数值**排，不是显示串。

        陷阱：显示串带「缺 N」前缀与千位分隔 —— 字符串序会把「缺 10」排到「缺 9」前、
        把「1,000」排到「500」前。这里特意只用能暴露该差异的数据。
        """
        from ui_qml.theme import registry as theme

        rows = [
            {"type_id": 1, "quantity": 10, "cost_price": 100.0, "plan_usage": 19},  # 缺 9；占用 1,000
            {"type_id": 2, "quantity": 10, "cost_price": 50.0, "plan_usage": 20},  # 缺 10；占用 500
        ]
        gaps = InvTableModel([dict(r) for r in rows])
        gaps.sort(6, Qt.SortOrder.AscendingOrder)
        assert [gaps.item_at(i)["type_id"] for i in range(2)] == [1, 2]
        assert gaps.data(gaps.index(0, 6), Qt.ItemDataRole.DisplayRole) == "缺 9"
        assert gaps.data(gaps.index(0, 6), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_RED

        locked = InvTableModel([dict(r) for r in rows])
        locked.sort(7, Qt.SortOrder.AscendingOrder)
        assert [locked.item_at(i)["type_id"] for i in range(2)] == [2, 1]
        assert locked.data(locked.index(1, 7), Qt.ItemDataRole.DisplayRole) == "1,000"

        no_gap = InvTableModel([{"type_id": 1, "quantity": 100, "plan_usage": 0}])
        assert no_gap.data(no_gap.index(0, 6), Qt.ItemDataRole.DisplayRole) == "-"
        assert no_gap.data(no_gap.index(0, 6), Qt.ItemDataRole.ForegroundRole) is None

    def test_item_at(self, qapp):
        """item_at 取行数据；越界/空模型返回 None"""
        model = InvTableModel(self.SAMPLE_ITEMS)
        item = model.item_at(0)
        assert item["type_id"] == 1001
        assert item["zh_name"] == "三钛合金"
        assert model.item_at(-1) is None
        assert model.item_at(999) is None
        assert InvTableModel([]).item_at(0) is None

    def test_unreliable_price_marked_but_number_still_shown(self, qapp):
        """方案 C：离群卖单价的行**不隐藏**虚高数字，只把「金额 + 估值可信」两列标橙并给 tooltip。

        回归背景：隔热剂 106 件 × 最低卖单价 68,000,000（卖侧仅 4 件挂单）在仓库页
        被读成 72.08 亿 ISK。数字必须留着（用户要看见问题），但要标出它不计入总额。

        文案用「市价不可信」而不是「卖单离群」：判据同时覆盖「卖侧太薄」与「没有买盘」两支，
        写成「卖单离群」会把后者说错。
        """
        from ui_qml.models.inventory_helpers import PRICE_UNRELIABLE_TIP
        from ui_qml.theme import registry as theme

        rows = [
            {
                "type_id": 23165,
                "quantity": 106,
                "cost_price": 29.0,
                "sell_price": 68_000_000.0,
                "price_credible": False,
            },
            {"type_id": 1001, "quantity": 100, "cost_price": 5.0, "sell_price": 5.5, "price_credible": True},
            {"type_id": 34, "quantity": 10, "cost_price": 0, "sell_price": None, "price_credible": None},
        ]
        model = InvTableModel(rows)

        assert model.data(model.index(0, 8), Qt.ItemDataRole.DisplayRole) == "7,208,000,000"
        assert model.data(model.index(0, 9), Qt.ItemDataRole.DisplayRole) == "⚠ 市价不可信"
        assert model.data(model.index(0, 9), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_ORANGE
        assert model.data(model.index(0, 8), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_ORANGE
        assert model.data(model.index(0, 9), Qt.ItemDataRole.ToolTipRole) == PRICE_UNRELIABLE_TIP

        # 可信行不标橙、无 tooltip；无价行是"-"、也不标橙（无价 ≠ 不可信）
        assert model.data(model.index(1, 9), Qt.ItemDataRole.DisplayRole) == "可"
        assert model.data(model.index(1, 9), Qt.ItemDataRole.ForegroundRole) is None
        assert model.data(model.index(1, 9), Qt.ItemDataRole.ToolTipRole) is None
        assert model.data(model.index(2, 9), Qt.ItemDataRole.DisplayRole) == "-"
        assert model.data(model.index(2, 9), Qt.ItemDataRole.ForegroundRole) is None

    def test_sort_by_price_credibility(self, qapp):
        """「估值可信」列可排：降序时**可信行全部排在前面**，不可信/无价行留在后面。"""
        rows = [
            {"type_id": 1, "quantity": 1, "sell_price": 5.0, "price_credible": None},
            {"type_id": 2, "quantity": 1, "sell_price": 5.0, "price_credible": True},
            {"type_id": 3, "quantity": 1, "sell_price": 5.0, "price_credible": False},
            {"type_id": 4, "quantity": 1, "sell_price": 5.0, "price_credible": True},
        ]
        model = InvTableModel(rows)
        model.sort(9, Qt.SortOrder.DescendingOrder)
        order = [model.item_at(i)["type_id"] for i in range(4)]
        # 同键行之间的先后不写死（Python 稳定排序的细节，不是业务契约）：只验分组
        assert set(order[:2]) == {2, 4}, f"可信行必须排在前面，实际 {order}"
        assert set(order[2:]) == {1, 3}, f"不可信/无价行应在后面，实际 {order}"


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
            "runs": 0,  # 原图：v16 迁移后 runs 恒为 0，是否无限看 is_bpo
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
        """可构造，行数列数正确；空数据列数恒定"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        assert model.rowCount() == 2
        assert model.columnCount() == 13
        assert BlueprintTableModel([]).rowCount() == 0

    def test_header_data(self, qapp):
        """表头正确（含「每流程利润」与「状态」）"""
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
            "每流程利润",
            "利润率",
            "状态",
        ]
        for i, h in enumerate(expected):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

    # (row, col) → 期望 DisplayRole。含名称回退、时间/成本格式化与正利润率符号。
    DISPLAY = {
        (0, 1): "渡鸦级蓝图",
        (1, 1): "无人机蓝图 I",  # 无 zh_name → display_name
        (0, 2): "蓝图原图",
        (1, 2): "蓝图拷贝",
        (0, 3): "10",
        (0, 4): "5",
        (0, 5): "渡鸦级",
        (0, 6): "1h 0m",  # 3600s
        (1, 6): "0h 10m",  # 600s
        (0, 7): "无限",  # is_bpo
        (1, 7): "50",  # runs
        (0, 8): "30,000,000 ISK",
        (0, 9): "55,000,000 ISK",
        (0, 10): "25,000,000 ISK",  # 55,000,000 − 30,000,000（每流程）
        (0, 11): "+83.3%",
        (1, 10): "119,500 ISK",  # 120,000 − 500
    }

    def test_display_values(self, qapp):
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        for (row, col), expected in self.DISPLAY.items():
            actual = model.data(model.index(row, col), Qt.ItemDataRole.DisplayRole)
            assert actual == expected, f"({row}, {col}) 期望 {expected!r} 得到 {actual!r}"

    def test_occupied_suffix(self, qapp):
        """被生产计划占用的蓝图类型显示「占用中」后缀"""
        rows = [dict(r) for r in self.SAMPLE_ROWS]
        rows[1]["occupied"] = True
        model = BlueprintTableModel(rows)
        idx = model.index(1, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "蓝图拷贝（占用中）"

    def test_time_zero_returns_dash(self, qapp):
        """base_time=0 返回横线"""
        rows = [{"blueprint_type_id": 9999, "base_time": 0}]
        model = BlueprintTableModel(rows)
        idx = model.index(0, 6)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_runs_zero_copy_not_infinite(self, qapp):
        """拷贝的 runs=0 是「耗尽」而非「无限」——原图身份只认 is_bpo"""
        rows = [{**self.SAMPLE_ROWS[1], "runs": 0}]
        model = BlueprintTableModel(rows)  # 必须持有引用：临时模型被 GC 后 idx 会解引用悬空指针
        idx = model.index(0, 7)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "0"

    def test_material_cost_none(self, qapp):
        """无材料成本时显示横线"""
        rows = [{"blueprint_type_id": 9999}]
        model = BlueprintTableModel(rows)
        idx = model.index(0, 8)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "-"

    def test_run_profit_none_and_foreground(self, qapp):
        """任一侧缺失 → 每流程利润显示横线且不染色；正绿负红"""
        from ui_qml.theme import registry as theme

        missing = BlueprintTableModel([{"blueprint_type_id": 9999, "revenue": 100.0}])
        assert missing.data(missing.index(0, 10), Qt.ItemDataRole.DisplayRole) == "-"
        assert missing.data(missing.index(0, 10), Qt.ItemDataRole.ForegroundRole) is None

        loss = BlueprintTableModel([{"blueprint_type_id": 9999, "revenue": 100.0, "material_cost": 250.0}])
        assert loss.data(loss.index(0, 10), Qt.ItemDataRole.DisplayRole) == "-150 ISK"
        assert loss.data(loss.index(0, 10), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_RED

        gain = BlueprintTableModel(self.SAMPLE_ROWS)
        assert gain.data(gain.index(0, 10), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_GREEN

    def test_margin_non_positive_and_none(self, qapp):
        """负利润率带符号；无利润率显示横线"""
        model = BlueprintTableModel([{"blueprint_type_id": 9999, "margin": -15.5}])
        assert model.data(model.index(0, 11), Qt.ItemDataRole.DisplayRole) == "-15.5%"
        model2 = BlueprintTableModel([{"blueprint_type_id": 9999}])
        assert model2.data(model2.index(0, 11), Qt.ItemDataRole.DisplayRole) == "-"

    def test_margin_foreground(self, qapp):
        """正利润率绿色、负利润率红色、无利润率 None"""
        from ui_qml.theme import registry as theme

        pos = BlueprintTableModel(self.SAMPLE_ROWS)
        assert pos.data(pos.index(0, 11), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_GREEN
        neg = BlueprintTableModel([{"blueprint_type_id": 9999, "margin": -10.0}])
        assert neg.data(neg.index(0, 11), Qt.ItemDataRole.ForegroundRole).name() == theme.ACCENT_RED
        none = BlueprintTableModel([{"blueprint_type_id": 9999}])
        assert none.data(none.index(0, 11), Qt.ItemDataRole.ForegroundRole) is None

    def test_row_at(self, qapp):
        """row_at 取行数据；越界返回 None"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        assert model.row_at(0)["blueprint_type_id"] == 3001
        assert model.row_at(-1) is None
        assert model.row_at(999) is None

    def test_sort_by_me_level(self, qapp):
        """按材料等级排序"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        model.sort(3, Qt.SortOrder.AscendingOrder)
        assert model.row_at(0)["me_level"] == 0  # 无人机蓝图

    def test_sort_by_margin(self, qapp):
        """按利润率升序"""
        model = BlueprintTableModel(self.SAMPLE_ROWS)
        model.sort(11, Qt.SortOrder.AscendingOrder)
        margins = [r["margin"] for r in model._rows if r.get("margin") is not None]
        assert margins == sorted(margins)

    def test_sort_by_run_profit(self, qapp):
        """「每流程利润」按**数值**排（显示串带千位分隔：字符串序会把 1,000 排到 900 前）"""
        rows = [
            {"blueprint_type_id": 1, "revenue": 1900.0, "material_cost": 1000.0},  # 900 ISK
            {"blueprint_type_id": 2, "revenue": 2000.0, "material_cost": 1000.0},  # 1,000 ISK
        ]
        model = BlueprintTableModel(rows)
        model.sort(10, Qt.SortOrder.AscendingOrder)
        assert [model.row_at(i)["blueprint_type_id"] for i in range(2)] == [1, 2]
        # 缺任一侧的行按 -inf 参与排序（升序排最前，与「利润率」列同口径）
        mixed = BlueprintTableModel([*[dict(r) for r in rows], {"blueprint_type_id": 3, "revenue": 100.0}])
        mixed.sort(10, Qt.SortOrder.AscendingOrder)
        assert [mixed.row_at(i)["blueprint_type_id"] for i in range(3)] == [3, 1, 2]


# ══════════════════════════════════════
#  BatchCostPriceDialog
# ══════════════════════════════════════


class TestBatchCostPriceDialog:
    """批量设置成本价对话框 — 价格来源切换 / 倍率 / 手动输入（阶段 4b 已迁 QML）。

    断言从 Widgets 控件（`_discount` / `_manual` / `_source`）改成桥的属性 ——
    行为契约不变，所以下面几条断言值都保持原样。
    """

    def test_defaults(self, qapp):
        """默认卖价 + 倍率 1.0（跟随生产规划页）；贸易中心可选、初值跟随「材料价格来源」。"""
        from ui_qml.bridge.hangar_dialogs import BatchCostPriceQmlDialog

        dlg = BatchCostPriceQmlDialog()
        try:
            assert dlg.price_type() == "sell"
            assert dlg.discount() == 1.0  # 不再是硬编码 0.9
            # 范围与生产规划页工具栏的倍率一致（可溢价，不只是打折）
            assert dlg.bridge.multiplierMax == 10.0
            # 回归：来源项早先写死「吉他卖价/买价/均价」，整个窗口钉死在吉他上，
            # 用户报「没法设置其他贸易中心的价格」。现在贸易中心由下拉选。
            assert dlg.bridge.hubs[0] == "Jita"
            assert dlg.hub_name() == dlg.bridge.hubs[dlg.bridge.hubIndex]
            dlg.bridge.setHubIndex(1)
            assert dlg.hub_name() == "Amarr"
        finally:
            dlg.deleteLater()

    def test_mult_follows_settings_and_persists(self, qapp):
        """初值跟随生产规划页的材料倍率；确认后写回同一字段。"""
        from services.user_settings import get_material_price_mult, set_material_price_mult
        from ui_qml.bridge.hangar_dialogs import BatchCostPriceQmlDialog

        set_material_price_mult(1.25)
        dlg = BatchCostPriceQmlDialog()
        try:
            assert dlg.discount() == pytest.approx(1.25)

            dlg.bridge.setMultiplier(0.8)
            dlg.bridge.accept()  # 确认才写回（改旋钮不写盘）
            assert get_material_price_mult() == pytest.approx(0.8)
        finally:
            dlg.deleteLater()

    def test_switch_to_manual(self, qapp):
        """切到手动输入：倍率行隐藏、手动价格行显示"""
        from ui_qml.bridge.hangar_dialogs import BatchCostPriceQmlDialog

        dlg = BatchCostPriceQmlDialog()
        try:
            dlg.bridge.setSourceIndex(3)
            assert dlg.price_type() == "manual"
            assert dlg.bridge.isManual is True
        finally:
            dlg.deleteLater()


# ══════════════════════════════════════
#  剪贴板导入 — 异类行过滤提示
# ══════════════════════════════════════


class TestImportFilteredNote:
    """剪贴板里混入另一类物品时，预览框统计栏提示已过滤行数。"""

    def test_material_review_note(self, qapp):
        """材料导入预览：有过滤则提示行数，无过滤则不加提示"""
        from ui_qml.bridge.review_bridge import ImportReviewQmlDialog

        with_note = ImportReviewQmlDialog([], "测试机库", 1, filtered_note=3)
        try:
            assert "[已过滤 3 行蓝图]" in with_note.bridge.summaryText
        finally:
            with_note.deleteLater()

        without = ImportReviewQmlDialog([], "测试机库", 1)
        try:
            assert "已过滤" not in without.bridge.summaryText
        finally:
            without.deleteLater()

    def test_blueprint_review_note(self, qapp):
        """蓝图导入预览：提示被过滤的材料行数（QML 版断言桥的汇总文案）"""
        from ui_qml.bridge.blueprint_import_bridge import BlueprintImportReviewQmlDialog

        dlg = BlueprintImportReviewQmlDialog([], "测试机库", filtered_note=2)
        try:
            assert "[已过滤 2 行材料]" in dlg.bridge.summaryText
        finally:
            dlg.deleteLater()
