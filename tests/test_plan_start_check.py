"""产线启动条件判定测试 — services/plan_start_check.py"""

from services.plan_start_check import (
    can_force_start,
    children_running,
    is_parent,
    pending_children_count,
    plan_start_block_reason,
)


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

    def test_parent_with_pending_child_only(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status="pending")
        assert children_running(parent, [parent, child]) is False

    def test_parent_with_completed_child(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status="completed")
        assert children_running(parent, [parent, child]) is False

    def test_child_itself_never_running_gate(self):
        child = _plan(id=2, group_id=10, child_level=1, status="pending")
        assert children_running(child, [child]) is False

    def test_no_group(self):
        standalone = _plan(id=9, group_id=0, child_level=0)
        assert children_running(standalone, [standalone]) is False

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

    def test_zero_when_all_completed(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        c1 = _plan(id=2, group_id=10, child_level=1, status="completed")
        assert pending_children_count(parent, [parent, c1]) == 0

    def test_child_returns_zero(self):
        child = _plan(id=2, group_id=10, child_level=1)
        assert pending_children_count(child, [child]) == 0


class TestIsParent:
    def test_parent_detection(self):
        assert is_parent(_plan(id=1, group_id=10, child_level=0)) is True
        assert is_parent(_plan(id=2, group_id=10, child_level=1)) is False
        assert is_parent(_plan(id=9, group_id=0, child_level=0)) is False


class TestPlanStartBlockReason:
    def test_startable(self):
        plan = _plan(id=1, group_id=0, child_level=0)
        assert plan_start_block_reason(plan, 1, []) is None

    def test_non_pending_status(self):
        assert plan_start_block_reason(_plan(status="ready"), 1, []) == "待下线"
        assert plan_start_block_reason(_plan(status="in_progress"), 1, []) == "生产中"
        assert plan_start_block_reason(_plan(status="completed"), 1, []) == "已完成"

    def test_no_mat_hangar(self):
        assert plan_start_block_reason(_plan(), None, []) == "材料机库未设置"

    def test_material_shortfall(self):
        plan = _plan()
        assert plan_start_block_reason(plan, 1, [], shortfall_count=3) == "材料不足 3 种"

    def test_allow_short_bypasses(self):
        plan = _plan()
        assert plan_start_block_reason(plan, 1, [], shortfall_count=3, allow_short=True) is None

    def test_no_blueprint(self):
        plan = _plan(has_image=False, assigned_blueprint_id=None)
        assert plan_start_block_reason(plan, 1, []) == "无可用蓝图"

    def test_parent_waiting_children(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status="pending")
        assert plan_start_block_reason(parent, 1, [parent, child]) == "等待 1 条子项完成"

    def test_parent_children_running(self):
        parent = _plan(id=1, group_id=10, child_level=0)
        child = _plan(id=2, group_id=10, child_level=1, status="in_progress")
        assert plan_start_block_reason(parent, 1, [parent, child]) == "子项产线运行中"

    def test_child_ignores_group(self):
        child = _plan(id=2, group_id=10, child_level=1)
        assert plan_start_block_reason(child, 1, [child]) is None


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


class TestBlueprintShortfallInjection:
    """蓝图流程不足（`bp_short`）与缺料同属**可强制**的软阻塞。"""

    def test_blocks_after_has_image(self):
        assert plan_start_block_reason(_plan(), 1, [], bp_short="第 1 张绑定蓝图流程不足") == "第 1 张绑定蓝图流程不足"

    def test_no_blueprint_reported_first(self):
        """一张蓝图都没有时先报「无可用蓝图」，不该报流程不足。"""
        plan = _plan(has_image=False, assigned_blueprint_id=None)
        assert plan_start_block_reason(plan, 1, [], bp_short="流程不足") == "无可用蓝图"

    def test_allow_short_skips_bp_short(self):
        assert plan_start_block_reason(_plan(), 1, [], bp_short="流程不足", allow_short=True) is None

    def test_缺料优先于缺流程(self):
        assert plan_start_block_reason(_plan(), 1, [], shortfall_count=2, bp_short="流程不足") == "材料不足 2 种"


class TestCanForceStartWithBlueprint:
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
