"""
BOM 递归展开 — 支持 T2/T3 产业链的完整材料树

从目标成品 type_id 开始，递归查找蓝图 → 材料 → 子蓝图 → 子材料，
构建完整的制造材料树。叶子节点为可直接购买的原材料。

用法:
    from services.bom_expander import expand_bom

    result = expand_bom(type_id=30013, quantity=10, bp_me=10)
    print(result["full_cost"])          # 总材料成本
    print(result["raw_materials"])      # 叶子节点列表
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from core.container import get_container
from services.manufacturing_calculator import calc_material_for_runs


def _default_db():
    """惰性获取 DatabaseManager（经容器）。"""
    return get_container().db


def _default_pricing():
    """惰性获取 PricingService（经容器）。"""
    return get_container().pricing_service


# ════════════════════════════════════════════════════
#  数据结构
# ════════════════════════════════════════════════════


@dataclass
class BomNode:
    """BOM 树节点 — 描述一个材料/中间产品的层级信息"""

    type_id: int
    name: str
    quantity: float  # 所需数量（已含 ME 浪费因子 × 产量倍数调整）
    base_quantity: int  # 蓝图中的原始数量
    is_intermediate: bool  # 是否是中间产品（可自己制造）
    children: list[BomNode] = field(default_factory=list)
    depth: int = 0
    unit_price: float = 0.0
    subtotal: float = 0.0
    blueprint_type_id: int | None = None


# ════════════════════════════════════════════════════
#  内部辅助函数
# ════════════════════════════════════════════════════


def _resolve_name(c, type_id: int) -> str:
    """解析物品名称 — 委托给 name_resolver"""
    from services.name_resolver import resolve_item_name

    return resolve_item_name(c, type_id)


def _find_blueprint_for_product(conn, product_type_id: int, activity: str = "manufacturing"):
    """查找产出指定物品的蓝图 → (bp_id, output_qty, base_time)"""
    row = conn.execute(
        """
        SELECT bp.blueprint_type_id, bp.quantity, ba.time
        FROM blueprint_products bp
        JOIN blueprint_activities ba
            ON ba.blueprint_type_id = bp.blueprint_type_id
            AND ba.activity = bp.activity
        WHERE bp.product_type_id = ? AND bp.activity = ?
        LIMIT 1
        """,
        (product_type_id, activity),
    ).fetchone()
    return row  # (bp_id, qty, time) or None


def _get_materials(conn, bp_id: int, activity: str = "manufacturing"):
    """获取蓝图材料列表 → [(material_type_id, quantity), ...]"""
    rows = conn.execute(
        """
        SELECT material_type_id, quantity
        FROM blueprint_materials
        WHERE blueprint_type_id = ? AND activity = ?
        """,
        (bp_id, activity),
    ).fetchall()
    return rows


# ════════════════════════════════════════════════════
#  核心：递归展开
# ════════════════════════════════════════════════════


def _expand(
    conn,
    type_id: int,
    needed_qty: float,
    bp_me: int,
    price_hub: str,
    price_type: str,
    depth: int,
    max_depth: int,
    seen: set[int],
    cache: dict[int, BomNode],
) -> BomNode:
    """
    内部递归展开。

    Args:
        conn: 数据库连接（已 ATTACH ref/mkt/bp）
        type_id: 要展开的物品 type_id
        needed_qty: 需要多少个（已含上层 ME/产量调整）
        bp_me: 本层蓝图的 ME 等级
        price_hub: 价格查询的贸易中心
        price_type: 价格类型 'buy'/'sell'
        depth: 当前递归深度
        max_depth: 最大递归深度
        seen: 已访问的 type_id 集合（循环检测）
        cache: type_id → BomNode 缓存（同层相同物品复用）

    Returns:
        BomNode 根节点
    """
    name = _resolve_name(conn, type_id)
    unit_price = _default_pricing().get_price(type_id, price_type, price_hub) or 0.0

    # 循环检测 / 深度限制
    if depth > max_depth or type_id in seen:
        return BomNode(
            type_id=type_id,
            name=name,
            quantity=needed_qty,
            base_quantity=0,
            is_intermediate=False,
            depth=depth,
            unit_price=unit_price,
            subtotal=round(unit_price * needed_qty, 2),
            blueprint_type_id=None,
        )

    # 缓存命中 — 注意：不同 needed_qty 不能复用，只缓存无子节点的情况
    if type_id in cache and depth > 0:
        cached = cache[type_id]
        if not cached.is_intermediate:
            # 叶子节点可以安全复用（数量缩放）
            scaled = BomNode(
                type_id=type_id,
                name=cached.name,
                quantity=needed_qty,
                base_quantity=cached.base_quantity,
                is_intermediate=False,
                depth=depth,
                unit_price=cached.unit_price,
                subtotal=round(cached.unit_price * needed_qty, 2),
                blueprint_type_id=None,
            )
            return scaled

    # 查找蓝图
    bp_row = _find_blueprint_for_product(conn, type_id, "manufacturing")
    if not bp_row:
        # 无蓝图 → 叶子节点（可直接购买的材料）
        node = BomNode(
            type_id=type_id,
            name=name,
            quantity=needed_qty,
            base_quantity=0,
            is_intermediate=False,
            depth=depth,
            unit_price=unit_price,
            subtotal=round(unit_price * needed_qty, 2),
            blueprint_type_id=None,
        )
        cache[type_id] = node
        return node

    bp_id, output_qty, _base_time = bp_row
    output_qty = output_qty or 1

    # 计算需要制造多少次（向上取整）
    runs = math.ceil(needed_qty / output_qty)

    # 获取材料
    mat_rows = _get_materials(conn, bp_id, "manufacturing")
    if not mat_rows:
        # 蓝图无材料记录 → 降级为叶子节点
        node = BomNode(
            type_id=type_id,
            name=name,
            quantity=needed_qty,
            base_quantity=output_qty,
            is_intermediate=False,
            depth=depth,
            unit_price=unit_price,
            subtotal=round(unit_price * needed_qty, 2),
            blueprint_type_id=bp_id,
        )
        cache[type_id] = node
        return node

    # 标记已访问，防止循环
    seen.add(type_id)

    children: list[BomNode] = []
    for mat_id, mat_base_qty in mat_rows:
        # 每次制造需要的材料量（含 ME 损耗）
        # runs 次制造共需要：
        child_qty = calc_material_for_runs(mat_base_qty, 10, bp_me, runs)

        child = _expand(
            conn,
            mat_id,
            child_qty,
            bp_me,  # 默认使用相同 ME（后续可扩展为每个子蓝图独立 ME）
            price_hub,
            price_type,
            depth + 1,
            max_depth,
            seen,
            cache,
        )
        children.append(child)

    # 移除循环检测标记（允许在其他分支再次遇到）
    seen.discard(type_id)

    # 计算本节点成本 = 所有子节点之和
    total_cost = sum(c.subtotal for c in children)

    node = BomNode(
        type_id=type_id,
        name=name,
        quantity=needed_qty,
        base_quantity=output_qty,
        is_intermediate=True,
        children=children,
        depth=depth,
        unit_price=unit_price,
        subtotal=round(total_cost, 2),
        blueprint_type_id=bp_id,
    )
    cache[type_id] = node
    return node


# ════════════════════════════════════════════════════
#  公开 API
# ════════════════════════════════════════════════════


def expand_bom(
    type_id: int,
    quantity: int = 1,
    bp_me: int = 0,
    price_hub: str = "Jita",
    price_type: str = "sell",
    max_depth: int = 5,
    char_config: dict | None = None,
) -> dict:
    """
    递归展开 BOM 树，返回完整的材料层级结构。

    Args:
        type_id: 目标成品 type_id
        quantity: 需要多少个成品
        bp_me: 顶层蓝图 ME 等级 (0-10)
        price_hub: 价格查询的贸易中心 (Jita, Amarr, ...)
        price_type: 价格类型 'buy' / 'sell'
        max_depth: 最大递归深度（防呆，默认 5 层足够覆盖 T3）
        char_config: 角色配置（预留，暂未使用）

    Returns:
        {
            "tree": BomNode,                  # 根节点（成品）
            "full_cost": float,               # 总材料成本（含所有中间产品）
            "leaf_only_cost": float,          # 只买原料的成本（不造中间产品）
            "depth": int,                     # 实际最大展开深度
            "raw_materials": [...],           # 所有叶子节点
            "intermediates": [...],           # 所有中间产品
        }
    """
    result: dict[str, Any] = {
        "tree": None,
        "full_cost": 0.0,
        "leaf_only_cost": 0.0,
        "depth": 0,
        "raw_materials": [],
        "intermediates": [],
    }

    with _default_db().connect("ref", "mkt", "bp") as conn:
        cache: dict[int, BomNode] = {}
        seen: set[int] = set()

        tree = _expand(
            conn,
            type_id,
            float(quantity),
            bp_me,
            price_hub,
            price_type,
            depth=0,
            max_depth=max_depth,
            seen=seen,
            cache=cache,
        )

        # 收集叶子节点和中间产品
        raw_materials: list[dict] = []
        intermediates: list[dict] = []
        max_depth_reached = 0

        def _collect(node: BomNode):
            nonlocal max_depth_reached
            if node.depth > max_depth_reached:
                max_depth_reached = node.depth

            if not node.is_intermediate:
                # 叶子节点
                raw_materials.append(
                    {
                        "type_id": node.type_id,
                        "name": node.name,
                        "total_qty": round(node.quantity, 2),
                        "unit_price": round(node.unit_price, 2),
                        "subtotal": round(node.subtotal, 2),
                    }
                )
            else:
                # 中间产品
                intermediates.append(
                    {
                        "type_id": node.type_id,
                        "name": node.name,
                        "quantity": round(node.quantity, 2),
                        "blueprint_type_id": node.blueprint_type_id,
                        "unit_cost": round(node.subtotal / node.quantity, 2) if node.quantity > 0 else 0.0,
                        "subtotal": round(node.subtotal, 2),
                        "depth": node.depth,
                    }
                )
                for child in node.children:
                    _collect(child)

        _collect(tree)

        # 计算总成本
        full_cost = tree.subtotal

        # 计算只买原料的成本（叶子节点 × 单价）
        leaf_only_cost = sum(m["subtotal"] for m in raw_materials)

        result.update(
            {
                "tree": tree,
                "full_cost": round(full_cost, 2),
                "leaf_only_cost": round(leaf_only_cost, 2),
                "depth": max_depth_reached,
                "raw_materials": raw_materials,
                "intermediates": intermediates,
            }
        )

    return result


# ════════════════════════════════════════════════════
#  便捷函数
# ════════════════════════════════════════════════════


def get_material_tree(
    type_id: int,
    quantity: int = 1,
    bp_me: int = 0,
    price_hub: str = "Jita",
    price_type: str = "sell",
) -> BomNode:
    """返回 BOM 树根节点（简洁接口）"""
    result = expand_bom(
        type_id=type_id,
        quantity=quantity,
        bp_me=bp_me,
        price_hub=price_hub,
        price_type=price_type,
    )
    return result["tree"]  # type: ignore[no-any-return]


def get_flat_materials(
    type_id: int,
    quantity: int = 1,
    bp_me: int = 0,
    price_hub: str = "Jita",
    price_type: str = "sell",
) -> list[dict]:
    """返回扁平化的所有叶子材料列表（购物清单）"""
    result = expand_bom(
        type_id=type_id,
        quantity=quantity,
        bp_me=bp_me,
        price_hub=price_hub,
        price_type=price_type,
    )
    return result["raw_materials"]  # type: ignore[no-any-return]


def print_tree(node: BomNode, indent: int = 0) -> str:
    """调试用：打印 BOM 树结构"""
    prefix = "  " * indent
    tag = "[造]" if node.is_intermediate else "[买]"
    line = f"{prefix}{tag} {node.name} (×{node.quantity:.0f}) — {node.subtotal:,.2f} ISK"
    lines = [line]
    for child in node.children:
        lines.append(print_tree(child, indent + 1))
    return "\n".join(lines)
