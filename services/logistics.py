"""
物流/运输分析 — 运费估算与利润计算

提供跨区域运输的运费估算和净利润计算功能。
支持两种运输模式：公开货运（按体积+抵押计价）和自有运输（按跳跃数计价）。
数据来源：硬编码 TRADE_HUB_DISTANCES 距离表、reference.db item.volume、
market.db market_prices（经 PricingService）。

⚠️ **当前没有 UI 调用方**：市场贸易页的「运输利润」Tab 已删除（2026-09），
`estimate_freight_cost` / `calc_transport_profit` 保留待合同市场接入；
`compute_jumps` 仍被 `services/contract_service.py` 使用。
"""

from collections import deque

from core.constants import TRADE_HUB_SYSTEM_IDS
from core.container import get_container
from core.eve_formulas import (
    ACCOUNTING_MULT,
    ADV_BROKER_DISCOUNT,
    BROKER_FEE_BASE,
    BROKER_FEE_MIN,
    BROKER_RELATION_MULT,
    RELIST_BASE_DISCOUNT,
    SALES_TAX_BASE,
    STANDING_CORP_WEIGHT,
    STANDING_FACTION_WEIGHT,
)
from core.logger import log


def _default_db():
    """惰性获取 DatabaseManager（经容器）。"""
    return get_container().db


def _default_pricing():
    """惰性获取 PricingService（经容器）。"""
    return get_container().pricing_service


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


def estimate_freight_cost(
    volume_m3: float,
    distance_jumps: int,
    collateral: float,
    price_per_jump: float = 500_000,
    price_per_m3: float = 200,
    use_public_freight: bool = True,
) -> dict:
    """
    估算跨区域货物运输的运费。

    两种计价模式：
    1. 公开货运（use_public_freight=True）：按体积 + 抵押价值计价
       - 公开货运公司如 PushX、Red Frog、Haulers Channel
       - 一般按体积（isk/m³）和抵押（% of collateral）收费
    2. 自有运输（use_public_freight=False）：按跳跃数计价（燃料成本）
       - 使用自己的货船运输
       - 只需燃料成本（isk/跳）

    参数:
        volume_m3: 物品总体积 (m³)
        distance_jumps: 跳跃数
        collateral: 货物抵押价值 (ISK)
        price_per_jump: 每跳燃料成本 (ISK)，默认 500,000
        price_per_m3: 公开货运每 m³ 费率 (ISK)，默认 200
        use_public_freight: 是否使用公开货运

    返回:
        {
            "freight_cost": float,      # 估算运费
            "collateral_fee": float,    # 抵押附加费（公开货运）
            "fuel_cost": float,         # 燃料成本（自有运输）
            "total_cost": float,        # 总运输成本
            "mode": str,                # 运输模式
            "breakdown": {...},         # 明细
        }
    """
    if volume_m3 <= 0:
        volume_m3 = 1.0
    if distance_jumps <= 0:
        distance_jumps = 1

    breakdown = {}

    if use_public_freight:
        # 公开货运：体积费 + 抵押附加费
        volume_fee = volume_m3 * price_per_m3
        # 抵押附加费 = collateral × 0.02（2% 行业标准费率）
        collateral_pct = 0.02
        collateral_fee = collateral * collateral_pct
        freight_cost = volume_fee + collateral_fee
        fuel_cost = 0.0

        breakdown = {
            "volume_fee": round(volume_fee, 2),
            "collateral_pct": round(collateral_pct * 100, 1),
            "collateral_fee": round(collateral_fee, 2),
            "price_per_m3": price_per_m3,
        }
        mode = "public_freight"
    else:
        # 自有运输：仅燃料成本
        fuel_cost = price_per_jump * distance_jumps
        freight_cost = fuel_cost
        collateral_fee = 0.0

        breakdown = {
            "price_per_jump": price_per_jump,
            "fuel_cost": round(fuel_cost, 2),
        }
        mode = "self_transport"

    return {
        "freight_cost": round(freight_cost, 2),
        "collateral_fee": round(collateral_fee if use_public_freight else 0, 2),
        "fuel_cost": round(fuel_cost if not use_public_freight else 0, 2),
        "total_cost": round(freight_cost, 2),
        "mode": mode,
        "breakdown": breakdown,
    }


