"""
库存管理数据层 — 机库 CRUD / 物品入库 / 加权平均成本 / 移动
"""
from datetime import datetime, timezone

from services.database_manager import get_db

db = get_db()

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

CREATE TABLE IF NOT EXISTS user_blueprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hangar_id INTEGER NOT NULL,
    blueprint_type_id INTEGER NOT NULL,
    is_bpo INTEGER NOT NULL DEFAULT 1,
    me_level INTEGER NOT NULL DEFAULT 0,
    te_level INTEGER NOT NULL DEFAULT 0,
    runs INTEGER NOT NULL DEFAULT 1,
    quantity INTEGER NOT NULL DEFAULT 1,
    notes TEXT DEFAULT '',
    FOREIGN KEY (hangar_id) REFERENCES hangars(id) ON DELETE CASCADE
);
"""

DEFAULT_HANGARS = ["矿仓", "组件仓", "产品仓", "通用仓库"]


def init_db():
    with db.connect("user") as conn:
        conn.executescript(SCHEMA)
        # 迁移：为旧版 user_blueprints 补加 cost_per_run 列
        try:
            conn.execute("ALTER TABLE user_blueprints ADD COLUMN cost_per_run REAL DEFAULT 0")
        except Exception:
            pass
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM hangars")
        if c.fetchone()[0] == 0:
            for name in DEFAULT_HANGARS:
                c.execute("INSERT INTO hangars (name) VALUES (?)", (name,))
            conn.commit()


def get_hangars() -> list[dict]:
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, notes FROM hangars ORDER BY id")
        return [{"id": r[0], "name": r[1], "notes": r[2]} for r in c.fetchall()]


def create_hangar(name: str) -> int:
    try:
        with db.connect("user") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO hangars (name) VALUES (?)", (name,))
            return c.lastrowid
    except Exception:
        return -1


def rename_hangar(hangar_id: int, name: str) -> bool:
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("UPDATE hangars SET name = ? WHERE id = ?", (name, hangar_id))
        return c.rowcount > 0


def delete_hangar(hangar_id: int) -> bool:
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM inventory_items WHERE hangar_id = ?", (hangar_id,))
        c.execute("DELETE FROM hangars WHERE id = ?", (hangar_id,))
        return c.rowcount > 0


def get_items(hangar_id: int) -> list[dict]:
    with db.connect("user", "ref", "mkt", "bp") as conn:
        c = conn.cursor()
        c.execute("""
            SELECT ii.id, ii.type_id, ii.quantity, ii.cost_price,
                   i.zh_name, i.en_name,
                   mp.sell_price, mp.buy_price
            FROM inventory_items ii
            LEFT JOIN ref.item i ON ii.type_id = i.type_id
            LEFT JOIN mkt.market_prices mp ON mp.type_id = i.type_id
                AND mp.region_id = 10000002
            WHERE ii.hangar_id = ?
            ORDER BY i.zh_name
        """, (hangar_id,))
        items = []
        for r in c.fetchall():
            tid = r[1]
            # 查询生产计划中该物品的规划占用
            c.execute("""
                SELECT COALESCE(SUM(bm.quantity * pp.runs * pp.parallels), 0)
                FROM production_plans pp
                JOIN bp.blueprint_products bp ON bp.product_type_id = pp.product_type_id
                    AND bp.activity = 'manufacturing'
                JOIN bp.blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
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


def get_item_price(type_id: int) -> float | None:
    with db.connect("mkt") as conn:
        c = conn.cursor()
        c.execute("SELECT sell_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1", (type_id,))
        r = c.fetchone()
        return r[0] if r else None


def add_item(hangar_id: int, type_id: int, quantity: int, cost_price: float = 0) -> int:
    if quantity <= 0:
        return -1
    with db.connect("user") as conn:
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
            return item_id
        else:
            c.execute("""INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at)
                         VALUES (?, ?, ?, ?, ?)""", (hangar_id, type_id, quantity, cost_price, now))
            return c.lastrowid


def remove_item(item_id: int) -> bool:
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        return c.rowcount > 0


def update_quantity(item_id: int, quantity: int) -> bool:
    if quantity < 0:
        return False
    with db.connect("user") as conn:
        c = conn.cursor()
        if quantity == 0:
            c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        else:
            c.execute("UPDATE inventory_items SET quantity = ? WHERE id = ?", (quantity, item_id))
        return c.rowcount > 0


def move_items(item_ids: list[int], to_hangar_id: int):
    with db.connect("user") as conn:
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


