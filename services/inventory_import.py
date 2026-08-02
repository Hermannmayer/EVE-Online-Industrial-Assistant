"""
剪贴板导入纯函数 — 增量/全量行计算与导入前后差异对比。

本模块只做纯逻辑（无 DB 依赖），供 ImportReviewDialog 与 HangarTab 复用。
"""

from __future__ import annotations

import re

# 全选复制可能带表头行（如「名称\t数量\t…」），按首个字段白名单跳过
_HEADER_TOKENS = {"名称", "物品", "项目", "item", "items", "name", "quantity", "数量", "type", "分类", "Item"}
# 数量字段里应跳过的体积/价格关键字
_SKIP_FIELD_KEYWORDS = ("m3", "m³", "星币", "isk", "体积", "volume", "估价", "price")


def split_clipboard_lines(raw: str) -> list[dict]:
    """解析 EVE 剪贴板 → [{name, qty}]（纯函数，无 DB 依赖）。

    支持 Tab 分隔与 ≥2 空格分隔两种格式；
    物品名去除尾部 *；数量取首个可解析为整数的非体积/价格字段；
    自动跳过表头行（名称/数量/类型等）与空行。
    """
    out: list[dict] = []
    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            # 空格分隔 — 按 2 个以上空格拆分，避免拆开物品名内部的单空格
            parts = [p.strip() for p in re.split(r" {2,}", line) if p.strip()]
        if not parts:
            continue
        name = parts[0].rstrip("*").strip()
        if not name:
            continue
        if name in _HEADER_TOKENS:
            continue
        qty = 1
        for p in parts[1:]:
            token = p.rstrip("*").replace(",", "").replace(" ", "")
            if any(kw in p.lower() for kw in _SKIP_FIELD_KEYWORDS):
                continue
            try:
                qty = int(token)
                break
            except ValueError:
                continue
        out.append({"name": name, "qty": qty})
    return out


def compute_transfer_rows(
    rows: list[dict],
    source_stock: dict[int, int],
    target_stock: dict[int, int] | None = None,
) -> list[dict]:
    """按剪贴板行生成移库计划（纯函数）。

    Args:
        rows: 已解析行 [{type_id, qty, ...}]（仅已匹配行；type_id 为 None 的行被过滤）
        source_stock: 源机库库存快照 {type_id: 数量}
        target_stock: 目标机库库存快照 {type_id: 数量}（缺省按空）

    Returns:
        [{type_id, clipboard_qty, source_avail, target_avail, move_qty, capped}]
        move_qty = min(clipboard_qty, source_avail)；capped 表示剪贴板数量超出源库现有。
    """
    target_stock = target_stock or {}
    out: list[dict] = []
    for r in rows:
        tid = r.get("type_id")
        if not tid:
            continue
        clip = int(r.get("qty") or 0)
        avail = int(source_stock.get(tid, 0))
        out.append(
            {
                "type_id": tid,
                "clipboard_qty": clip,
                "source_avail": avail,
                "target_avail": int(target_stock.get(tid, 0)),
                "move_qty": min(clip, avail),
                "capped": clip > avail,
            }
        )
    return out


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
