"""产线启动条件判定测试 — services/plan_start_check.py"""

from services.plan_start_check import (
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