def get_total_value(hangar_id: int, price_type: str = "sell", discount: float = 0) -> dict:
    col = "sell_price" if price_type == "sell" else "buy_price"
    with db.connect("user", "mkt") as conn:
        c = conn.cursor()
        c.execute(f"""
            SELECT ii.quantity, mkt.market_prices.{col}
            FROM inventory_items ii
            LEFT JOIN mkt.market_prices ON mkt.market_prices.type_id = ii.type_id
            AND mkt.market_prices.region_id = 10000002
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


# ── 用户蓝图管理 ──

def add_blueprint(hangar_id: int, blueprint_type_id: int, is_bpo: bool = True,
                  me_level: int = 0, te_level: int = 0, runs: int = 1,
                  quantity: int = 1, notes: str = "") -> int:
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("""INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo,
                     me_level, te_level, runs, quantity, notes)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (hangar_id, blueprint_type_id, int(is_bpo), me_level, te_level, runs, quantity, notes))
        return c.lastrowid


def get_blueprints(hangar_id: int = None) -> list[dict]:
    """获取用户蓝图列表，可指定机库或全部"""
    with db.connect("user", "ref") as conn:
        c = conn.cursor()
        if hangar_id is not None:
            c.execute("""SELECT ub.id, ub.hangar_id, ub.blueprint_type_id, ub.is_bpo,
                         ub.me_level, ub.te_level, ub.runs, ub.quantity, ub.notes,
                         i.zh_name, i.en_name
                         FROM user_blueprints ub
                         LEFT JOIN ref.item i ON ub.blueprint_type_id = i.type_id
                         WHERE ub.hangar_id = ?
                         ORDER BY i.zh_name""", (hangar_id,))
        else:
            c.execute("""SELECT ub.id, ub.hangar_id, ub.blueprint_type_id, ub.is_bpo,
                         ub.me_level, ub.te_level, ub.runs, ub.quantity, ub.notes,
                         i.zh_name, i.en_name
                         FROM user_blueprints ub
                         LEFT JOIN ref.item i ON ub.blueprint_type_id = i.type_id
                         ORDER BY i.zh_name""")
        return [
            {
                "id": r[0], "hangar_id": r[1], "blueprint_type_id": r[2],
                "is_bpo": bool(r[3]), "me_level": r[4], "te_level": r[5],
                "runs": r[6], "quantity": r[7], "notes": r[8],
                "zh_name": r[9] or "", "en_name": r[10] or "",
            }
            for r in c.fetchall()
        ]


def update_blueprint(bp_id: int, **kwargs) -> bool:
    """更新蓝图属性，kwargs 可含 is_bpo, me_level, te_level, runs, quantity, notes"""
    allowed = {"is_bpo", "me_level", "te_level", "runs", "quantity", "notes", "hangar_id"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if "is_bpo" in updates:
        updates["is_bpo"] = int(updates["is_bpo"])
    with db.connect("user") as conn:
        c = conn.cursor()
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [bp_id]
        c.execute(f"UPDATE user_blueprints SET {sets} WHERE id = ?", vals)
        return c.rowcount > 0


def delete_blueprint(bp_id: int) -> bool:
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM user_blueprints WHERE id = ?", (bp_id,))
        return c.rowcount > 0


def delete_blueprints_batch(ids: list[int]) -> int:
    """批量删除蓝图，返回删除行数"""
    if not ids:
        return 0
    with db.connect("user") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM user_blueprints WHERE id IN ({placeholders})", tuple(ids))
        return c.rowcount


def move_blueprints_to_hangar(ids: list[int], hangar_id: int) -> int:
    """批量移动蓝图到目标机库"""
    if not ids:
        return 0
    with db.connect("user") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(ids))
        c.execute(f"UPDATE user_blueprints SET hangar_id = ? WHERE id IN ({placeholders})", (hangar_id, *ids))
        return c.rowcount


