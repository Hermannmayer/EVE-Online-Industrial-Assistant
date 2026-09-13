"""蓝图同步纯逻辑测试 —— 属性归一 / 组内配对 / 目标张数调整。

覆盖「流程数变化不得删旧插新」「原图归一是不动点」「quantity>1 不整行误删」
这三条与数据丢失直接相关的契约。
"""

import pytest

from domain.blueprint_sync import normalize_clipboard_attr, plan_group_sync, target_units

pytestmark = pytest.mark.fast


def _row(row_id: int, runs: int = 1004, quantity: int = 1, notes: str = "") -> dict:
    return {"id": row_id, "runs": runs, "quantity": quantity, "notes": notes}


class TestNormalizeClipboardAttr:
    @pytest.mark.parametrize(
        ("text", "runs", "is_bpo", "out_runs"),
        [
            ("原图", -1, True, 0),
            ("原本", -1, True, 0),
            ("Original", -1, True, 0),
            ("Blueprint Original", -1, True, 0),
            ("", -1, True, 0),  # 判词失配时由负数兜底
            ("拷贝", 10, False, 10),
            ("Copy", 10, False, 10),
            ("", 10, False, 10),
            ("原图", 10, True, 0),  # 原图一律归 0（不变量：is_bpo=1 ⇒ runs=0）
        ],
    )
    def test_normalize(self, text, runs, is_bpo, out_runs):
        assert normalize_clipboard_attr(text, runs) == (is_bpo, out_runs)

    def test_negative_runs_never_leaks(self):
        """归一是 0 值不动点：同一份剪贴板再解析一次结果不变。"""
        assert normalize_clipboard_attr("原图", -1) == normalize_clipboard_attr("原图", 0) == (True, 0)


class TestPlanGroupSync:
    def test_same_runs_is_noop(self):
        """流程数未变 → 零操作（重复粘贴的幂等路径）。"""
        assert plan_group_sync([_row(1)], [1004]) == []

    def test_noop_ignores_row_order_differences_only(self):
        """同规格多行、流程数各异：按同值配对，不产生无谓改写。"""
        rows = [_row(10, runs=2996), _row(11, runs=1004)]
        assert plan_group_sync(rows, [1004, 2996]) == []

    def test_runs_change_updates_in_place_and_deletes_surplus(self):
        """现有 3 张 → 剪贴板 2 张：原地改写 2 行、删 1 行，保存 2 个 id。"""
        rows = [_row(1), _row(2), _row(3)]
        ops = plan_group_sync(rows, [996, 996])
        assert ops == [
            {"op": "update", "id": 1, "runs": 996, "quantity": 1},
            {"op": "update", "id": 2, "runs": 996, "quantity": 1},
            {"op": "delete", "id": 3},
        ]

    def test_quantity_block_keeps_id_and_quantity(self):
        """一行 quantity=3（拷贝产出的合并行）→ 剪贴板 3 张同值：单条 update，张数不变。"""
        ops = plan_group_sync([_row(1, quantity=3)], [996, 996, 996])
        assert ops == [{"op": "update", "id": 1, "runs": 996, "quantity": 3}]

    def test_quantity_reduced_does_not_delete_row(self):
        """容量用不完只缩减张数，绝不整行删除（回归：审计指出的 quantity 缺口）。"""
        ops = plan_group_sync([_row(1, quantity=3)], [996, 996])
        assert ops == [{"op": "update", "id": 1, "runs": 996, "quantity": 2}]

    def test_quantity_exhausted_then_inserts(self):
        ops = plan_group_sync([_row(1, quantity=3)], [996] * 5)
        assert ops == [
            {"op": "update", "id": 1, "runs": 996, "quantity": 3},
            {"op": "insert", "runs": 996},
            {"op": "insert", "runs": 996},
        ]

    def test_empty_clipboard_deletes_all(self):
        ops = plan_group_sync([_row(1), _row(2, quantity=3)], [])
        assert ops == [{"op": "delete", "id": 1}, {"op": "delete", "id": 2}]

    def test_empty_existing_inserts_all(self):
        assert plan_group_sync([], [1004, 1004]) == [
            {"op": "insert", "runs": 1004},
            {"op": "insert", "runs": 1004},
        ]

    def test_noted_row_survives_over_anonymous(self):
        """容量不足时保留带备注的行、删除无备注的行。"""
        rows = [_row(1, notes=""), _row(2, notes="主力图")]
        ops = plan_group_sync(rows, [1004])
        assert ops == [{"op": "delete", "id": 1}]

    def test_heterogeneous_runs_split_keeps_id_for_majority(self):
        """一行 quantity=2 被分到两个不同流程数：保 id 给多数份额，其余转新增。"""
        ops = plan_group_sync([_row(1, quantity=2)], [1004, 996])
        assert ops == [
            {"op": "update", "id": 1, "runs": 996, "quantity": 1},
            {"op": "insert", "runs": 1004},
        ]

    def test_incremental_target_never_deletes(self):
        """增量模式传入「现有 + 剪贴板」作为目标 → 不产生任何 delete。"""
        rows = [_row(1, runs=1004), _row(2, runs=2996)]
        ops = plan_group_sync(rows, [1004, 2996, 1004])
        assert ops == [{"op": "insert", "runs": 1004}]

    def test_result_is_deterministic(self):
        rows = [_row(3), _row(1, notes="n"), _row(2)]
        assert plan_group_sync(rows, [996, 996]) == plan_group_sync(list(reversed(rows)), [996, 996])


class TestTargetUnits:
    def test_truncates(self):
        assert target_units([1004, 996, 1004], 2) == [1004, 996]

    def test_pads_with_most_common(self):
        assert target_units([1004, 1004, 996], 5) == [1004, 1004, 996, 1004, 1004]

    def test_empty_pads_with_zero(self):
        assert target_units([], 3) == [0, 0, 0]

    def test_zero_target_clears(self):
        assert target_units([1004], 0) == []

    def test_negative_target_clamped(self):
        assert target_units([1004], -5) == []
