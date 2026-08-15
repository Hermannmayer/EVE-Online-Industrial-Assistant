"""BOM 递归遍历骨架 — 单一守卫的 DFS。

把「查蓝图 → 查材料 → 算材料量 → 环/深度守卫」收敛为唯一来源，
供树（材料树）、扁平（材料总表 / 溢出清单）等不同投影复用。

查询经 BlueprintReader 协议注入，领域层不依赖 SQLite 连接。
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from domain.formulas import calc_material_for_runs

DEFAULT_WASTE = 10  # T1 兜底（calc_material_for_runs 当前不参与计算，保留兼容）


class BlueprintReader(Protocol):
    """蓝图数据访问协议 — 由 services 层适配实现。"""

    def product(self, product_type_id: int, activity: str = "manufacturing") -> tuple[int, int] | None:
        """返回 (blueprint_type_id, per_run_output)；无蓝图返回 None。"""
        ...

    def materials(self, blueprint_type_id: int, activity: str = "manufacturing") -> list[tuple[int, int, int]]:
        """返回 [(material_type_id, quantity, wastefactor)]。"""
        ...


@dataclass
class BomStep:
    """DFS 遍历的一个节点事件。blueprint=None 表示叶子（含环/深度封顶）。"""

    type_id: int
    qty: float
    depth: int
    blueprint: tuple[int, int] | None  # (bp_id, per_run) 或 None
    runs: int  # 中间产品 = ceil(qty/per_run)；叶子 = 0


def walk_bom(
    reader: BlueprintReader,
    root_type_id: int,
    quantity: float,
    *,
    me_level: int = 0,
    max_depth: int = 5,
    seen_mode: str = "path",
) -> Iterator[BomStep]:
    """按前序 DFS 遍历 BOM，yield BomStep。

    seen_mode:
      - "path"：路径集（下钻 add / 回溯 discard），真环命中 → 作为叶子 yield。
      - "global"：全局集，重复/环命中 → 跳过（不再 yield / 递归）。

    材料子节点量 = calc_material_for_runs(mat_qty, wastefactor or DEFAULT_WASTE, me_level, runs)。
    """
    seen: set[int] = set()

    def _walk(type_id: int, qty: float, depth: int) -> Iterator[BomStep]:
        if depth > max_depth:
            yield BomStep(type_id, qty, depth, None, 0)
            return
        if type_id in seen:
            if seen_mode == "path":
                yield BomStep(type_id, qty, depth, None, 0)
            return
        bp = reader.product(type_id)
        if bp is None:
            if seen_mode == "global":
                seen.add(type_id)
            yield BomStep(type_id, qty, depth, None, 0)
            return
        bp_id, per_run = bp
        if per_run < 1:
            per_run = 1
        runs = math.ceil(qty / per_run)
        seen.add(type_id)
        yield BomStep(type_id, qty, depth, (bp_id, per_run), runs)
        for mat_id, mat_qty, wastefactor in reader.materials(bp_id):
            child_qty = calc_material_for_runs(mat_qty, wastefactor or DEFAULT_WASTE, me_level, runs)
            yield from _walk(mat_id, child_qty, depth + 1)
        if seen_mode == "path":
            seen.discard(type_id)

    yield from _walk(root_type_id, quantity, 0)