def calc_transport_profit(
    type_id: int,
    buy_hub: str,
    sell_hub: str,
    buy_price_type: str,
    sell_price_type: str,
    quantity: int,
    distance_jumps: int,
    char_config: dict | None = None,
    use_public_freight: bool = True,
) -> dict:
    """
    计算跨区域运输的净利润（包含运费和贸易费用）。

    参数:
        type_id: 物品 type_id
        buy_hub: 购买区域
        sell_hub: 出售区域
        buy_price_type: 买入价类型 'buy'/'sell'
        sell_price_type: 卖出价类型 'buy'/'sell'
        quantity: 数量
        distance_jumps: 跳跃数
        char_config: 角色配置（技能等级等）
        use_public_freight: 是否使用公开货运

    返回:
        {
            "buy_cost": float,
            "sell_revenue": float,
            "freight_cost": float,
            "broker_cost": float,
            "sales_tax": float,
            "net_profit": float,
            "margin_pct": float,
            "isk_per_m3": float,
            "total_volume_m3": float,
            "status": str,
        }
    """
    result = {
        "buy_cost": 0.0,
        "sell_revenue": 0.0,
        "freight_cost": 0.0,
        "broker_cost": 0.0,
        "sales_tax": 0.0,
        "net_profit": 0.0,
        "margin_pct": 0.0,
        "isk_per_m3": 0.0,
        "total_volume_m3": 0.0,
        "status": "",
    }

    # 1. 获取买卖价格
    buy_price = _default_pricing().get_price(type_id, buy_price_type, buy_hub)
    sell_price = _default_pricing().get_price(type_id, sell_price_type, sell_hub)

    if not buy_price or not sell_price:
        result["status"] = "no_price"
        return result

    # 2. 获取物品体积
    with _default_db().connect("ref") as conn:
        c = conn.cursor()
        c.execute("SELECT volume FROM item WHERE type_id = ?", (type_id,))
        row = c.fetchone()
        volume_m3 = row[0] or 1.0 if row else 1.0

    total_volume_m3 = volume_m3 * quantity

    # 3. 获取角色技能配置
    skills = char_config.get("skills", {}) if char_config else {}
    market_data_buy = char_config.get("market", {}).get(buy_hub.lower(), {}) if char_config else {}
    market_data_sell = char_config.get("market", {}).get(sell_hub.lower(), {}) if char_config else {}

    # 4. 计算买入经纪人费
    broker_lvl = skills.get("经纪人关系学", 0)
    adv_rel = skills.get("高级经纪人关系学", 0)
    accounting = skills.get("会计学", 0)

    # 买入声望因子
    fs_buy = market_data_buy.get("faction_standing", 5.0)
    cs_buy = market_data_buy.get("corp_standing", 5.0)
    sf_buy = 2 ** (STANDING_FACTION_WEIGHT * max(0, fs_buy) + STANDING_CORP_WEIGHT * max(0, cs_buy))
    broker_rate = (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_lvl) / sf_buy if sf_buy > 0 else BROKER_FEE_BASE
    broker_rate = max(BROKER_FEE_MIN, broker_rate)

    # 改单折扣
    relist_discount = min(RELIST_BASE_DISCOUNT + adv_rel * ADV_BROKER_DISCOUNT, 100)

    # 买入费用 = 1次挂单 + 1次改单
    buy_broker_pct = broker_rate + broker_rate * (1 - relist_discount / 100)

    # 5. 计算卖出费率（声望可能不同）
    fs_sell = market_data_sell.get("faction_standing", 5.0)
    cs_sell = market_data_sell.get("corp_standing", 5.0)
    sf_sell = 2 ** (STANDING_FACTION_WEIGHT * max(0, fs_sell) + STANDING_CORP_WEIGHT * max(0, cs_sell))
    sell_rate = (BROKER_FEE_BASE - BROKER_RELATION_MULT * broker_lvl) / sf_sell if sf_sell > 0 else BROKER_FEE_BASE
    sell_rate = max(BROKER_FEE_MIN, sell_rate)

    # 卖出费用 = 1次挂单 + 1次改单 + 销售税
    sell_broker_pct = sell_rate + sell_rate * (1 - relist_discount / 100)
    sales_tax_rate = SALES_TAX_BASE * (1 - ACCOUNTING_MULT * accounting)

    # 6. 基础成本/收入
    raw_buy_cost = buy_price * quantity
    raw_sell_revenue = sell_price * quantity

    buy_broker_cost = raw_buy_cost * (buy_broker_pct / 100)
    sell_broker_cost = raw_sell_revenue * (sell_broker_pct / 100)
    sales_tax = raw_sell_revenue * (sales_tax_rate / 100)

    total_buy_cost = raw_buy_cost + buy_broker_cost
    total_sell_revenue = raw_sell_revenue - sell_broker_cost - sales_tax
    total_broker_cost = buy_broker_cost + sell_broker_cost

    # 7. 计算运费
    collateral = raw_buy_cost  # 抵押价值 = 买入总成本
    freight_result = estimate_freight_cost(
        volume_m3=total_volume_m3,
        distance_jumps=distance_jumps,
        collateral=collateral,
        use_public_freight=use_public_freight,
    )
    freight_cost = freight_result["total_cost"]

    # 8. 计算净利润
    net_profit = total_sell_revenue - total_buy_cost - freight_cost
    buy_total_including_freight = total_buy_cost + freight_cost
    margin_pct = net_profit / buy_total_including_freight * 100 if buy_total_including_freight > 0 else 0

    isk_per_m3 = net_profit / total_volume_m3 if total_volume_m3 > 0 else net_profit

    return {
        "buy_cost": round(total_buy_cost, 2),
        "sell_revenue": round(total_sell_revenue, 2),
        "freight_cost": round(freight_cost, 2),
        "broker_cost": round(total_broker_cost, 2),
        "sales_tax": round(sales_tax, 2),
        "net_profit": round(net_profit, 2),
        "margin_pct": round(margin_pct, 2),
        "isk_per_m3": round(isk_per_m3, 2),
        "total_volume_m3": round(total_volume_m3, 2),
        "freight_breakdown": freight_result["breakdown"],
        "freight_mode": freight_result["mode"],
        "status": "",
    }


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
