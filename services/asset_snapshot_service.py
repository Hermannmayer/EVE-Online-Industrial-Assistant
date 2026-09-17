"""物品查询页空闲态仪表盘 —— 资产快照采集/查询与钱包余额读写。

纯服务层（无 Qt）。资产折线图的数据源，5 条线取数来源如下（勿再猜）：

- ``inventory``（库存材料金额）= 遍历全部机库求和
  ``inventory_manager.get_total_value(hangar_id, price_type="sell")["market_total"]``
- ``orders``（挂单金额）= ``SELECT SUM(price * volume_remain) FROM open_orders``
- ``line_value``（运行中产线价值）= **只取制造中产线**（``category=='manufacturing'`` 且
  ``status IN ('in_progress','running')``）的材料占用 × **卖单价**，见 ``_line_value()``。
  与「仓库管理」里的「规划占用」**口径不同**：那个只算命中的库存物料，
  这里算计划的**完整材料需求**（缺料也算进去）。
- ``wallet``（钱包余额）= ``get_wallet_balance()``（settings.json，用户手填 + 订单变动自动增减）
- ``total``（总资产）= ``inventory + orders + line_value + wallet``

每天一行（``asset_snapshots.snap_date`` 唯一），当天重复记录覆盖不累积。
日期一律由 **SQLite 侧** ``date('now','localtime')`` 决定（与
``schema_migrations.price_snapshots.snapshot_time`` 同源），不混用 Python 的
``date.today()`` —— 二者跨时区/跨零点会给出不同日期，而 upsert 冲突键正是这一列。

基线表（``asset_snapshots`` / ``open_orders`` / ``order_events``）既由 schema 迁移创建给
存量库（v16→v17 建前两张表，v17→v18 加 ``line_value`` 列并建 ``order_events``），
也在本模块入口 ``CREATE TABLE IF NOT EXISTS`` 兜底给测试/新库 —— 复用
``inventory_manager.SCHEMA`` 的既有约定，两边都用 ``IF NOT EXISTS``，重复执行幂等。
``ALTER TABLE`` 不在此处，仍只走迁移。
"""

from __future__ import annotations

import sqlite3

from core.container import get_container
from core.logger import log
from services import inventory_manager, user_settings
from services.database_manager import DatabaseManager

