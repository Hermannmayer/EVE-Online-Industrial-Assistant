"""产线启动条件判定测试 — services/plan_start_check.py"""

import pytest

from services.plan_start_check import (
    can_force_start,
    children_running,
    is_parent,
    pending_children_count,
    plan_start_block,
    plan_start_block_reason,
)

pytestmark = pytest.mark.fast


def _plan(**kw):
    base = {
        "id": 1,
        "status": "pending",
        "group_id": 0,
        "child_level": 0,
        "has_image": True,
        "assigned_blueprint_id": None,
    }
    base.update(kw)
    return base


class TestChildrenRunning:
    def test_parent_with_running_child(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status="in_progress")
        assert children_running(parent, [parent, child]) is True

    @pytest.mark.parametrize("status", ["pending", "completed"])
    def test_parent_with_inactive_child(self, status):
        """挂起/已完成子项都不算「产线运行中」。"""
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status=status)
        assert children_running(parent, [parent, child]) is False

    @pytest.mark.parametrize(
        "plan",
        [_plan(id=2, group_id=10, child_level=1), _plan(id=9, group_id=0, child_level=0)],
        ids=["子项", "无组"],
    )
    def test_non_parent_never_gated(self, plan):
        """子项自身 / 无组计划都不是母项 → 永远不会被「子项运行中」拦下。"""
        assert children_running(plan, [plan]) is False

    def test_other_group_children_ignored(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        other = _plan(id=5, group_id=20, child_level=1, status="in_progress")
        assert children_running(parent, [parent, other]) is False


class TestPendingChildrenCount:
    def test_counts_pending_and_running(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        c1 = _plan(id=2, group_id=10, child_level=1, status="pending")
        c2 = _plan(id=3, group_id=10, child_level=1, status="in_progress")
        c3 = _plan(id=4, group_id=10, child_level=1, status="completed")
        assert pending_children_count(parent, [parent, c1, c2, c3]) == 2

    def test_non_parent_returns_zero(self):
        child = _plan(id=2, group_id=10, child_level=1)
        assert pending_children_count(child, [child]) == 0


class TestIsParent:
    def test_parent_detection(self):
        assert is_parent(_plan(id=1, group_id=10, child_level=0)) is True
        assert is_parent(_plan(id=2, group_id=10, child_level=1)) is False
        assert is_parent(_plan(id=9, group_id=0, child_level=0)) is False


class TestPlanStartBlock:
    """`plan_start_block` 是启动阻塞的**唯一真源**：返回 (类别码, 原因文案)；None = 可启动。

    判定顺序：status → 机库 → 缺料 → 蓝图缺失 → 流程不足 → 子项。
    `plan_start_block_reason` 只是它的文案投影（1 行委托），不另立重复用例。
    """

    def test_startable(self):
        plan = _plan(id=1, group_id=0, child_level=0)
        assert plan_start_block(plan, 1, []) is None

    @pytest.mark.parametrize(
        ("status", "code", "text"),
        [
            ("ready", "status_ready", "待下线"),
            ("in_progress", "status_running", "生产中"),
            ("running", "status_running", "生产中"),
            ("completed", "status_done", "已完成"),
            ("done", "status_done", "已完成"),
            ("weird", "status_other", "状态「weird」不可启动"),
        ],
    )
    def test_status_codes(self, status, code, text):
        assert plan_start_block(_plan(status=status), 1, []) == (code, text)

    def test_no_mat_hangar(self):
        assert plan_start_block(_plan(), None, []) == ("no_mat_hangar", "材料机库未设置")

    def test_material_short(self):
        assert plan_start_block(_plan(), 1, [], shortfall_count=3) == ("material_short", "材料不足 3 种")

    def test_allow_short_bypasses_shortfall(self):
        """「仍要启动」跳过缺料这个软阻塞。"""
        assert plan_start_block(_plan(), 1, [], shortfall_count=3, allow_short=True) is None

    def test_shortfall_precedes_bp_short(self):
        """缺料优先于缺流程 —— 行上只报一个原因，顺序错了文案就错。"""
        block = plan_start_block(_plan(), 1, [], shortfall_count=2, bp_short="流程不足")
        assert block == ("material_short", "材料不足 2 种")

    def test_blueprint_missing_beats_bp_short(self):
        """一张蓝图都没有时先报「无可用蓝图」，不该报流程不足。"""
        plan = _plan(has_image=False, assigned_blueprint_id=None)
        assert plan_start_block(plan, 1, [], bp_short="流程不足") == ("blueprint_missing", "无可用蓝图")

    def test_blueprint_short(self):
        assert plan_start_block(_plan(), 1, [], bp_short="流程不足") == ("blueprint_short", "流程不足")

    def test_allow_short_skips_bp_short(self):
        assert plan_start_block(_plan(), 1, [], bp_short="流程不足", allow_short=True) is None

    def test_children_running_beats_waiting(self):
        """同组既有运行中又有待办子项 → 报「运行中」。"""
        parent = _plan(id=1, group_id=10, child_level=0)
        c1 = _plan(id=2, group_id=10, child_level=1, status="in_progress")
        c2 = _plan(id=3, group_id=10, child_level=1, status="pending")
        assert plan_start_block(parent, 1, [parent, c1, c2]) == ("children_running", "子项产线运行中")

    def test_waiting_children(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status="pending")
        assert plan_start_block(parent, 1, [parent, child]) == ("waiting_children", "等待 1 条子项完成")

    def test_child_ignores_group(self):
        """子项自身不因「组里有人」被拦 —— 它自己就是干活的那条。"""
        child = _plan(id=2, group_id=10, child_level=1)
        assert plan_start_block(child, 1, [child]) is None

    def test_reason_projection_agrees_with_block(self):
        """`plan_start_block_reason` 是同一判定的文案投影（同源），抽查代表性分支。"""
        plan = _plan()
        for kw in (
            {},
            {"shortfall_count": 3},
            {"bp_short": "流程不足"},
            {"shortfall_count": 2, "bp_short": "流程不足"},
            {"shortfall_count": 3, "allow_short": True},
        ):
            block = plan_start_block(plan, 1, [], **kw)
            assert plan_start_block_reason(plan, 1, [], **kw) == (block[1] if block else None)


class TestCanForceStart:
    """缺料是否为**唯一**阻塞 —— 决定行上给「启动」还是「?」（与计划表格同口径）。"""

    def test_shortfall_only_is_forceable(self):
        assert can_force_start(_plan(), 1, [], shortfall_count=2) is True

    def test_no_shortfall_is_not(self):
        assert can_force_start(_plan(), 1, [], shortfall_count=0) is False

    def test_missing_hangar_blocks(self):
        """材料机库未设置 → 不只是缺料，不可强制。"""
        assert can_force_start(_plan(), None, [], shortfall_count=2) is False

    def test_no_blueprint_blocks(self):
        """无可用蓝图 → 不可强制。"""
        assert can_force_start(_plan(has_image=False), 1, [], shortfall_count=2) is False

    def test_pending_children_block(self):
        """母项还有未完成子项 → 不可强制。"""
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1)
        assert can_force_start(parent, 1, [parent, child], shortfall_count=2) is False


class TestCanForceStartWithBlueprint:
    """蓝图流程不足（`bp_short`）与缺料同属**可强制**的软阻塞。"""

    def test_bp_short_only_is_forceable(self):
        assert can_force_start(_plan(), 1, [], shortfall_count=0, bp_short="流程不足") is True

    def test_both_soft_blocks_forceable(self):
        assert can_force_start(_plan(), 1, [], shortfall_count=2, bp_short="流程不足") is True

    def test_bp_short_with_pending_children_not_forceable(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1)
        assert can_force_start(parent, 1, [parent, child], shortfall_count=0, bp_short="流程不足") is False

    def test_bp_short_without_blueprint_not_forceable(self):
        plan = _plan(has_image=False, assigned_blueprint_id=None)
        assert can_force_start(plan, 1, [], shortfall_count=0, bp_short="流程不足") is False
