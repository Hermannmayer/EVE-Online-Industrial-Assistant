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


def compute_missing_in_hangar(
    hangar_qty: dict[int, int],
    clipboard_type_ids: set[int],
) -> dict[int, int]:
    """全量同步的**反向差集**：「目标机库里有、剪贴板里没有」的物品 → {type_id: 现有数量}。

    「库存修正 / 全量同步」是以剪贴板为准的**双向**比对：正向按剪贴板数量 set，
    反向把这条差集清零（数量归零 = 删掉机库里的那一行）。只做正向就是本条缺陷的根因 ——
    用户修正库存后，上一份清单里有、这次没复制的物品会**永久残留**在软件里
    （实测 `41484 旗舰级电容器电池 I` 残留 6 个，计划表据此少排 6 个）。

    只收 `quantity > 0` 的行（0 行本来就不在库里）；结果按 type_id 升序，
    便于预览与确认文案稳定排序。纯函数、无 DB 依赖，由调用方把机库快照喂进来。
    """
    return {
        int(tid): int(qty) for tid, qty in sorted(hangar_qty.items()) if int(qty) > 0 and tid not in clipboard_type_ids
    }


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
