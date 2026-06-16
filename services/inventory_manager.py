"""
库存管理数据层 — 机库 CRUD / 物品入库 / 加权平均成本 / 移动
"""
import sqlite3
from datetime import datetime, timezone

from core.paths import DB_PATH

# ── Schema ──

SCHEMA = """
CREATE TABLE IF NOT EXISTS hangars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hangar_id INTEGER NOT NULL,
    type_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    cost_price REAL DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (hangar_id) REFERENCES hangars(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_item ON inventory_items(hangar_id, type_id);
"""

DEFAULT_HANGARS = ["矿仓", "组件仓", "产品仓", "通用仓库"]


def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM hangars")
        if c.fetchone()[0] == 0:
            for name in DEFAULT_HANGARS:
                c.execute("INSERT INTO hangars (name) VALUES (?)", (name,))
            conn.commit()
    finally:
        conn.close()


def get_hangars() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, notes FROM hangars ORDER BY id")
        return [{"id": r[0], "name": r[1], "notes": r[2]} for r in c.fetchall()]
    finally:
        conn.close()


def create_hangar(name: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("INSERT INTO hangars (name) VALUES (?)", (name,))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return -1
    finally:
        conn.close()


def rename_hangar(hangar_id: int, name: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("UPDATE hangars SET name = ? WHERE id = ?", (name, hangar_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def delete_hangar(hangar_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("DELETE FROM inventory_items WHERE hangar_id = ?", (hangar_id,))
        c.execute("DELETE FROM hangars WHERE id = ?", (hangar_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def get_items(hangar_id: int) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("""
            SELECT ii.id, ii.type_id, ii.quantity, ii.cost_price,
                   i.zh_name, i.en_name,
                   mp.sell_price, mp.buy_price
            FROM inventory_items ii
            LEFT JOIN item i ON ii.type_id = i.type_id
            LEFT JOIN market_prices mp ON mp.type_id = i.type_id
                AND mp.region_id = 10000002
            WHERE ii.hangar_id = ?
            ORDER BY i.zh_name
        """, (hangar_id,))
        items = []
        for r in c.fetchall():
            tid = r[1]
            # 查询生产计划中该物品的规划占用
            plan_qty = 0
            c.execute("""
                SELECT COALESCE(SUM(bm.quantity * pp.runs * pp.parallels), 0)
                FROM production_plans pp
                JOIN blueprint_products bp ON bp.product_type_id = pp.product_type_id
                    AND bp.activity = 'manufacturing'
                JOIN blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                    AND bm.activity = 'manufacturing'
                WHERE bm.material_type_id = ? AND pp.status IN ('pending', 'running')
            """, (tid,))
            row = c.fetchone()
            plan_qty = row[0] if row else 0

            stock_qty = r[2]
            remain = max(0, stock_qty - plan_qty)

            items.append({
                "id": r[0], "type_id": tid,
                "quantity": stock_qty,
                "cost_price": r[3] or 0,
                "zh_name": r[4] or "", "en_name": r[5] or "",
                "sell_price": r[6], "buy_price": r[7],
                "plan_usage": plan_qty,
                "plan_remain": remain,
            })
        return items
    finally:
        conn.close()


def get_item_price(type_id: int) -> float | None:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("SELECT sell_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1", (type_id,))
        r = c.fetchone()
        return r[0] if r else None
    finally:
        conn.close()


def add_item(hangar_id: int, type_id: int, quantity: int, cost_price: float = 0) -> int:
    if quantity <= 0:
        return -1
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        c.execute("SELECT id, quantity, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
                  (hangar_id, type_id))
        row = c.fetchone()
        if row:
            item_id, old_qty, old_cost = row
            old_cost = old_cost or 0
            total_qty = old_qty + quantity
            avg_cost = (old_qty * old_cost + quantity * cost_price) / total_qty if total_qty > 0 else 0
            c.execute("UPDATE inventory_items SET quantity = ?, cost_price = ?, created_at = ? WHERE id = ?",
                      (total_qty, round(avg_cost, 2), now, item_id))
            conn.commit()
            return item_id
        else:
            c.execute("""INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at)
                         VALUES (?, ?, ?, ?, ?)""", (hangar_id, type_id, quantity, cost_price, now))
            conn.commit()
            return c.lastrowid
    finally:
        conn.close()


def remove_item(item_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def update_quantity(item_id: int, quantity: int) -> bool:
    if quantity < 0:
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        if quantity == 0:
            c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        else:
            c.execute("UPDATE inventory_items SET quantity = ? WHERE id = ?", (quantity, item_id))
        conn.commit()
        return c.rowcount > 0
    finally:
        conn.close()


def move_items(item_ids: list[int], to_hangar_id: int):
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        for item_id in item_ids:
            c.execute("SELECT hangar_id, type_id, quantity, cost_price FROM inventory_items WHERE id = ?", (item_id,))
            row = c.fetchone()
            if not row or row[0] == to_hangar_id:
                continue
            _, type_id, qty, cost = row
            c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
            c.execute("SELECT id, quantity, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
                      (to_hangar_id, type_id))
            existing = c.fetchone()
            if existing:
                tid, old_q, old_c = existing
                old_c = old_c or 0
                total_q = old_q + qty
                avg_cost = (old_q * old_c + qty * cost) / total_q if total_q > 0 else 0
                c.execute("UPDATE inventory_items SET quantity = ?, cost_price = ? WHERE id = ?",
                          (total_q, round(avg_cost, 2), tid))
            else:
                c.execute("""INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at)
                             VALUES (?, ?, ?, ?, datetime('now'))""", (to_hangar_id, type_id, qty, cost))
        conn.commit()
    finally:
        conn.close()


def get_total_value(hangar_id: int, price_type: str = "sell", discount: float = 0) -> dict:
    col = "sell_price" if price_type == "sell" else "buy_price"
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        c.execute(f"""
            SELECT ii.quantity, mp.{col}
            FROM inventory_items ii
            LEFT JOIN market_prices mp ON mp.type_id = ii.type_id AND mp.region_id = 10000002
            WHERE ii.hangar_id = ?
        """, (hangar_id,))
        total = 0
        count = 0
        for qty, price in c.fetchall():
            if price:
                total += qty * price
                count += 1
        factor = (100 - discount) / 100
        return {
            "market_total": round(total, 2),
            "discounted_total": round(total * factor, 2),
            "discount": discount,
            "items_with_price": count,
        }
    finally:
        conn.close()
