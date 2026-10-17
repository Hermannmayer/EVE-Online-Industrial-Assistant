"""
物流/运输分析 — 运费估算与利润计算

提供跨区域运输的运费估算和净利润计算功能。
支持两种运输模式：公开货运（按体积+抵押计价）和自有运输（按跳跃数计价）。
数据来源：硬编码 TRADE_HUB_DISTANCES 距离表、reference.db item.volume、
market.db market_prices（经 PricingService）。

⚠️ **`compute_jumps` / 距离工具仍在使用**：`services/contract_service.py` 用它给合同每行算跳数，
`list_trade_hub_distances` 供 UI 距离表。原运费估算（`estimate_freight_cost`）与运输利润
（`calc_transport_profit`）没有 UI 调用方，已按 2026-10-17 审计 04-4 删除；将来接合同市场时再按需加回。
"""

from collections import deque

from core.constants import TRADE_HUB_SYSTEM_IDS
from core.container import get_container
from core.logger import log


def _default_db():
    """惰性获取 DatabaseManager（经容器）。"""
    return get_container().db


# ════════════════════════════════════════════════════
#  四大贸易中心之间的跳跃数（High-sec 安全路线）
# ════════════════════════════════════════════════════
#: 高安门槛：星系安全等级 ≥ 此值算高安（EVE 的高安上限是 1.0，0.45 是高安的下界）。
HIGHSEC_MIN_SECURITY = 0.45

#: 兜底距离表 —— 只在 reference.db 的 stargate 表为空（全新安装尚未导 SDE）时启用。
#: ⚠️ 这张表**与实测不符**，仅作降级：Amarr↔Dodixie 标 62（真值高安 34）、
#: Amarr↔Rens 标 60（真值 20）、Hek↔Amarr 标 76（真值 26）、Jita↔Amarr 标 72（真值 45）。
#: 真值由 `compute_jumps` 走本地星门图 BFS 得出，经游戏内跳数核对。
TRADE_HUB_DISTANCES: dict[tuple[str, str], int] = {
    ("Jita", "Amarr"): 72,
    ("Jita", "Dodixie"): 12,
    ("Jita", "Rens"): 18,
    ("Amarr", "Dodixie"): 62,
    ("Amarr", "Rens"): 60,
    ("Dodixie", "Rens"): 30,
    # Hek — Metropolis 贸易中心
    ("Hek", "Amarr"): 76,
    ("Hek", "Dodixie"): 28,
    ("Hek", "Jita"): 21,
    ("Hek", "Rens"): 5,
}
# 反向对称
for (a, b), d in list(TRADE_HUB_DISTANCES.items()):
    TRADE_HUB_DISTANCES[(b, a)] = d


#: 星系邻接表与安全等级表 —— 进程内只建一次（13,776 行的星门表，建图约几十毫秒）。
_GATE_GRAPH: dict[int, set[int]] | None = None
_GATE_SECURITY: dict[int, float] = {}
#: `(起点, 终点, 口径, 最低安全) → 跳数 | None`。单次 BFS 是毫秒级，缓存是为了让
#: 表格滚动/重排时不重复算。
_JUMP_CACHE: dict[tuple[int, int, str, float | None], int | None] = {}


