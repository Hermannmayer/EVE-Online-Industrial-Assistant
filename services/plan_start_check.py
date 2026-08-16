"""产线启动条件判定 — 纯逻辑，无 DB/Qt。

供产线启动小助手判断"该行是否可启动 / 为何不可启动"：
  缺料、无材料机库、无可用蓝图、母项有子项未完成 → 按钮留白 + 状态栏原因。
母项（child_level==0）依赖子项产物，子项未完成则母项不可启动。
"""

from __future__ import annotations

_STATUS_BLOCK = {
    "in_progress": "生产中",
    "running": "生产中",
    "ready": "待下线",
    "completed": "已完成",
    "done": "已完成",
}

_ACTIVE_STATUSES = ("in_progress", "running")
_UNFINISHED_STATUSES = ("pending", "in_progress", "running")


def _plan_group_id(plan: dict) -> int:
    return int(plan.get("group_id") or plan.get("group_number") or 0)


def _plan_level(plan: dict) -> int:
    return int(plan.get("child_level") or plan.get("sub_level") or 0)


def is_parent(plan: dict) -> bool:
    """母项：child_level==0 且有组（有子项才可能构成组）。"""
    return _plan_level(plan) == 0 and bool(_plan_group_id(plan))


def children_running(plan: dict, all_plans: list[dict]) -> bool:
    """母项同组内有 in_progress/running 子项 → True。子项自身永远 False。"""
    if not is_parent(plan):
        return False
    gid = _plan_group_id(plan)
    return any(
        _plan_group_id(p) == gid and _plan_level(p) > 0 and (p.get("status") or "").lower() in _ACTIVE_STATUSES
        for p in all_plans
    )


def pending_children_count(plan: dict, all_plans: list[dict]) -> int:
    """母项未完成（pending/running/生产中）子项数，供「等待 N 条子项」展示。"""
    if not is_parent(plan):
        return 0
    gid = _plan_group_id(plan)
    return sum(
        1
        for p in all_plans
        if _plan_group_id(p) == gid and _plan_level(p) > 0 and (p.get("status") or "").lower() in _UNFINISHED_STATUSES
    )


def plan_start_block_reason(
    plan: dict,
    mat_hangar_id: int | None,
    all_plans: list[dict],
    *,
    shortfall_count: int = 0,
    allow_short: bool = False,
) -> str | None:
    """返回阻止启动的原因文本；None = 可启动。

    判定顺序：status 非待生产 → 材料机库未设置 → 缺料(且未允许缺料) →
    无可用蓝图 → 母项子项未完成。
    """
    status = (plan.get("status") or "").lower()
    if status != "pending":
        return _STATUS_BLOCK.get(status, f"状态「{status}」不可启动")
    if not mat_hangar_id:
        return "材料机库未设置"
    if shortfall_count > 0 and not allow_short:
        return f"材料不足 {shortfall_count} 种"
    if not plan.get("has_image") and not plan.get("assigned_blueprint_id"):
        return "无可用蓝图"
    if is_parent(plan):
        if children_running(plan, all_plans):
            return "子项产线运行中"
        pending = pending_children_count(plan, all_plans)
        if pending:
            return f"等待 {pending} 条子项完成"
    return None