# 基线表 DDL（与 services.schema_migrations 的 _USER_V17_TABLES_SQL / _ORDER_EVENTS_SQL 保持一致）
SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snap_date TEXT NOT NULL UNIQUE,          -- YYYY-MM-DD（本地日期），每天一行
    total REAL DEFAULT 0,                    -- 总资产（库存 + 挂单 + 产线 + 钱包）
    orders REAL DEFAULT 0,                   -- 挂单金额（卖单按 sell 价、买单按 buy 价）
    inventory REAL DEFAULT 0,                -- 库存材料金额
    line_value REAL DEFAULT 0,               -- 运行中产线价值（制造中产线材料占用 × 卖单价）
    wallet REAL DEFAULT 0,                   -- 钱包余额（用户手填 + 订单变动自动增减）
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS open_orders (
    order_id INTEGER PRIMARY KEY,
    is_buy INTEGER DEFAULT 0,
    price REAL DEFAULT 0,
    volume_total INTEGER DEFAULT 0,
    volume_remain INTEGER DEFAULT 0,
    location_id INTEGER DEFAULT 0,
    location_name TEXT DEFAULT '',
    type_id INTEGER DEFAULT 0,
    type_name TEXT DEFAULT '',
    issued TEXT DEFAULT '',
    duration INTEGER DEFAULT 0,
    imported_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS order_events (
    order_id INTEGER NOT NULL,
    applied_at TEXT NOT NULL,
    outcome TEXT DEFAULT '',        -- filled / cancelled
    is_buy INTEGER DEFAULT 0,
    price REAL DEFAULT 0,
    volume INTEGER DEFAULT 0,
    delta REAL DEFAULT 0,           -- 本次对钱包余额的增减（ISK，正=加）
    PRIMARY KEY (order_id, applied_at)
);
"""

# 钱包余额在 settings.json 里的键
_WALLET_KEY = "wallet_balance"

#: 参与「运行中产线价值」的计划状态（与 `char_capacity.active_lines_by_category` 同口径）
_ACTIVE_STATUSES = ("in_progress", "running")
#: 只取制造产线（科研/反应/拷贝不计入 —— 用户明确要求）
_LINE_CATEGORY = "manufacturing"
#: 取价星域：Jita（与 `inventory_manager.get_total_value` 同口径，不引新设置）
_REGION_ID = 10000002

_INSERT_SQL = """
INSERT INTO asset_snapshots (snap_date, total, orders, inventory, line_value, wallet)
VALUES (date('now','localtime'), ?, ?, ?, ?, ?)
ON CONFLICT(snap_date) DO UPDATE SET
    total = excluded.total,
    orders = excluded.orders,
    inventory = excluded.inventory,
    line_value = excluded.line_value,
    wallet = excluded.wallet,
    created_at = datetime('now','localtime')
"""


def _default_db() -> DatabaseManager:
    """惰性获取 DatabaseManager（经容器）。"""
    return get_container().db


def _ensure_schema(conn) -> None:
    """在给定连接上创建基线表（IF NOT EXISTS，幂等）。"""
    conn.executescript(SCHEMA)


def ensure_schema() -> None:
    """确保基线表存在（给外部调用方/新库兜底）。"""
    with _default_db().connect("user") as conn:
        _ensure_schema(conn)


def _inventory_value() -> float:
    """inventory 线：遍历全部机库按卖单价估值求和。"""
    total = 0.0
    for hangar in inventory_manager.get_hangars():
        value = inventory_manager.get_total_value(hangar["id"], price_type="sell")
        total += float(value.get("market_total", 0) or 0)
    return round(total, 2)


def _orders_value() -> float:
    """orders 线：逐行 ``price * volume_remain`` 求和（卖单用 sell 语义价、买单同理，直接取自身 price）。"""
    with _default_db().connect("user") as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT COALESCE(SUM(price * volume_remain), 0) FROM open_orders").fetchone()
    return round(float(row[0] or 0), 2)


def _sell_prices(type_ids: set[int]) -> dict[int, float]:
    """market.db 里这批 type_id 的 Jita 卖单价（缺失/为 0 的不进结果）。"""
    if not type_ids:
        return {}
    marks = ",".join("?" * len(type_ids))
    with _default_db().connect("mkt") as conn:
        rows = conn.execute(
            f"SELECT type_id, sell_price FROM market_prices WHERE region_id = ? AND type_id IN ({marks})",
            (_REGION_ID, *sorted(type_ids)),
        ).fetchall()
    return {int(r[0]): float(r[1]) for r in rows if r[1]}


def _line_value() -> float:
    """line_value 线：**制造中**产线的材料占用 × 卖单价。

    取数链路：``plan_service.load_plans_for_wizard()``（已 enrich ``category``）筛出
    ``category == 'manufacturing'`` 且 ``status IN ('in_progress','running')`` 的计划 →
    逐条 ``plan_execution.material_requirements(plan)`` 拿完整材料需求
    （含缺料：这是「占用价值」，不是「到手价值」）→ 乘 Jita 卖单价求和。

    单条计划解析失败只跳过并记日志，整体不抛 —— 一条脏计划不该让整张折线断掉。
    缺价的物料按 0 计（合并成一条 warning，避免刷屏）。
    """
    from services.plan_execution import material_requirements
    from services.plan_service import load_plans_for_wizard

    try:
        plans = [
            p
            for p in (load_plans_for_wizard() or [])
            if str(p.get("category") or "") == _LINE_CATEGORY and str(p.get("status") or "").lower() in _ACTIVE_STATUSES
        ]
    except Exception:
        log.exception("运行中产线价值：计划加载失败")
        return 0.0
    if not plans:
        return 0.0

    needs: dict[int, float] = {}
    for plan in plans:
        try:
            for req in material_requirements(plan):
                type_id = int(req.get("type_id") or 0)
                if type_id:
                    needs[type_id] = needs.get(type_id, 0.0) + float(req.get("need") or 0)
        except Exception:
            log.exception("运行中产线价值：计划 %s 的材料需求计算失败", plan.get("id"))
    if not needs:
        return 0.0

    try:
        prices = _sell_prices(set(needs))
    except sqlite3.Error:
        log.exception("运行中产线价值：market.db 卖单价读取失败")
        return 0.0
    missing = sorted(tid for tid in needs if tid not in prices)
    if missing:
        log.warning("运行中产线价值：%s 种物料没有卖单价，按 0 计（示例 %s）", len(missing), missing[:5])
    return round(sum(qty * prices.get(tid, 0.0) for tid, qty in needs.items()), 2)


def record_snapshot(wallet: float | None = None) -> dict:
    """采集当日资产快照并 upsert（同日重复覆盖，不累积）。

    Args:
        wallet: 钱包余额；None 时读 ``get_wallet_balance()``。

    Returns:
        该行 dict：``{"date", "total", "orders", "inventory", "line_value", "wallet"}``。
    """
    if wallet is None:
        wallet = get_wallet_balance()
    wallet = float(wallet)

    inventory = _inventory_value()
    orders = _orders_value()
    line_value = _line_value()
    total = round(inventory + orders + line_value + wallet, 2)

    with _default_db().connect("user") as conn:
        _ensure_schema(conn)
        conn.execute(_INSERT_SQL, (total, orders, inventory, line_value, wallet))
        row = conn.execute("SELECT snap_date FROM asset_snapshots WHERE snap_date = date('now','localtime')").fetchone()
    snap_date = row[0] if row else ""

    return {
        "date": snap_date,
        "total": total,
        "orders": orders,
        "inventory": inventory,
        "line_value": line_value,
        "wallet": wallet,
    }


def load_series(days: int = 90) -> list[dict]:
    """按日期升序返回最近 ``days`` 天内的快照序列。

    每项 ``{"date", "total", "orders", "inventory", "line_value", "wallet"}``；
    库为空时返回 ``[]``，不抛异常。
    """
    offset = f"-{max(int(days), 0)} days"
    with _default_db().connect("user") as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT snap_date, total, orders, inventory, line_value, wallet FROM asset_snapshots "
            "WHERE snap_date >= date('now','localtime', ?) ORDER BY snap_date ASC",
            (offset,),
        ).fetchall()
    return [
        {"date": r[0], "total": r[1], "orders": r[2], "inventory": r[3], "line_value": r[4], "wallet": r[5]}
        for r in rows
    ]


def adjust_wallet_balance(delta: float) -> float:
    """按订单变动增减钱包余额（返回调整后的值）。

    订单成交对钱包的影响是**一次性**的：卖单成交 +价格×剩余量、买单成交 −价格×剩余量。
    与 ``set_wallet_balance`` 分开命名，是为了让调用点的意图（增减 vs 覆盖）一眼可辨。
    """
    value = round(get_wallet_balance() + float(delta), 2)
    set_wallet_balance(value)
    return value


def get_wallet_balance() -> float:
    """wallet 线：读 settings.json 里的钱包余额；缺失/非数值一律 0.0。"""
    raw = user_settings.load_settings().get(_WALLET_KEY)
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def set_wallet_balance(value: float) -> None:
    """写回钱包余额（read-modify-write，保留 settings.json 其余键）。"""
    user_settings.save_settings({_WALLET_KEY: float(value)})