def _load_gate_graph() -> tuple[dict[int, set[int]], dict[int, float]]:
    """从 reference.db 建星系邻接表 + 安全等级表。

    ⚠️ `stargate.destination_system_id` 这个列名是**骗人的**：实测 13,776 行里它存的
    全是**星门 id**（5xxxxxxx），没有一个落在星系 id 区间（3xxxxxxx）。必须先把它当
    星门 id 再 join 一次 `stargate` 才拿到目标星系：

        sg1.solar_system_id → sg2.solar_system_id WHERE sg2.stargate_id = sg1.destination_system_id

    实测该图正确：Jita→Amarr 最短 11 跳（走 Ahbazon 低安捷径）、限高安 45 跳，与游戏一致。
    """
    global _GATE_GRAPH
    if _GATE_GRAPH is not None:
        return _GATE_GRAPH, _GATE_SECURITY

    graph: dict[int, set[int]] = {}
    security: dict[int, float] = {}
    with _default_db().connect("ref") as conn:
        for sys_id, sec in conn.execute("SELECT solar_system_id, security FROM solar_system"):
            security[int(sys_id)] = float(sec or 0.0)
        for a, b in conn.execute(
            """
            SELECT sg1.solar_system_id, sg2.solar_system_id
            FROM stargate sg1
            JOIN stargate sg2 ON sg2.stargate_id = sg1.destination_system_id
            """
        ):
            a, b = int(a), int(b)
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)

    if not graph:
        log.warning("星门表为空 —— 跳跃数将回退到内置距离表（重新导入 SDE 可修复）")
    _GATE_GRAPH = graph
    _GATE_SECURITY.clear()
    _GATE_SECURITY.update(security)
    return graph, security


def compute_jumps(
    origin_system_id: int,
    destination_system_id: int,
    mode: str = "shortest",
    min_security: float | None = None,
) -> int | None:
    """两个星系之间的跳跃数；不可达返回 None。

    口径：
      - `"shortest"` —— 纯最短路（可能穿低安，例如 Jita→Amarr 只要 11 跳）
      - `"highsec"`  —— 只走安全等级 ≥ `HIGHSEC_MIN_SECURITY` 的中间星系与终点（45 跳）
      - `"custom"`   —— 只走安全等级 ≥ `min_security` 的星系

    起点星系不参与安全过滤（合同从哪儿发是既成事实）。
    """
    if not origin_system_id or not destination_system_id:
        return None
    if origin_system_id == destination_system_id:
        return 0

    key = (origin_system_id, destination_system_id, mode, min_security)
    if key in _JUMP_CACHE:
        return _JUMP_CACHE[key]

    graph, security = _load_gate_graph()
    if not graph:
        _JUMP_CACHE[key] = None
        return None

    floor = HIGHSEC_MIN_SECURITY if mode == "highsec" else (min_security if mode == "custom" else None)

    def passable(sys_id: int) -> bool:
        return floor is None or security.get(sys_id, 0.0) >= floor

    jumps: int | None = None
    if passable(destination_system_id):
        seen = {origin_system_id}
        queue = deque([(origin_system_id, 0)])
        while queue:
            node, dist = queue.popleft()
            for nxt in graph.get(node, ()):
                if nxt in seen or not passable(nxt):
                    continue
                if nxt == destination_system_id:
                    jumps = dist + 1
                    queue.clear()
                    break
                seen.add(nxt)
                queue.append((nxt, dist + 1))

    _JUMP_CACHE[key] = jumps
    return jumps


def get_distance_jumps(source: str, destination: str) -> int | None:
    """两个**贸易中心**之间的跳跃数（按高安路线 —— 跑货实际会飞的那条）。

    星门图不可用时回退到内置距离表。未知贸易中心返回 None。
    """
    src_sys = TRADE_HUB_SYSTEM_IDS.get(source)
    dst_sys = TRADE_HUB_SYSTEM_IDS.get(destination)
    if src_sys and dst_sys:
        jumps = compute_jumps(src_sys, dst_sys, mode="highsec")
        if jumps is not None:
            return jumps
    return TRADE_HUB_DISTANCES.get((source, destination))


def list_trade_hub_distances() -> list[dict]:
    """返回所有贸易中心对的跳跃距离（走高安路线），供 UI 使用。"""
    seen = set()
    result = []
    for a, b in TRADE_HUB_DISTANCES:
        key = tuple(sorted([a, b]))
        if key in seen:
            continue
        seen.add(key)
        result.append({"from": a, "to": b, "jumps": get_distance_jumps(a, b)})
    return result
