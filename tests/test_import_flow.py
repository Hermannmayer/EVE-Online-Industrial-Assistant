"""导入纯函数测试 — services/inventory_import.py

覆盖:
  - compute_row_delta: 增量/全量 四象限（有库存/无库存/归零/负 delta）
  - compute_import_diff: 增/减/成本变化/无变化过滤
  - split_clipboard_lines: Tab/空格分隔、星号、千分位、体积字段、表头跳过
  - compute_transfer_rows: 移库计划（clamp/过滤未匹配）
"""

import pytest

from services.inventory_import import (
    compute_import_diff,
    compute_row_delta,
    compute_transfer_rows,
    split_clipboard_lines,
)

pytestmark = pytest.mark.fast

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


# ════════════════════════════════════════════════════════════════
#  split_clipboard_lines
# ════════════════════════════════════════════════════════════════


class TestSplitClipboardLines:
    def test_tab_separated(self):
        """Tab 分隔：名称 + 数量"""
        assert split_clipboard_lines("三钛合金\t1000\n") == [{"name": "三钛合金", "qty": 1000}]

    def test_space_separated(self):
        """多空格分隔（≥2 空格）"""
        assert split_clipboard_lines("三钛合金  1000\n") == [{"name": "三钛合金", "qty": 1000}]

    def test_name_asterisk_stripped(self):
        """物品名尾部 * 去除"""
        assert split_clipboard_lines("麦格纳原子*\t200\n") == [{"name": "麦格纳原子", "qty": 200}]

    def test_thousands_separator(self):
        """数量千分位解析"""
        assert split_clipboard_lines("三钛合金\t1,000\n")[0]["qty"] == 1000

    def test_volume_field_skipped(self):
        """体积字段（m3）不作为数量，回退为 1"""
        result = split_clipboard_lines("恒星骨架\t5,000 m3\t组件\n")
        assert result[0]["qty"] == 1

    def test_header_row_skipped(self):
        """表头行（名称/数量）跳过"""
        raw = "名称\t数量\n三钛合金\t100\n"
        assert split_clipboard_lines(raw) == [{"name": "三钛合金", "qty": 100}]

    def test_empty_and_blank_lines(self):
        """空行跳过，空输入返回空列表"""
        assert split_clipboard_lines("") == []
        assert split_clipboard_lines("\n\n三钛合金\t100\n\n") == [{"name": "三钛合金", "qty": 100}]


# ════════════════════════════════════════════════════════════════
#  compute_transfer_rows
# ════════════════════════════════════════════════════════════════


class TestComputeTransferRows:
    def test_normal_move(self):
        """剪贴板数量在源库额度内 → move_qty=clipboard，不 clamp"""
        rows = [{"type_id": 34, "qty": 50}]
        result = compute_transfer_rows(rows, {34: 80}, {34: 20})
        assert result[0] == {
            "type_id": 34,
            "clipboard_qty": 50,
            "source_avail": 80,
            "target_avail": 20,
            "move_qty": 50,
            "capped": False,
        }

    def test_capped_by_source(self):
        """剪贴板数量超源库现有 → move_qty=源库现有，capped=True"""
        rows = [{"type_id": 34, "qty": 100}]
        result = compute_transfer_rows(rows, {34: 80})
        assert result[0]["move_qty"] == 80
        assert result[0]["capped"] is True

    def test_source_missing(self):
        """源库无该物品 → source_avail=0, move_qty=0"""
        rows = [{"type_id": 35, "qty": 100}]
        result = compute_transfer_rows(rows, {34: 80})
        assert result[0]["source_avail"] == 0
        assert result[0]["move_qty"] == 0
        assert result[0]["capped"] is True

    def test_unmatched_filtered(self):
        """type_id 为 None 的未匹配行被过滤"""
        rows = [{"type_id": 34, "qty": 100}, {"type_id": None, "qty": 999}]
        result = compute_transfer_rows(rows, {34: 80})
        assert len(result) == 1
        assert result[0]["type_id"] == 34

    def test_target_stock_default(self):
        """未传 target_stock 时 target_avail=0"""
        rows = [{"type_id": 34, "qty": 50}]
        result = compute_transfer_rows(rows, {34: 80})
        assert result[0]["target_avail"] == 0
