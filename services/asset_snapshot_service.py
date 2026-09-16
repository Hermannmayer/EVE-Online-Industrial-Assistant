"""物品查询页空闲态仪表盘 —— 资产快照采集/查询与钱包余额读写。

纯服务层（无 Qt）。资产折线图的数据源，4 条线取数来源如下（勿再猜）：

- ``inventory``（库存材料金额）= 遍历全部机库求和
  ``inventory_manager.get_total_value(hangar_id, price_type="sell")["market_total"]``
- ``orders``（挂单金额）= ``SELECT SUM(price * volume_remain) FROM open_orders``
- ``wallet``（钱包余额）= ``get_wallet_balance()``（settings.json，用户手填）
- ``total``（总资产）= ``inventory + orders + wallet``

每天一行（``asset_snapshots.snap_date`` 唯一），当天重复记录覆盖不累积。
日期一律由 **SQLite 侧** ``date('now','localtime')`` 决定（与
``schema_migrations.price_snapshots.snapshot_time`` 同源），不混用 Python 的
``date.today()`` —— 二者跨时区/跨零点会给出不同日期，而 upsert 冲突键正是这一列。

基线表（``asset_snapshots`` / ``open_orders``）既由 schema 迁移（v16→v17，
``services/schema_migrations._USER_V17_TABLES_SQL``）创建给存量库，也在本模块入口
``CREATE TABLE IF NOT EXISTS`` 兜底给测试/新库 —— 复用 ``inventory_manager.SCHEMA``
的既有约定，两边都用 ``IF NOT EXISTS``，重复执行幂等。
``ALTER TABLE`` 不在此处，仍只走迁移。
"""

from __future__ import annotations

from core.container import get_container
from services import inventory_manager, user_settings
from services.database_manager import DatabaseManager

# 基线表 DDL（与 services.schema_migrations._USER_V17_TABLES_SQL 保持一致）
SCHEMA = """
CREATE TABLE IF NOT EXISTS asset_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snap_date TEXT NOT NULL UNIQUE,          -- YYYY-MM-DD（本地日期），每天一行
    total REAL DEFAULT 0,                    -- 总资产（库存 + 挂单 + 钱包）
    orders REAL DEFAULT 0,                   -- 挂单金额（卖单按 sell 价、买单按 buy 价）
    inventory REAL DEFAULT 0,                -- 库存材料金额
    wallet REAL DEFAULT 0,                   -- 钱包余额（用户手填）
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
"""

# 钱包余额在 settings.json 里的键
_WALLET_KEY = "wallet_balance"

_INSERT_SQL = """
INSERT INTO asset_snapshots (snap_date, total, orders, inventory, wallet)
VALUES (date('now','localtime'), ?, ?, ?, ?)
ON CONFLICT(snap_date) DO UPDATE SET
    total = excluded.total,
    orders = excluded.orders,
    inventory = excluded.inventory,
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


def record_snapshot(wallet: float | None = None) -> dict:
    """采集当日资产快照并 upsert（同日重复覆盖，不累积）。

    Args:
        wallet: 钱包余额；None 时读 ``get_wallet_balance()``。

    Returns:
        该行 dict：``{"date", "total", "orders", "inventory", "wallet"}``。
    """
    if wallet is None:
        wallet = get_wallet_balance()
    wallet = float(wallet)

    inventory = _inventory_value()
    orders = _orders_value()
    total = round(inventory + orders + wallet, 2)

    with _default_db().connect("user") as conn:
        _ensure_schema(conn)
        conn.execute(_INSERT_SQL, (total, orders, inventory, wallet))
        row = conn.execute(
            "SELECT snap_date FROM asset_snapshots WHERE snap_date = date('now','localtime')"
        ).fetchone()
    snap_date = row[0] if row else ""

    return {"date": snap_date, "total": total, "orders": orders, "inventory": inventory, "wallet": wallet}


def load_series(days: int = 90) -> list[dict]:
    """按日期升序返回最近 ``days`` 天内的快照序列。

    每项 ``{"date", "total", "orders", "inventory", "wallet"}``；
    库为空时返回 ``[]``，不抛异常。
    """
    offset = f"-{max(int(days), 0)} days"
    with _default_db().connect("user") as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT snap_date, total, orders, inventory, wallet FROM asset_snapshots "
            "WHERE snap_date >= date('now','localtime', ?) ORDER BY snap_date ASC",
            (offset,),
        ).fetchall()
    return [
        {"date": r[0], "total": r[1], "orders": r[2], "inventory": r[3], "wallet": r[4]}
        for r in rows
    ]


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
