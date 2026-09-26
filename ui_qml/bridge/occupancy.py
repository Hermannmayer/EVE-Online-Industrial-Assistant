"""人物产线占用 —— 「每人物一块」的块数据（两个调用方共用一份渲染数据）。

块只被一块 QML 画出来：`ui_qml/qml/components/OccupancyPanel.qml`。既然渲染面是同一块
面板，喂它的数据也只能有一份，否则两个入口迟早长得不一样：

- `ui_qml/bridge/query_dashboard_bridge.py` 的 `_refresh_occupancy` —— 查询页空闲态
  仪表盘左栏，口径是**正在生产**（`services.char_capacity.RUNNING_STATUSES`）。
- `ui_qml/bridge/char_usage_bridge.py` —— 工业页「人物占用情况」对话框，口径是
  **已规划**（`PLANNED_STATUSES`：待生产的也先把线占上）。

块的形状见 `OccupancyPanel.qml` 头部；`active`（已占）的口径由调用方给的 `per_char`
决定（`services.char_capacity.char_line_usage` 算好），本模块只管「怎么显示」：
标签、语义色、统一分母 `cap`、以及「待下线 N」。

颜色在这里就解析成 hex（过 `theme.token_color` 的对比度校正）—— QML 不准自己读
`Theme` 取动态色，与资产折线图同一约定。
"""

from __future__ import annotations

from typing import Any

import ui_qml.theme.registry as theme
from services.char_capacity import (
    CAPACITY_LINE_MANUFACTURING,
    CAPACITY_LINE_REACTION,
    CAPACITY_LINE_RESEARCH,
    LINE_TYPES,
    capacity_line_for_category,
    line_label,
)

__all__ = ["LINE_COLORS", "build_occupancy_blocks", "char_status", "occupancy_summary", "ready_count_by_char_line"]

#: 线型 → 主题色 token（制造绿 / 科研青 / 反应紫）
LINE_COLORS: dict[str, str] = {
    CAPACITY_LINE_MANUFACTURING: "ACCENT_GREEN",
    CAPACITY_LINE_RESEARCH: "ACCENT_CYAN",
    CAPACITY_LINE_REACTION: "ACCENT_PURPLE",
}


def char_status(per_line: dict[str, tuple[int, int]]) -> tuple[str, str]:
    """(状态文本, 语义色 token) —— 超员 / 空闲 / 生产中（文案与产线小助手逐字一致）。"""
    active_total = sum(per_line.get(line, (0, 0))[0] for line in LINE_TYPES)
    max_total = sum(per_line.get(line, (0, 0))[1] for line in LINE_TYPES)
    if active_total > max_total:
        return f"超员 +{active_total - max_total}", "ACCENT_RED"
    if active_total == 0:
        return "空闲", "ACCENT_GREEN"
    return "生产中", "PRIMARY"


def ready_count_by_char_line(plans: list[dict]) -> dict[tuple[str, str], int]:
    """`{(人物, 线型): 待下线计划数}` —— 用计划表自己的 `category` → 线型映射。"""
    counts: dict[tuple[str, str], int] = {}
    for plan in plans:
        if str(plan.get("status") or "").lower() != "ready":
            continue
        char = str(plan.get("char_name") or "").strip()
        line = capacity_line_for_category(str(plan.get("category") or ""))
        counts[(char, line)] = counts.get((char, line), 0) + 1
    return counts


def occupancy_summary(per_char: list[tuple[str, dict[str, tuple[int, int]]]], *, label: str = "占用") -> str:
    """摘要行：`N 人物 · 占用 a/m`。`label` 让「已规划」口径的调用方换成自己的说法。"""
    active_total = sum(active for _char, per_line in per_char for active, _max in per_line.values())
    max_total = sum(maximum for _char, per_line in per_char for _active, maximum in per_line.values())
    return f"{len(per_char)} 人物 · {label} {active_total}/{max_total}"


def build_occupancy_blocks(per_char: list[tuple[str, dict[str, tuple[int, int]]]], plans: list[dict]) -> list[dict]:
    """每人物一块（块内制造 / 科研 / 反应各一行）。

    - ``active``：已占（口径由调用方的 `per_char` 决定）；``max``：该人物自己的上限。
    - ``cap``：该线型各人物上限中的**最大值** —— 所有人共用同一个分母（槽位同宽、
      条子等长可比）。早先取的是**之和**，于是单个人物跑满自己那 11 条线时
      只点亮了整条的一半（分母是所有人加起来的 22）。
    - ``readyN`` / ``readyText``：该人物该线型下 **待下线**（``status=='ready'``）的计划数，
      取自已加载的计划表，不额外查库。
    - ``freeN``：还能再上几条线（上限 − 已占，负数按 0）。
    """
    ready = ready_count_by_char_line(plans)
    cap_by_line: dict[str, int] = {
        line: max((int(per_line.get(line, (0, 0))[1]) for _char, per_line in per_char), default=0)
        for line in LINE_TYPES
    }
    blocks: list[dict[str, Any]] = []
    for char, per_line in per_char:
        status_text, status_token = char_status(per_line)
        lines_data: list[dict[str, Any]] = []
        for line in LINE_TYPES:
            active, maximum = per_line.get(line, (0, 0))
            ready_n = int(ready.get((char or "", line), 0))
            free_n = max(int(maximum) - int(active), 0)
            lines_data.append(
                {
                    "key": str(line),
                    "label": line_label(line),
                    "color": theme.token_color(LINE_COLORS.get(line, "")),
                    "active": int(active),
                    "max": int(maximum),
                    "cap": int(cap_by_line.get(line, maximum)),
                    "readyN": ready_n,
                    "readyText": f"待下线 {ready_n}" if ready_n else "",
                    "freeN": free_n,
                    "detailText": f"{line_label(line)} 已占 {int(active)} / 上限 {int(maximum)}"
                    + (f" · 待下线 {ready_n}" if ready_n else "")
                    + f" · 空闲 {free_n}",
                }
            )
        blocks.append(
            {
                "name": char or "(未分配)",
                "statusText": status_text,
                "statusColor": theme.token_color(status_token),
                "lines": lines_data,
            }
        )
    return blocks
