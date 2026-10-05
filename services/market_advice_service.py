"""交易建议 —— 单个物品「挂单还是吃单」的只读判定（纯计算 + 只读查询）。

数据源与口径（三张表都在 `market.db`）：

- `market_prices`：每个 `(type_id, region_id)` 一行**挂单价** —— `buy_price` 是最高买单价、
  `sell_price` 是最低卖单价。同一 key 有多行时取 `fetch_time` 最新的一行（与市场浏览器同口径）。
- `price_history`：日级**成交**数据。`dayVolume` = 近 7 个**日历天**（`[今天 - 6, 今天]`）的
  `volume` 之和 ÷ 7，窗口内没有记录的日子按 0 成交计入分母；窗口里**一条记录都没有** → `None`
  （「没记录」不等于「0 成交」，不拿 0 冒充）。
- `market_volume_snapshots`：每日快照，`orderVolume` 取该物品**最新一天**的 `sell_volume`
  （卖单挂单量）。没有快照行 → `None`；快照里的 0 是真的「队列为空」，照实回 0。

费率**不在这里发明**：默认值取自 `core.eve_formulas.BROKER_FEE_BASE` / `SALES_TAX_BASE`，
且只走参数 —— 本模块**不读角色设置**，保持纯函数式。物品名走
`services.name_resolver.resolve_item_name`（terminology 覆盖 → `ref.item.zh_name` → type_id）。

判定顺序：`no_data` → `avoid_thin` → `two_sided` / `take_orders`；修正项见
`TREND_DOWN_PCT` / `TREND_UP_PCT` / `TURN_DAYS_WARN`。

**两处口径收口**（规则原文没写死，这里取更保守的一侧）：

1. 「拿不到买价 / 卖价」按**任一侧**缺价执行：只有卖价没有买价时算不出价差，给半边的吃单
   建议只会误导 → 一律 `no_data`，`reasons` 写明缺的是哪一侧。价格缺行与价格为 0 同义
   （0 不是可成交的价），字段回 `None` 而不是 0。
2. `trend_30d` 修正只加在**可操作**的三个 verdict 上：`no_data` 的两条建议是规则 1 的固定
   文案「先跑一次『更新价格』」，往后面接「尽快出手」是自相矛盾的。
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from core.eve_formulas import BROKER_FEE_BASE, SALES_TAX_BASE
from core.logger import log
from services.database_manager import get_db
from services.name_resolver import resolve_item_name

#: 吉他（The Forge）—— 与 `services.price_history.REGION_ID` 同值
JITA_RID = 10000002

#: 成交量窗口（**日历**天）：近 7 天 = [今天 - 6, 今天]
HISTORY_DAYS = 7

#: 两侧挂单的报价偏移：买单贴最高买价 +1%、卖单压最低卖价 -1%
BUY_ORDER_MULT = 1.01
SELL_ORDER_MULT = 0.99

#: 双向挂单门槛倍数：价差 > 来回费用 × 该倍数才值得两侧都挂（v1 口径）
SPREAD_FEE_MULT = 2.0

#: 大盘方向阈值（CPI 近 30 天涨跌 %）：≤ -3 尽快出手，≥ +3 可以慢慢卖
TREND_DOWN_PCT = -3.0
TREND_UP_PCT = 3.0

#: 卖单队列超过这么多天量就提示排队
TURN_DAYS_WARN = 14.0

#: 口径说明（`caliber` 字段逐字，UI 直接显示）
CALIBER = "买卖价=挂单价；成交量=成交历史（近 7 个日历天）"

#: 拿不到报价时的固定建议（规则 1）
NO_DATA_ADVICE = "先跑一次「更新价格」（本页数据来自本地缓存）"


# ════════════════════════════════════════════════════════════════
#  纯计算
# ════════════════════════════════════════════════════════════════


def _price(value: float | None) -> float | None:
    """价格列取值：NULL 或 ≤ 0 都当「没有这个报价」→ `None`（0 不是可成交的价）。"""
    if value is None:
        return None
    price = float(value)
    return price if price > 0 else None


def _spread_pct(buy: float, sell: float) -> float | None:
    """价差 % = (卖价 − 买价) ÷ 卖价 × 100；卖价 ≤ 0 算不出 → `None`（不除零）。"""
    if sell <= 0:
        return None
    return (sell - buy) / sell * 100.0


def _round_trip_fee_pct(broker_pct: float, sales_tax_pct: float) -> float:
    """来回一次挂单的费用率 % = 买侧经纪人费 + 卖侧经纪人费 + 卖出的销售税。"""
    return 2.0 * broker_pct + sales_tax_pct


def _turn_days(order_volume: float | None, day_volume: float | None) -> float | None:
    """卖完当前卖单队列要几天 = 挂单量 ÷ 日均成交量。

    任一侧未知、或日均成交为 0 → `None`（不除零，也不拿 0 冒充「立刻卖完」）。
    """
    if order_volume is None or day_volume is None or day_volume <= 0:
        return None
    return order_volume / day_volume


def _isk(value: float | None) -> str:
    """ISK 金额文案；`None` 如实写「无报价」。

    ≥ 1 ISK 按 2 位小数；< 1 ISK 的小额报价（0.01 级）按 6 位小数并去掉尾随 0 ——
    否则「买价 0.02 × 1.01」会被四舍五入成 0.02，给不出能用的挂单价。
    """
    if value is None:
        return "无报价"
    if abs(value) >= 1:
        return f"{value:,.2f}"
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def _pct(value: float | None) -> str:
    """百分比文案；`None`（未知）如实写「未知」，不拿 0 冒充。"""
    return "未知" if value is None else f"{value:,.2f}%"


# ════════════════════════════════════════════════════════════════
#  只读查询
# ════════════════════════════════════════════════════════════════


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    """`market.db` 里有没有这张表（从没「更新价格」过的库缺表，不是错误）。

    裸 `sqlite_master` 指的是**主库**，而本模块的连接主库就是 `mkt`；哪天主库换成
    `ref`，这里必须改写成 `mkt.sqlite_master`（踩过的坑见
    `services/market_chain_service._table_exists` 的说明）。
    """
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _load_quotes(conn: sqlite3.Connection, type_id: int, region_id: int) -> tuple[float | None, float | None]:
    """`(最高买价, 最低卖价)`；缺行 / 缺表 / 价格列为 0 → 对应侧给 `None`。"""
    if not _table_exists(conn, "market_prices"):
        return None, None
    row = conn.execute(
        "SELECT buy_price, sell_price FROM market_prices WHERE type_id = ? AND region_id = ? "
        "ORDER BY fetch_time DESC LIMIT 1",
        (type_id, region_id),
    ).fetchone()
    if row is None:
        return None, None
    return _price(row["buy_price"]), _price(row["sell_price"])


def _load_day_volume(conn: sqlite3.Connection, type_id: int, region_id: int, days: int) -> float | None:
    """近 `days` 个日历天的日均成交量（成交量之和 ÷ days）；窗口内一条记录都没有 → `None`。"""
    if not _table_exists(conn, "price_history"):
        return None
    today = date.today()
    start = (today - timedelta(days=days - 1)).isoformat()
    row = conn.execute(
        "SELECT COUNT(*) AS n, SUM(volume) AS vol FROM price_history "
        "WHERE type_id = ? AND region_id = ? AND date BETWEEN ? AND ?",
        (type_id, region_id, start, today.isoformat()),
    ).fetchone()
    if row is None or int(row["n"] or 0) == 0:
        return None
    return float(row["vol"] or 0) / days


def _load_order_volume(conn: sqlite3.Connection, type_id: int, region_id: int) -> float | None:
    """最新一天的卖单挂单量；没有快照行（或列为 NULL）→ `None`。"""
    if not _table_exists(conn, "market_volume_snapshots"):
        return None
    row = conn.execute(
        "SELECT sell_volume FROM market_volume_snapshots WHERE type_id = ? AND region_id = ? "
        "ORDER BY date DESC LIMIT 1",
        (type_id, region_id),
    ).fetchone()
    if row is None or row["sell_volume"] is None:
        return None
    return float(row["sell_volume"])


def _resolve_name(conn: sqlite3.Connection, type_id: int) -> str:
    """物品名：terminology 覆盖 → `ref.item.zh_name` / `en_name` → type_id 字符串。

    reference.db 还没导入（`item` 表不存在）时退回 id —— 名字缺失不该让整条建议失败。
    """
    try:
        return resolve_item_name(conn, type_id)
    except sqlite3.Error:
        log.debug("item 表不可用，物品名退回 type_id=%s", type_id)
        return str(type_id)


# ════════════════════════════════════════════════════════════════
#  对外接口
# ════════════════════════════════════════════════════════════════


def get_trade_advice(
    type_id: int,
    region_id: int = JITA_RID,
    *,
    trend_30d: float | None = None,
    broker_pct: float | None = None,
    sales_tax_pct: float | None = None,
    min_daily_volume: float = 10.0,
    _db=None,
) -> dict:
    """单个物品的「挂单还是吃单」建议（只读；字段与口径见模块 docstring）。

    `trend_30d` = 大盘方向（CPI 近 30 天涨跌 %），`None` = 不知道 → 不做大盘修正。
    `broker_pct` / `sales_tax_pct` = 该角色的经纪人费率 / 销售税率（%），`None` 时取
    `core.eve_formulas` 的基础默认值（`BROKER_FEE_BASE` / `SALES_TAX_BASE`）——
    本函数**不读角色设置**，要按角色算就由调用方传参。
    `min_daily_volume` = 薄市场门槛（件/天）。

    浮点字段：价格与挂单量原样给出；百分比 / 日均保留 4 位小数，`turnDays` 保留 2 位。
    """
    broker = float(BROKER_FEE_BASE if broker_pct is None else broker_pct)
    tax = float(SALES_TAX_BASE if sales_tax_pct is None else sales_tax_pct)
    fee_pct = _round_trip_fee_pct(broker, tax)

    conn_mgr = _db or get_db()
    with conn_mgr.connect("mkt", "ref") as conn:
        name = _resolve_name(conn, type_id)
        buy, sell = _load_quotes(conn, type_id, region_id)
        day_volume = _load_day_volume(conn, type_id, region_id, HISTORY_DAYS)
        order_volume = _load_order_volume(conn, type_id, region_id)

    spread = _spread_pct(buy, sell) if buy is not None and sell is not None else None
    turn = _turn_days(order_volume, day_volume)
    #: 成交量的一句话（缺数据时如实说「没有记录」，不说「0 件」）
    vol_phrase = (
        f"近 {HISTORY_DAYS} 个日历天没有成交记录"
        if day_volume is None
        else f"近 {HISTORY_DAYS} 个日历天日均成交 {day_volume:,.2f} 件"
    )
    fee_phrase = (
        f"来回费用 {fee_pct:,.2f}%（买侧经纪人 {broker:,.2f}% + 卖侧经纪人 {broker:,.2f}% + 销售税 {tax:,.2f}%）"
    )

    reasons: list[str] = []
    if buy is None or sell is None:
        # ── 规则 1：取不到买卖价 → no_data（任一侧缺价都算，见模块 docstring 收口 1）
        missing = "买价和卖价" if buy is None and sell is None else ("买价" if buy is None else "卖价")
        verdict = "no_data"
        reasons.append(f"取不到{missing}：本地 market_prices 里 region {region_id} 没有该物品挂单行，或价格列为 0")
        reasons.append(
            f"{vol_phrase}（有成交记录，但没有可挂的报价）"
            if day_volume is not None
            else f"price_history 里也没有它近 {HISTORY_DAYS} 个日历天的成交记录"
        )
        reasons.append(f"没有买卖价就算不出价差，{fee_phrase}也无从对比 → 先补一次本地报价")
        buy_advice = sell_advice = NO_DATA_ADVICE
    elif day_volume is None or day_volume < min_daily_volume:
        # ── 规则 2：薄市场 → 别挂大单 / 别重仓
        verdict = "avoid_thin"
        reasons.append(
            f"{vol_phrase}，低于薄市场门槛 {min_daily_volume:g} 件/天"
            if day_volume is not None
            else f"{vol_phrase}（不按 0 成交算），达不到薄市场门槛 {min_daily_volume:g} 件/天"
        )
        # 这里只说数字，不评价价差够不够 —— 价差宽也可能因为没人接单而不该挂（薄市场另有理由）
        reasons.append(f"最高买价 {_isk(buy)} / 最低卖价 {_isk(sell)} ISK，价差 {_pct(spread)}，{fee_phrase}")
        reasons.append(
            f"卖单挂单量 {order_volume:,.0f} 件，没人接单就换不了手"
            if order_volume is not None
            else "market_volume_snapshots 里没有该物品快照，卖单队列未知"
        )
        buy_advice = f"薄市场，别挂大单：{vol_phrase}，挂上去可能长期不成交"
        sell_advice = (
            f"薄市场，别重仓：卖单挂单量 {order_volume:,.0f} 件，按当前成交量要慢慢排"
            if order_volume is not None
            else "薄市场，别重仓：卖单队列未知，别压大单"
        )
    elif spread is not None and spread > fee_pct * SPREAD_FEE_MULT:
        # ── 规则 3 前半：价差盖得住来回费用两倍 → 两侧挂单
        buy_order = buy * BUY_ORDER_MULT
        sell_order = sell * SELL_ORDER_MULT
        reasons.append(
            f"价差 {_pct(spread)} > {fee_phrase}的 {SPREAD_FEE_MULT:g} 倍（{_pct(fee_pct * SPREAD_FEE_MULT)}），"
            "两侧都挂才划算"
        )
        reasons.append(f"{vol_phrase}，达到门槛 {min_daily_volume:g} 件/天，卖得动")
        if buy_order >= sell_order:
            # 两侧挂单价撞在一起（买价 × 1.01 ≥ 卖价 × 0.99）→ 没有价差空间，退回吃单
            verdict = "take_orders"
            reasons.append(
                f"但买价 × {BUY_ORDER_MULT} = {_isk(buy_order)} ISK 已 ≥ 卖价 × {SELL_ORDER_MULT} = "
                f"{_isk(sell_order)} ISK：两侧挂单撞在一起，没有价差空间"
            )
            buy_advice = f"价差太窄，改用吃单：直接吃卖单（{_isk(sell)}）"
            sell_advice = f"价差太窄，改用吃单：直接卖给最高买单（{_isk(buy)}）"
        else:
            verdict = "two_sided"
            reasons.append(
                f"最高买价 {_isk(buy)} / 最低卖价 {_isk(sell)} ISK，挂单比吃单各让 1 个点"
                f"（{_isk(buy_order)} / {_isk(sell_order)}）"
            )
            buy_advice = (
                f"挂买单：买价 × {BUY_ORDER_MULT} = {_isk(buy_order)} ISK（贴着现有最高买价往上 1 个点，别直接吃卖单）"
            )
            sell_advice = f"挂卖单：卖价 × {SELL_ORDER_MULT} = {_isk(sell_order)} ISK（压过现有最低卖价）"
    else:
        # ── 规则 3 后半：价差盖不住来回费用的两倍门槛 → 直接吃单
        # （不写「覆盖不了来回费用 Y%」：Y% < 价差 ≤ 2Y% 时那句话是错的）
        verdict = "take_orders"
        reasons.append(
            f"价差 {_pct(spread)} 覆盖不了来回费用 {_pct(fee_pct)} 的 {SPREAD_FEE_MULT:g} 倍"
            f"（{_pct(fee_pct * SPREAD_FEE_MULT)}），挂单不划算"
        )
        reasons.append(f"{vol_phrase}，达到门槛 {min_daily_volume:g} 件/天")
        reasons.append(f"最高买价 {_isk(buy)} / 最低卖价 {_isk(sell)} ISK：吃单立刻成交，挂单要等")
        buy_advice = f"直接吃卖单（{_isk(sell)}）更划算"
        sell_advice = f"直接卖给最高买单（{_isk(buy)}）"

    # ── 规则 4：大盘修正（no_data 的固定文案不接大盘话术，见模块 docstring 收口 2）
    if verdict != "no_data" and trend_30d is not None:
        trend = float(trend_30d)
        if trend <= TREND_DOWN_PCT:
            note = f"大盘近 30 天 {trend:+.1f}%：趋势向下，别挂高价等，尽快出手"
        elif trend >= TREND_UP_PCT:
            note = f"大盘近 30 天 {trend:+.1f}%：可以挂高一点慢慢卖"
        else:
            note = ""
        if note:
            reasons.append(note)
            buy_advice = f"{buy_advice}；{note}"
            sell_advice = f"{sell_advice}；{note}"

    # ── 规则 5：卖单队列排得太久
    if turn is not None and turn > TURN_DAYS_WARN and order_volume is not None and day_volume:
        reasons.append(
            f"卖单队列约 {turn:,.1f} 天量（挂单量 {order_volume:,.0f} ÷ 近 {HISTORY_DAYS} 天日均 {day_volume:,.2f}）："
            "挂单要排队，想快出就贴着买价卖"
        )

    return {
        "typeId": int(type_id),
        "name": name,
        "buyPrice": buy,
        "sellPrice": sell,
        "spreadPct": round(spread, 4) if spread is not None else None,
        "roundTripFeePct": round(fee_pct, 4),
        "dayVolume": round(day_volume, 4) if day_volume is not None else None,
        "orderVolume": order_volume,
        "turnDays": round(turn, 2) if turn is not None else None,
        "caliber": CALIBER,
        "verdict": verdict,
        "buyAdvice": buy_advice,
        "sellAdvice": sell_advice,
        "reasons": reasons,
    }