def update_blueprints_batch(ids: list[int], **kwargs) -> int:
    """批量更新蓝图属性（me_level, te_level, runs, cost_per_run 等）"""
    if not ids or not kwargs:
        return 0
    allowed = {"me_level", "te_level", "runs", "cost_per_run"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return 0
    with db.connect("user") as conn:
        c = conn.cursor()
        sets = ", ".join(f"{k} = ?" for k in updates)
        placeholders = ",".join("?" * len(ids))
        vals = list(updates.values()) + ids
        c.execute(f"UPDATE user_blueprints SET {sets} WHERE id IN ({placeholders})", vals)
        return c.rowcount


def get_blueprint_product_info(blueprint_type_id: int) -> dict | None:
    """获取蓝图的产物信息（名称、产量、制造时间）"""
    from core.eve_formulas import resolve_item_name
    with db.connect("bp", "ref") as conn:
        c = conn.cursor()
        c.execute("""
            SELECT bp.product_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.blueprint_type_id = ? AND bp.activity = 'manufacturing'
            LIMIT 1
        """, (blueprint_type_id,))
        row = c.fetchone()
        if not row:
            return None
        prod_id, prod_qty, base_time = row
        prod_name = resolve_item_name(c, prod_id)
        return {"product_type_id": prod_id, "product_name": prod_name,
                "product_quantity": prod_qty or 1, "base_time": base_time}


def get_blueprint_product_info_batch(bp_ids: list[int]) -> dict[int, dict]:
    """批量获取蓝图产物信息，返回 {blueprint_type_id: {product_type_id, product_name, product_quantity, base_time}}"""
    from core.eve_formulas import resolve_item_name
    if not bp_ids:
        return {}
    result = {}
    with db.connect("bp", "ref") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bp_ids))
        c.execute(f"""
            SELECT bp.blueprint_type_id, bp.product_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.blueprint_type_id IN ({placeholders}) AND bp.activity = 'manufacturing'
        """, tuple(bp_ids))
        for bpid, prod_id, prod_qty, base_time in c.fetchall():
            prod_name = resolve_item_name(c, prod_id)
            result[bpid] = {
                "product_type_id": prod_id, "product_name": prod_name,
                "product_quantity": prod_qty or 1, "base_time": base_time,
            }
    return result


def get_blueprint_materials_batch(bp_ids: list[int]) -> dict[int, list[tuple[int, int]]]:
    """批量获取蓝图材料，返回 {blueprint_type_id: [(material_type_id, quantity), ...]}"""
    if not bp_ids:
        return {}
    result: dict[int, list[tuple[int, int]]] = {bpid: [] for bpid in bp_ids}
    with db.connect("bp") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bp_ids))
        c.execute(f"""
            SELECT blueprint_type_id, material_type_id, quantity
            FROM blueprint_materials
            WHERE blueprint_type_id IN ({placeholders}) AND activity = 'manufacturing'
        """, tuple(bp_ids))
        for bpid, mid, qty in c.fetchall():
            result.setdefault(bpid, []).append((mid, qty))
    return result


def check_blueprint_exists(blueprint_type_id: int) -> bool:
    """检查用户蓝图库中是否已存在指定类型的蓝图"""
    with db.connect("user") as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_blueprints WHERE blueprint_type_id = ?", (blueprint_type_id,))
        return c.fetchone()[0] > 0


def get_blueprint_tech_levels():
    """从 reference.db 获取各蓝图的科技等级

    返回 dict[blueprint_type_id, int] — 1=T1, 2=T2, 3=T3
    """
    levels = {}
    with db.connect("bp") as conn:
        c = conn.cursor()
        # T2: 作为 invention 产物的 blueprint_type_id
        c.execute("SELECT DISTINCT product_type_id FROM blueprint_products WHERE activity = 'invention'")
        t2_ids = {r[0] for r in c.fetchall()}
        # T3: 自身为 invention 产物（从 T2 BPC 发明得到的设计图）
        c.execute("SELECT DISTINCT blueprint_type_id FROM blueprint_products WHERE activity = 'invention'")
        {r[0] for r in c.fetchall()}
        c.execute(
            "SELECT DISTINCT bp2.product_type_id FROM blueprint_products bp1"
            " JOIN blueprint_products bp2"
            " ON bp2.blueprint_type_id = bp1.product_type_id"
            " WHERE bp1.activity = 'invention' AND bp2.activity = 'invention'"
        )
        t3_ids = {r[0] for r in c.fetchall()}
        # 所有有 manufacturing 活动的蓝图
        c.execute(
            "SELECT DISTINCT blueprint_type_id"
            " FROM blueprint_activities"
            " WHERE activity IN ('manufacturing', 'reaction')"
        )
        for (bpid,) in c.fetchall():
            if bpid in t3_ids:
                levels[bpid] = 3
            elif bpid in t2_ids:
                levels[bpid] = 2
            else:
                levels[bpid] = 1
    return levels


def get_blueprint_reaction_ids() -> set[int]:
    """获取所有反应公式的 blueprint_type_id"""
    with db.connect("bp") as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT blueprint_type_id FROM blueprint_activities WHERE activity = 'reaction'")
        return {r[0] for r in c.fetchall()}
