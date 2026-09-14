"""甘特图排期 —— 纯计算，不依赖 Qt。

原先这套逻辑长在 `ui_pyside6/views/industry/gantt_view.py` 的 QWidget 里，
与 QPainter 自绘混在一起。阶段 2b 把绘制交给 QML，排期计算上移到服务层，
这样它可以脱离界面单测（原先要构造 QWidget 才能测）。

排期口径（与旧实现一致）：
- **行序**取计划树序（母项在前、子项紧随），与项目其它视图一致；
- **时间**上子项先跑（同组子项之间并行、都从 0 起），母项接在全部子项结束之后 ——
  母项依赖子项产出，不能一起开跑；跨组不串行（不同产品各自从 0 起）；
- 柱形条末端标出预计完成时刻（本地时区）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

__all__ = ["build_rows", "end_time_text", "max_hours"]

#: 排期时间轴的取整粒度（小时）：轴上限向上取整到它的倍数
AXIS_GRANULARITY = 12
#: 空数据时的轴上限
DEFAULT_MAX_HOURS = 48
#: `calculated_time` 缺失时的兜底：每流程每并行按 2 小时估
FALLBACK_HOURS_PER_RUN = 2


def build_rows(plans: list[dict]) -> list[dict]:
    """把计划列表排成「按 BOM 依赖串行」的甘特条。

    返回每项含 `name` / `start` / `duration`（小时）/ `endText` / `planId`。
    颜色不在这里定 —— 那是主题的事，由 QML 按行号取调色板。
    """
    from services.plan_service import group_and_sort_plans

    ordered = [p for p in group_and_sort_plans(list(plans)) if p.get("id") is not None]
    rows: list[dict] = []
    for i, plan in enumerate(ordered):
        calculated = plan.get("calculated_time", 0) or 0
        if calculated > 0:
            hours = calculated / 3600  # 秒 → 小时
        else:
            runs = plan.get("runs", 1) or 1
            parallels = plan.get("parallels", 1) or 1
            hours = runs * parallels * FALLBACK_HOURS_PER_RUN  # 兜底占位
        rows.append(
            {
                "name": plan.get("product_name", f"计划#{plan.get('id', i)}"),
                "start": 0.0,
                "duration": float(hours),
                "planId": plan.get("id"),
                "plan": plan,  # 供 end_time_text 算末端完成时刻（状态 / started_at）
            }
        )
    _apply_dependencies(rows)

    now = datetime.now(UTC)
    for row in rows:
        row["endText"] = end_time_text(row["plan"], row["start"] + row["duration"], now)
        row.pop("plan", None)
    return rows


def max_hours(rows: list[dict]) -> int:
    """时间轴上限：覆盖最右侧柱形条，向上取整到 `AXIS_GRANULARITY` 的倍数。"""
    longest = int(max((r.get("duration", 1) + r.get("start", 0) for r in rows), default=DEFAULT_MAX_HOURS))
    longest = max(longest, 24)
    return ((longest + AXIS_GRANULARITY - 1) // AXIS_GRANULARITY) * AXIS_GRANULARITY


def _apply_dependencies(rows: list[dict]) -> None:
    """同组内按 `component_parent_type_id` 建依赖边：父项 start = max(子项 end)。

    子项都是叶子 → 从 0 起跑；每一层的父项被推到子项结束之后。
    用**松弛迭代**而不是递归：BOM 层数未知，迭代天然能容忍环（轮数上界 = 行数）。
    **跨组不串行** —— 不同 group_number 是不同产品，各自从 0 起。
    """
    by_group: dict[int, list[dict]] = {}
    for row in rows:
        plan = row["plan"]
        gid = int(plan.get("group_id") or plan.get("group_number") or 0)
        by_group.setdefault(gid, []).append(row)

    for gid, members in by_group.items():
        if not gid:  # 独立计划：各自从 0 起跑
            continue
        by_tid = {int(m["plan"].get("product_type_id") or 0): m for m in members}
        mother = next((m for m in members if _level(m["plan"]) == 0), None)

        for _ in range(len(members)):
            changed = False
            for row in members:
                parent = _parent_row(row, by_tid, mother)
                if parent is None:
                    continue
                end = row["start"] + row["duration"]
                if end > parent["start"]:
                    parent["start"] = end
                    changed = True
            if not changed:
                break


def _parent_row(row: dict, by_tid: dict, mother: dict | None) -> dict | None:
    """行在时间上的前驱：同组内 `component_parent_type_id` 指向的那一行。

    缺失 / 指回自己 → 回退该组的母项；母项自己 → None（没有前驱）。
    """
    ptid = row["plan"].get("component_parent_type_id")
    parent = by_tid.get(int(ptid)) if ptid else None
    if parent is None or parent is row:
        parent = mother
    return None if parent is row else parent


def _level(plan: dict) -> int:
    return int(plan.get("child_level") or plan.get("sub_level") or 0)


def end_time_text(plan: dict, end_hours: float, now: datetime | None = None) -> str:
    """柱形条末端的预计完成时刻（**本地时区** MM-DD HH:MM）。

    - 在产计划给**真实 ETA**：`started_at + calculated_time`，与倒计时列同一实现
      （`plan_execution.remaining_seconds`），只是换算到本地时区再显示 ——
      库里 `started_at` 存的是 naive UTC，直接显示会差一个时区。
    - 其余按「现在开工」推算：本地当前时间 + 排期结束偏移。
    """
    from services.plan_execution import remaining_seconds

    now_utc = now or datetime.now(UTC)
    if str(plan.get("status") or "").lower() in ("in_progress", "running"):
        rem = remaining_seconds(plan, now=now_utc)
        if rem is not None:
            return (now_utc + timedelta(seconds=rem)).astimezone().strftime("%m-%d %H:%M")
    local_now = now_utc.astimezone().replace(tzinfo=None)
    return (local_now + timedelta(hours=end_hours)).strftime("%m-%d %H:%M")
