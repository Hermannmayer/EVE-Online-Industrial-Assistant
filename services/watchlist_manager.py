"""
关注列表数据层 — 价格监控 CRUD / 阈值设置 / 价格变化检测
"""

from core.container import get_container
from services.database_manager import DatabaseManager


def _db() -> DatabaseManager:
    """惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。"""
    return get_container().db


# ── Schema ──

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL DEFAULT 10000002,
    note TEXT,
    price_threshold_buy REAL,
    price_threshold_sell REAL,
    last_buy_price REAL,
    last_sell_price REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db():
    """初始化关注列表表"""
    with _db().connect("user") as conn:
        conn.executescript(SCHEMA)


# ── CRUD ──


def add_to_watchlist(
    type_id: int,
    region_id: int = 10000002,
    note: str = "",
    buy_threshold: float | None = None,
    sell_threshold: float | None = None,
) -> int:
    """添加物品到关注列表，返回新记录 id"""
    with _db().connect("user") as conn:
        c = conn.cursor()
        # 检查是否已存在
        c.execute(
            "SELECT id FROM watchlist_items WHERE type_id = ? AND region_id = ?",
            (type_id, region_id),
        )
        existing = c.fetchone()
        if existing:
            return int(existing[0])
        c.execute(
            """INSERT INTO watchlist_items
               (type_id, region_id, note, price_threshold_buy, price_threshold_sell)
               VALUES (?, ?, ?, ?, ?)""",
            (type_id, region_id, note, buy_threshold, sell_threshold),
        )
        conn.commit()
        return c.lastrowid or 0


def remove_from_watchlist(item_id: int) -> bool:
    """删除关注列表中的物品"""
    with _db().connect("user") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM watchlist_items WHERE id = ?", (item_id,))
        conn.commit()
        return c.rowcount > 0


def get_watchlist() -> list[dict]:
    """获取所有关注物品，JOIN item 表获取名称和市场价格"""
    with _db().connect("user", "ref", "mkt") as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT wi.id, wi.type_id, wi.region_id, wi.note,
                   wi.price_threshold_buy, wi.price_threshold_sell,
                   wi.last_buy_price, wi.last_sell_price,
                   wi.created_at, wi.updated_at,
                   i.zh_name, i.en_name,
                   mp.buy_price, mp.sell_price
            FROM watchlist_items wi
            LEFT JOIN ref.item i ON wi.type_id = i.type_id
            LEFT JOIN mkt.market_prices mp ON mp.type_id = wi.type_id
                AND mp.region_id = wi.region_id
                AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices
                                     WHERE type_id = wi.type_id AND region_id = wi.region_id)
            ORDER BY i.zh_name
            """
        )
        items = []
        for r in c.fetchall():
            buy_price = r[12]
            sell_price = r[13]
            items.append(
                {
                    "id": r[0],
                    "type_id": r[1],
                    "region_id": r[2],
                    "note": r[3] or "",
                    "buy_threshold": r[4],
                    "sell_threshold": r[5],
                    "last_buy_price": r[6],
                    "last_sell_price": r[7],
                    "created_at": r[8],
                    "updated_at": r[9],
                    "zh_name": r[10] or "",
                    "en_name": r[11] or "",
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                }
            )
        return items


def update_watchlist_item(
    item_id: int,
    note: str | None = None,
    buy_threshold: float | None = None,
    sell_threshold: float | None = None,
) -> bool:
    """更新关注物品的备注或阈值"""
    from datetime import UTC, datetime

    updates: dict[str, object] = {}
    if note is not None:
        updates["note"] = note
    if buy_threshold is not None:
        updates["price_threshold_buy"] = buy_threshold
    if sell_threshold is not None:
        updates["price_threshold_sell"] = sell_threshold
    if not updates:
        return False
    # 用 Python 时间戳（参数化写入），不能把字符串 "datetime('now')" 当值存进去
    updates["updated_at"] = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    with _db().connect("user") as conn:
        c = conn.cursor()
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [item_id]
        c.execute(f"UPDATE watchlist_items SET {sets} WHERE id = ?", vals)
        conn.commit()
        return c.rowcount > 0


def check_price_changes() -> list[dict]:
    """遍历关注列表，对比当前 market_prices 与上次记录的价格。
    返回有变化的物品列表：[(type_id, 名称, 原买价, 新买价, 原卖价, 新卖价), ...]
    同时更新 last_buy_price / last_sell_price。
    """
    with _db().connect("user", "ref", "mkt") as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT wi.id, wi.type_id, wi.region_id, wi.last_buy_price, wi.last_sell_price,
                   mp.buy_price, mp.sell_price, i.zh_name
            FROM watchlist_items wi
            LEFT JOIN mkt.market_prices mp ON mp.type_id = wi.type_id
                AND mp.region_id = wi.region_id
                AND mp.fetch_time = (SELECT MAX(fetch_time) FROM mkt.market_prices
                                     WHERE type_id = wi.type_id AND region_id = wi.region_id)
            LEFT JOIN ref.item i ON wi.type_id = i.type_id
            """
        )
        changes = []
        now = "datetime('now')"
        for row in c.fetchall():
            w_id, type_id, region_id, old_buy, old_sell, new_buy, new_sell, name = row
            new_buy = new_buy or 0
            new_sell = new_sell or 0
            old_buy = old_buy or 0
            old_sell = old_sell or 0
            has_change = False
            if (old_buy and new_buy and abs(new_buy - old_buy) > 0.01) or (
                old_sell and new_sell and abs(new_sell - old_sell) > 0.01
            ):
                changes.append(
                    {
                        "type_id": type_id,
                        "name": name or str(type_id),
                        "old_buy": old_buy,
                        "new_buy": new_buy,
                        "old_sell": old_sell,
                        "new_sell": new_sell,
                    }
                )
                has_change = True
            # 更新快照价格
            if has_change or old_buy == 0:
                c.execute(
                    f"UPDATE watchlist_items SET last_buy_price = ?, "
                    f"last_sell_price = ?, updated_at = {now} WHERE id = ?",
                    (new_buy, new_sell, w_id),
                )
        conn.commit()
        return changes
