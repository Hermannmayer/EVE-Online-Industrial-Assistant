"""
剪贴板导入纯函数 — 增量/全量行计算与导入前后差异对比。

本模块只做纯逻辑（无 DB 依赖），供 ImportReviewDialog 与 HangarTab 复用。
"""

from __future__ import annotations


def compute_row_delta(mode: str, qty: int, current: int) -> tuple[int, int]:
    """计算单行导入的 (delta, final)。

    Args:
        mode: "incremental" 增量累加 | "full" 全量同步
        qty: 本次导入数量（全量模式下为目标数量）
        current: 机库现有数量

    Returns:
        (delta, final)：delta 为本行比原纪录的变化量（可负），final 为导入后数量。
    """
    if mode == "full":
        final = qty
        delta = qty - current
    else:
        delta = qty
        final = current + qty
    return delta, final


def compute_import_diff(
    before: dict[int, tuple[int, float]],
    after: dict[int, tuple[int, float]],
    names: dict[int, str],
    type_ids: list[int],
) -> list[dict]:
    """对比导入前后库存，返回发生变化行列表。

    Args:
        before: 导入前快照 {type_id: (数量, 成本价)}
        after: 导入后快照 {type_id: (数量, 成本价)}
        names: 名称映射 {type_id: 显示名}
        type_ids: 需要对比的 type_id 列表（before/after 缺省按 0 处理）

    Returns:
        [{type_id, name, qty_before, qty_after, cost_before, cost_after,
          qty_delta, cost_delta}]，仅含数量或成本发生变化的行。
    """
    result: list[dict] = []
    for tid in type_ids:
        b_qty, b_cost = before.get(tid, (0, 0))
        a_qty, a_cost = after.get(tid, (0, 0))
        if b_qty == a_qty and b_cost == a_cost:
            continue
        result.append(
            {
                "type_id": tid,
                "name": names.get(tid, str(tid)),
                "qty_before": b_qty,
                "qty_after": a_qty,
                "cost_before": b_cost,
                "cost_after": a_cost,
                "qty_delta": a_qty - b_qty,
                "cost_delta": a_cost - b_cost,
            }
        )
    return result
