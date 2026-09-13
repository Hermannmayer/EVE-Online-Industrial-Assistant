"""产线启动条件判定 — 纯逻辑，无 DB/Qt。

供产线启动小助手判断"该行是否可启动 / 为何不可启动"：
  缺料、无材料机库、无可用蓝图、母项有子项未完成 → 按钮留白 + 状态栏原因。
母项（child_level==0）依赖子项产物，子项未完成则母项不可启动。
"""

from __future__ import annotations

# 非待生产状态 → (类别码, 原因文案)。码供 UI 选短标签，文案供 tooltip，
# 同一处定义保证两者永不漂移。
_STATUS_BLOCK = {
    "in_progress": ("status_running", "生产中"),
    "running": ("status_running", "生产中"),
    "ready": ("status_ready", "待下线"),
    "completed": ("status_done", "已完成"),
    "done": ("status_done", "已完成"),
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


def plan_start_block(
    plan: dict,
    mat_hangar_id: int | None,
    all_plans: list[dict],
    *,
    shortfall_count: int = 0,
    bp_short: str | None = None,
    allow_short: bool = False,
    blueprint_ready: bool | None = None,
) -> tuple[str, str] | None:
    """启动阻塞的**唯一真源**：返回 `(类别码, 原因文案)`；None = 可启动。

    判定顺序：status 非待生产 → 材料机库未设置 → 缺料 → 输入蓝图不可用 →
    蓝图流程不足 → 母项子项未完成。`plan_start_block_reason` 是本函数的文案投影，
    UI 用类别码选动作槽短标签、用文案做 tooltip —— 两者同源，不会漂移。

    类别码：status_running / status_ready / status_done / status_other /
    no_mat_hangar / material_short / blueprint_missing / blueprint_short /
    children_running / waiting_children。

    入参含义同 `plan_start_block_reason` 的 docstring。
    """
    status = (plan.get("status") or "").lower()
    if status != "pending":
        return _STATUS_BLOCK.get(status, ("status_other", f"状态「{status}」不可启动"))
    if not mat_hangar_id:
        return "no_mat_hangar", "材料机库未设置"
    if shortfall_count > 0 and not allow_short:
        return "material_short", f"材料不足 {shortfall_count} 种"
    ready = blueprint_ready
    if ready is None:
        ready = bool(plan.get("has_image") or plan.get("assigned_blueprint_id"))
    if not ready:
        from services.plan_job_kinds import input_blueprint_hint

        return "blueprint_missing", input_blueprint_hint(plan.get("activity"))
    if bp_short and not allow_short:
        return "blueprint_short", bp_short
    if is_parent(plan):
        if children_running(plan, all_plans):
            return "children_running", "子项产线运行中"
        pending = pending_children_count(plan, all_plans)
        if pending:
            return "waiting_children", f"等待 {pending} 条子项完成"
    return None


def plan_start_block_reason(
    plan: dict,
    mat_hangar_id: int | None,
    all_plans: list[dict],
    *,
    shortfall_count: int = 0,
    bp_short: str | None = None,
    allow_short: bool = False,
    blueprint_ready: bool | None = None,
) -> str | None:
    """返回阻止启动的原因文本；None = 可启动（`plan_start_block` 的文案投影）。

    `bp_short`: 蓝图流程不足的原因文本（由调用方用
    `services.plan_execution.binding_shortfall(plan_id)` 预检后注入 ——
    本函数是纯逻辑、不碰 DB）。
    `allow_short`: 打开后跳过**可强制**的两个软阻塞（缺料、蓝图流程不足）；
    其余阻塞（机库未设置 / 无蓝图 / 等子项）不受影响。
    blueprint_ready: 是否已绑定可用输入蓝图。None（默认）= 按旧口径
        用 plan 的 has_image / assigned_blueprint_id 推断；
        调用方拿到更准的信息（plan_execution.plan_blueprint_ready）时应显式传入。
    """
    block = plan_start_block(
        plan,
        mat_hangar_id,
        all_plans,
        shortfall_count=shortfall_count,
        bp_short=bp_short,
        allow_short=allow_short,
        blueprint_ready=blueprint_ready,
    )
    return block[1] if block else None


def can_force_start(
    plan: dict,
    mat_hangar_id: int | None,
    all_plans: list[dict],
    *,
    shortfall_count: int,
    bp_short: str | None = None,
    blueprint_ready: bool | None = None,
) -> bool:
    """缺料 / 蓝图流程不足 是否为**唯一**阻塞 → 允许「仍要启动」（与计划表格同口径）。

    复用 `plan_start_block_reason`：把 allow_short 打开后再看还有没有别的阻塞
    （材料机库未设置 / 无可用蓝图 / 母项子项未完成），有则不可强制。
    """
    if shortfall_count <= 0 and not bp_short:
        return False
    return (
        plan_start_block_reason(
            plan,
            mat_hangar_id,
            all_plans,
            shortfall_count=shortfall_count,
            bp_short=bp_short,
            allow_short=True,
            blueprint_ready=blueprint_ready,
        )
        is None
    )
