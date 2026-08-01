"""导入纯函数测试 — services/inventory_import.py

覆盖:
  - compute_row_delta: 增量/全量 四象限（有库存/无库存/归零/负 delta）
  - compute_import_diff: 增/减/成本变化/无变化过滤
"""

from services.inventory_import import compute_import_diff, compute_row_delta

# ════════════════════════════════════════════════════════════════
#  compute_row_delta
# ════════════════════════════════════════════════════════════════


class TestComputeRowDelta:
    def test_incremental_with_stock(self):
        """增量模式：delta=qty，final=current+qty"""
        assert compute_row_delta("incremental", 100, 50) == (100, 150)

    def test_incremental_no_stock(self):
        """增量模式：机库无该物品"""
        assert compute_row_delta("incremental", 100, 0) == (100, 100)

    def test_full_with_stock(self):
        """全量模式：final=qty，delta=qty-current"""
        assert compute_row_delta("full", 100, 50) == (50, 100)

    def test_full_no_stock(self):
        """全量模式：机库无该物品"""
        assert compute_row_delta("full", 100, 0) == (100, 100)

    def test_full_zero_target_removes(self):
        """全量归零：delta 为负（qty-current）"""
        assert compute_row_delta("full", 0, 80) == (-80, 0)

    def test_incremental_negative_delta(self):
        """增量模式负 delta"""
        assert compute_row_delta("incremental", -30, 50) == (-30, 20)

    def test_full_equal_current_no_change(self):
        """全量模式与现有一致时 delta=0"""
        assert compute_row_delta("full", 80, 80) == (0, 80)


# ════════════════════════════════════════════════════════════════
#  compute_import_diff
# ════════════════════════════════════════════════════════════════


class TestComputeImportDiff:
    def test_increase_only(self):
        before = {1001: (100, 5.0)}
        after = {1001: (150, 5.0)}
        names = {1001: "三钛合金"}
        result = compute_import_diff(before, after, names, [1001])
        assert result == [
            {
                "type_id": 1001,
                "name": "三钛合金",
                "qty_before": 100,
                "qty_after": 150,
                "cost_before": 5.0,
                "cost_after": 5.0,
                "qty_delta": 50,
                "cost_delta": 0.0,
            }
        ]

    def test_decrease_and_removal(self):
        """全量归零删除：行从库存消失"""
        before = {1001: (100, 5.0)}
        after = {}
        names = {1001: "三钛合金"}
        result = compute_import_diff(before, after, names, [1001])
        assert len(result) == 1
        assert result[0]["qty_delta"] == -100
        assert result[0]["qty_after"] == 0
        assert result[0]["cost_after"] == 0.0

    def test_cost_change_only(self):
        """仅成本变化也计入"""
        before = {1001: (100, 5.0)}
        after = {1001: (100, 6.0)}
        names = {1001: "三钛合金"}
        result = compute_import_diff(before, after, names, [1001])
        assert len(result) == 1
        assert result[0]["cost_delta"] == 1.0
        assert result[0]["qty_delta"] == 0

    def test_no_change_filtered(self):
        """数量与成本均未变化 → 不返回"""
        before = {1001: (100, 5.0)}
        after = {1001: (100, 5.0)}
        names = {1001: "三钛合金"}
        assert compute_import_diff(before, after, names, [1001]) == []

    def test_new_item_treated_as_zero_before(self):
        """新物品：before 缺省按 0 处理"""
        before = {}
        after = {1001: (50, 3.0)}
        names = {1001: "三钛合金"}
        result = compute_import_diff(before, after, names, [1001])
        assert result[0]["qty_before"] == 0
        assert result[0]["qty_delta"] == 50

    def test_multi_item_partial_change(self):
        """多物品：只返回发生变化的行"""
        before = {1001: (100, 5.0), 1002: (200, 8.0)}
        after = {1001: (100, 5.0), 1002: (250, 8.0)}
        names = {1001: "三钛合金", 1002: "类银超金属"}
        result = compute_import_diff(before, after, names, [1001, 1002])
        assert len(result) == 1
        assert result[0]["type_id"] == 1002
