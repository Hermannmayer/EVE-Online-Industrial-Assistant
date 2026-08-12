"""
库存管理数据层 — 机库 CRUD / 物品入库 / 加权平均成本 / 移动
"""

import json
from datetime import UTC, datetime

from core.container import get_container
from core.logger import log
from services.database_manager import DatabaseManager
from services.terminology import term


def _default_db() -> DatabaseManager:
    """惰性获取 DatabaseManager（经容器，消除模块级单例双轨）。"""
    return get_container().db


# ── Schema ──

SCHEMA = """
CREATE TABLE IF NOT EXISTS hangars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    notes TEXT DEFAULT '',
    solar_system_id INTEGER DEFAULT NULL,
    facility_type TEXT DEFAULT NULL,
    facility_tax REAL DEFAULT NULL,
    rigs TEXT DEFAULT NULL
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
    with _default_db().connect("user") as conn:
        conn.executescript(SCHEMA)
        # cost_per_run 列已由 schema_migrations user v1→v2 处理，此处不再需要
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM hangars")
        if c.fetchone()[0] == 0:
            for name in DEFAULT_HANGARS:
                c.execute("INSERT INTO hangars (name) VALUES (?)", (name,))
            conn.commit()


# 注意：蓝图名称补拉由 InitWizard「蓝图数据」步骤中的
# run_blueprint_update() 末尾自动调用 fill_missing_blueprint_names()，
# 不需要在启动时冗余触发。


def get_hangars() -> list[dict]:
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("SELECT id, name, notes, solar_system_id, facility_type, facility_tax, rigs FROM hangars ORDER BY id")
        return [
            {
                "id": r[0],
                "name": r[1],
                "notes": r[2],
                "solar_system_id": r[3],
                "facility_type": r[4],
                "facility_tax": r[5],
                "rigs": r[6],
            }
            for r in c.fetchall()
        ]


def create_hangar(name: str, solar_system_id: int | None = None) -> int:
    try:
        with _default_db().connect("user") as conn:
            c = conn.cursor()
            c.execute("INSERT INTO hangars (name, solar_system_id) VALUES (?, ?)", (name, solar_system_id))
            return c.lastrowid or 0
    except Exception:
        return -1


def rename_hangar(hangar_id: int, name: str) -> bool:
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("UPDATE hangars SET name = ? WHERE id = ?", (name, hangar_id))
        return c.rowcount > 0


def update_hangar_system(hangar_id: int, solar_system_id: int | None) -> bool:
    """设置机库所在星系（None 清除）。"""
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("UPDATE hangars SET solar_system_id = ? WHERE id = ?", (solar_system_id, hangar_id))
        return c.rowcount > 0


def get_hangar_system_id(hangar_id: int | None, *, _db: DatabaseManager | None = None) -> int | None:
    """读取机库所在星系的 solar_system_id（无机库/未设置返回 None）。"""
    if not hangar_id:
        return None
    conn_mgr = _db or _default_db()
    with conn_mgr.connect("user") as conn:
        row = conn.execute("SELECT solar_system_id FROM hangars WHERE id = ?", (hangar_id,)).fetchone()
        return row[0] if row and row[0] is not None else None


def get_hangar_name(hangar_id: int | None) -> str:
    """读取机库名称（无机库/未设置返回空串）。"""
    if not hangar_id:
        return ""
    try:
        with _default_db().connect("user") as conn:
            row = conn.execute("SELECT name FROM hangars WHERE id = ?", (hangar_id,)).fetchone()
            return row[0] if row else ""
    except Exception:
        return ""


def get_default_mat_hangar_and_system() -> tuple[int | None, int | None]:
    """返回 (默认材料机库 id, 其所在星系 id)。settings 未配置/读取失败 → (None, None)。

    供新建计划/加单写路径同时写 mat_hangar_id + solar_system_id 使用。
    星系查询失败（如 hangars 表未就绪）时降级返回 (机库 id, None)，不抛异常。
    """
    from services import user_settings

    try:
        settings = user_settings.load_settings()
    except Exception:
        return None, None
    hid = settings.get("default_mat_hangar_id")
    try:
        return hid, get_hangar_system_id(hid)
    except Exception:
        return hid, None


def get_default_mat_hangar_system_id() -> int | None:
    """从 settings.json 默认材料机库带出星系（无计划上下文的 SCI 依据）。"""
    return get_default_mat_hangar_and_system()[1]


def update_hangar_config(
    hangar_id: int,
    facility_type: str | None,
    facility_tax: float | None,
    rigs: list[int] | None,
) -> bool:
    """更新机库工业配置（设施类型/设施税/改件）。rigs 存 JSON 数组。"""
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE hangars SET facility_type=?, facility_tax=?, rigs=? WHERE id=?",
            (facility_type, facility_tax, json.dumps(rigs or []) if rigs is not None else None, hangar_id),
        )
        return c.rowcount > 0


def get_hangar_config(hangar_id: int | None) -> dict:
    """读取机库工业配置 {facility_type, facility_tax, rigs: list[int]}；无机库/未配置返回默认。"""
    default: dict = {"facility_type": None, "facility_tax": None, "rigs": []}
    if not hangar_id:
        return default
    with _default_db().connect("user") as conn:
        row = conn.execute(
            "SELECT facility_type, facility_tax, rigs FROM hangars WHERE id = ?",
            (hangar_id,),
        ).fetchone()
    if not row:
        return default
    try:
        rigs = json.loads(row[2]) if row[2] else []
        rigs = [int(r) for r in rigs] if isinstance(rigs, list) else []
    except (ValueError, TypeError):
        rigs = []
    return {"facility_type": row[0], "facility_tax": row[1], "rigs": rigs}


def delete_hangar(hangar_id: int) -> bool:
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM inventory_items WHERE hangar_id = ?", (hangar_id,))
        c.execute("DELETE FROM hangars WHERE id = ?", (hangar_id,))
        return c.rowcount > 0


def get_items(hangar_id: int) -> list[dict]:
    with _default_db().connect("user", "ref", "mkt", "bp") as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT ii.id, ii.type_id, ii.quantity, ii.cost_price,
                   i.zh_name, i.en_name,
                   mp.sell_price, mp.buy_price
            FROM inventory_items ii
            LEFT JOIN ref.item i ON ii.type_id = i.type_id
            LEFT JOIN mkt.market_prices mp ON mp.type_id = i.type_id
                AND mp.region_id = 10000002
            WHERE ii.hangar_id = ?
        """,
            (hangar_id,),
        )
        items = []
        for r in c.fetchall():
            tid = r[1]
            # 名称统一：terminology.item_overrides 优先（基础矿物 34-40 等不在 item 表，仅在此注册）
            override = term.item_override(tid)
            display_name = override or (r[4] or r[5]) or str(tid)
            # 生产计划占用：pending 为待启动预留；in_progress/ready 已物理扣减，作核对参考
            c.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN pp.status = 'pending'
                                     THEN bm.quantity * pp.runs * pp.parallels ELSE 0 END), 0),
                    COALESCE(SUM(CASE WHEN pp.status IN ('in_progress', 'ready')
                                     THEN bm.quantity * pp.runs * pp.parallels ELSE 0 END), 0)
                FROM production_plans pp
                JOIN bp.blueprint_products bp ON bp.product_type_id = pp.product_type_id
                    AND bp.activity = 'manufacturing'
                JOIN bp.blueprint_materials bm ON bm.blueprint_type_id = bp.blueprint_type_id
                    AND bm.activity = 'manufacturing'
                WHERE bm.material_type_id = ?
            """,
                (tid,),
            )
            row = c.fetchone()
            plan_qty = row[0] if row else 0
            plan_active = row[1] if row else 0

            stock_qty = r[2]
            remain = max(0, stock_qty - plan_qty)

            items.append(
                {
                    "id": r[0],
                    "type_id": tid,
                    "quantity": stock_qty,
                    "cost_price": r[3] or 0,
                    "zh_name": r[4] or "",
                    "en_name": r[5] or "",
                    "display_name": display_name,
                    "sell_price": r[6],
                    "buy_price": r[7],
                    "plan_usage": plan_qty,
                    "plan_active": plan_active,
                    "plan_remain": remain,
                }
            )
        # 名称排序（terminology 覆盖项 SQL 无法排序，Python 端统一排）
        items.sort(key=lambda it: it["display_name"])
        # 研究成本（拷贝/发明）批量填充 — 蓝图表在 blueprint.db；SCI 跟随该机库所在星系
        try:
            from services.research_calculator import research_costs_batch

            sys_id = get_hangar_system_id(hangar_id)
            with _default_db().connect("bp") as bp_conn:
                costs = research_costs_batch(bp_conn, [it["type_id"] for it in items], solar_system_id=sys_id)
            for it in items:
                it["research_cost"] = costs.get(it["type_id"])
        except Exception:
            log.exception("计算研究成本失败")
        return items


def get_item_price(type_id: int) -> float | None:
    with _default_db().connect("mkt") as conn:
        c = conn.cursor()
        c.execute("SELECT sell_price FROM market_prices WHERE type_id = ? AND region_id = 10000002 LIMIT 1", (type_id,))
        r = c.fetchone()
        return r[0] if r else None


def get_inventory_cost_map(_db: DatabaseManager | None = None) -> dict[int, tuple[int, float]]:
    """跨机库汇总各物品库存数量与加权平均成本（成本按数量加权）。

    零成本库存（cost_price 为 0 或 NULL）也计入库存，加权成本按 0 处理；
    quantity <= 0 的行不计入（视为无库存）。

    Args:
        _db: 可选注入的 DatabaseManager（便于测试）；None 时用模块级单例。

    Returns:
        {type_id: (总数量, 加权平均成本)}，仅含 quantity > 0 的物品。
    """
    conn_mgr = _db or _default_db()
    result: dict[int, tuple[int, float]] = {}
    with conn_mgr.connect("user") as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT type_id,
                   SUM(quantity) AS total_qty,
                   SUM(quantity * COALESCE(cost_price, 0)) / NULLIF(SUM(quantity), 0) AS avg_cost
            FROM inventory_items
            WHERE quantity > 0
            GROUP BY type_id
            """
        )
        for tid, qty, cost in c.fetchall():
            result[int(tid)] = (int(qty), float(cost or 0))
    return result


def add_item(hangar_id: int, type_id: int, quantity: int, cost_price: float = 0, *, conn=None) -> int:
    """把 quantity 件物品加入机库，按加权平均成本合并。

    conn: 可选注入的连接——调用方持有事务时传入，在同一连接上执行且**不提交**，
    由调用方统一 commit/rollback；None 时用缓存连接并自动提交。
    """
    if quantity <= 0:
        return -1
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

    def _do(c) -> int:
        row = c.execute(
            "SELECT id, quantity, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
            (hangar_id, type_id),
        ).fetchone()
        if row:
            item_id, old_qty, old_cost = row
            old_cost = old_cost or 0
            total_qty = old_qty + quantity
            avg_cost = (old_qty * old_cost + quantity * cost_price) / total_qty if total_qty > 0 else 0
            c.execute(
                "UPDATE inventory_items SET quantity = ?, cost_price = ?, created_at = ? WHERE id = ?",
                (total_qty, round(avg_cost, 2), now, item_id),
            )
            return int(item_id)
        cur = c.execute(
            """INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at)
                     VALUES (?, ?, ?, ?, ?)""",
            (hangar_id, type_id, quantity, cost_price, now),
        )
        return cur.lastrowid or 0

    if conn is not None:
        return _do(conn)
    with _default_db().connect("user") as conn:
        return _do(conn)


def set_item_quantity(
    hangar_id: int,
    type_id: int,
    quantity: int,
    cost_price: float | None = None,
    *,
    conn=None,
) -> int:
    """全量同步：把 (hangar_id, type_id) 的数量设为 quantity。

    quantity <= 0 时删除该行；cost_price 传入则覆盖单位成本，否则保留现值
    （新行默认 0）。供「剪贴板全量导入」覆盖机库数量用。

    conn: 可选注入的连接——调用方持有事务时传入，在同一连接上执行且**不提交**；
    None 时用缓存连接并自动提交。返回受影响 item_id（删除/未命中返回 0）。
    """
    if quantity < 0:
        return 0

    def _do(c) -> int:
        row = c.execute(
            "SELECT id, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
            (hangar_id, type_id),
        ).fetchone()
        if quantity == 0:
            if row:
                c.execute("DELETE FROM inventory_items WHERE id = ?", (row[0],))
                return int(row[0])
            return 0
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        new_cost = cost_price if cost_price is not None else ((row[1] or 0) if row else 0)
        if row:
            c.execute(
                "UPDATE inventory_items SET quantity = ?, cost_price = ?, created_at = ? WHERE id = ?",
                (quantity, round(new_cost, 2), now, row[0]),
            )
            return int(row[0])
        cur = c.execute(
            """INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at)
                     VALUES (?, ?, ?, ?, ?)""",
            (hangar_id, type_id, quantity, new_cost, now),
        )
        return cur.lastrowid or 0

    if conn is not None:
        return _do(conn)
    with _default_db().connect("user") as conn:
        return _do(conn)


def update_cost_price(item_id: int, cost_price: float) -> bool:
    """直接覆盖该库存行的单位成本价（参数化 UPDATE，返回是否命中）。"""
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("UPDATE inventory_items SET cost_price = ? WHERE id = ?", (round(cost_price, 2), item_id))
        return c.rowcount > 0


def get_hangar_stock(hangar_id: int) -> dict[int, int]:
    """单机库库存快照 {type_id: quantity}（quantity > 0 才计入）。

    供「启动生产计划」材料校验/扣减使用。
    """
    result: dict[int, int] = {}
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute(
            "SELECT type_id, quantity FROM inventory_items WHERE hangar_id = ? AND quantity > 0",
            (hangar_id,),
        )
        for tid, qty in c.fetchall():
            result[int(tid)] = int(qty)
    return result


def get_hangar_cost_map(hangar_id: int) -> dict[int, float]:
    """单机库物品成本快照 {type_id: 加权平均成本}。

    轻量单查询（不走 get_items 的 N+1），供撤销启动返还时按原成本回补、避免稀释。
    """
    result: dict[int, float] = {}
    with _default_db().connect("user") as conn:
        rows = conn.execute(
            "SELECT type_id, cost_price FROM inventory_items WHERE hangar_id = ?",
            (hangar_id,),
        ).fetchall()
        for tid, cost in rows:
            result[int(tid)] = float(cost or 0)
    return result


def deduct_item(hangar_id: int, type_id: int, quantity: int, *, conn=None) -> int:
    """从机库扣减 quantity，返回实际扣减量。

    不足则扣到 0（不跨负、不报错）；扣减后余量为 0 则删除该行。
    扣减不改变成本价（加权平均成本仅在 add_item 时变动）。

    conn: 可选注入的连接——调用方持有事务时传入，在同一连接上执行且**不提交**，
    由调用方统一 commit/rollback；None 时用缓存连接并提交。
    """
    if quantity <= 0:
        return 0

    def _do(c) -> int:
        row = c.execute(
            "SELECT id, quantity FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
            (hangar_id, type_id),
        ).fetchone()
        if not row:
            return 0
        item_id, cur = row
        deducted = min(int(cur), quantity)
        remaining = int(cur) - deducted
        if remaining <= 0:
            c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        else:
            c.execute("UPDATE inventory_items SET quantity = ? WHERE id = ?", (remaining, item_id))
        return deducted

    if conn is not None:
        return _do(conn)
    with _default_db().connect("user") as conn:
        deducted = _do(conn)
        conn.commit()
        return deducted


def remove_item(item_id: int) -> bool:
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        return c.rowcount > 0


def update_quantity(item_id: int, quantity: int) -> bool:
    if quantity < 0:
        return False
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        if quantity == 0:
            c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        else:
            c.execute("UPDATE inventory_items SET quantity = ? WHERE id = ?", (quantity, item_id))
        return c.rowcount > 0


def move_items(item_ids: list[int], to_hangar_id: int):
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        for item_id in item_ids:
            c.execute("SELECT hangar_id, type_id, quantity, cost_price FROM inventory_items WHERE id = ?", (item_id,))
            row = c.fetchone()
            if not row or row[0] == to_hangar_id:
                continue
            _, type_id, qty, cost = row
            c.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
            c.execute(
                "SELECT id, quantity, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
                (to_hangar_id, type_id),
            )
            existing = c.fetchone()
            if existing:
                tid, old_q, old_c = existing
                old_c = old_c or 0
                total_q = old_q + qty
                avg_cost = (old_q * old_c + qty * cost) / total_q if total_q > 0 else 0
                c.execute(
                    "UPDATE inventory_items SET quantity = ?, cost_price = ? WHERE id = ?",
                    (total_q, round(avg_cost, 2), tid),
                )
            else:
                c.execute(
                    """INSERT INTO inventory_items (hangar_id, type_id, quantity, cost_price, created_at)
                             VALUES (?, ?, ?, ?, datetime('now'))""",
                    (to_hangar_id, type_id, qty, cost),
                )


def move_quantity(from_hangar_id: int, type_id: int, quantity: int, to_hangar_id: int) -> int:
    """按数量把物品从源机库移到目标机库，成本沿用源库单位成本。

    剪贴板数量超过源库现有量时按源库现有量扣减（clamp，不报错）；
    源库行扣空则删除；目标库合并走 add_item 加权平均。同一事务内完成。
    Returns: 实际移动数量（源库无该物品/数量<=0/同库返回 0）。
    """
    if quantity <= 0 or from_hangar_id == to_hangar_id:
        return 0
    with _default_db().connect("user") as conn:
        row = conn.execute(
            "SELECT quantity, cost_price FROM inventory_items WHERE hangar_id = ? AND type_id = ?",
            (from_hangar_id, type_id),
        ).fetchone()
        if not row:
            return 0
        cost = row[1] or 0
        deducted = deduct_item(from_hangar_id, type_id, quantity, conn=conn)
        if deducted > 0:
            add_item(to_hangar_id, type_id, deducted, cost, conn=conn)
        return deducted


def get_total_value(hangar_id: int, price_type: str = "sell", discount: float = 0) -> dict:
    col = "sell_price" if price_type == "sell" else "buy_price"
    with _default_db().connect("user", "mkt") as conn:
        c = conn.cursor()
        c.execute(
            f"""
            SELECT ii.quantity, mkt.market_prices.{col}
            FROM inventory_items ii
            LEFT JOIN mkt.market_prices ON mkt.market_prices.type_id = ii.type_id
            AND mkt.market_prices.region_id = 10000002
            WHERE ii.hangar_id = ?
        """,
            (hangar_id,),
        )
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


def add_blueprint(
    hangar_id: int,
    blueprint_type_id: int,
    is_bpo: bool = True,
    me_level: int = 0,
    te_level: int = 0,
    runs: int = 1,
    quantity: int = 1,
    notes: str = "",
    *,
    conn=None,
) -> int:
    """新增蓝图。conn 传入时在同一连接执行且不提交（由调用方统一事务）。"""

    def _do(c) -> int:
        cur = c.execute(
            """INSERT INTO user_blueprints (hangar_id, blueprint_type_id, is_bpo,
                     me_level, te_level, runs, quantity, notes)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (hangar_id, blueprint_type_id, int(is_bpo), me_level, te_level, runs, quantity, notes),
        )
        return cur.lastrowid or 0

    if conn is not None:
        return _do(conn)
    with _default_db().connect("user") as conn:
        return _do(conn)


def get_blueprints(hangar_id: int | None = None) -> list[dict]:
    """获取用户蓝图列表，可指定机库或全部"""
    with _default_db().connect("user", "ref") as conn:
        c = conn.cursor()
        if hangar_id is not None:
            c.execute(
                """SELECT ub.id, ub.hangar_id, ub.blueprint_type_id, ub.is_bpo,
                         ub.me_level, ub.te_level, ub.runs, ub.quantity, ub.notes,
                         i.zh_name, i.en_name
                         FROM user_blueprints ub
                         LEFT JOIN ref.item i ON ub.blueprint_type_id = i.type_id
                         WHERE ub.hangar_id = ?
                         ORDER BY i.zh_name""",
                (hangar_id,),
            )
        else:
            c.execute("""SELECT ub.id, ub.hangar_id, ub.blueprint_type_id, ub.is_bpo,
                         ub.me_level, ub.te_level, ub.runs, ub.quantity, ub.notes,
                         i.zh_name, i.en_name
                         FROM user_blueprints ub
                         LEFT JOIN ref.item i ON ub.blueprint_type_id = i.type_id
                         ORDER BY i.zh_name""")
        return [
            {
                "id": r[0],
                "hangar_id": r[1],
                "blueprint_type_id": r[2],
                "is_bpo": bool(r[3]),
                "me_level": r[4],
                "te_level": r[5],
                "runs": r[6],
                "quantity": r[7],
                "notes": r[8],
                "zh_name": r[9] or "",
                "en_name": r[10] or "",
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
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        sets = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [bp_id]
        c.execute(f"UPDATE user_blueprints SET {sets} WHERE id = ?", vals)
        return c.rowcount > 0


def delete_blueprint(bp_id: int, *, conn=None) -> bool:
    """删除蓝图。conn 传入时在同一连接执行且不提交（由调用方统一事务）。"""

    def _do(c) -> bool:
        cur = c.execute("DELETE FROM user_blueprints WHERE id = ?", (bp_id,))
        return bool(cur.rowcount > 0)

    if conn is not None:
        return _do(conn)
    with _default_db().connect("user") as conn:
        return _do(conn)


def delete_blueprints_batch(ids: list[int]) -> int:
    """批量删除蓝图，返回删除行数"""
    if not ids:
        return 0
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(ids))
        c.execute(f"DELETE FROM user_blueprints WHERE id IN ({placeholders})", tuple(ids))
        return c.rowcount


def move_blueprints_to_hangar(ids: list[int], hangar_id: int) -> int:
    """批量移动蓝图到目标机库"""
    if not ids:
        return 0
    with _default_db().connect("user") as conn:
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
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        sets = ", ".join(f"{k} = ?" for k in updates)
        placeholders = ",".join("?" * len(ids))
        vals = list(updates.values()) + ids
        c.execute(f"UPDATE user_blueprints SET {sets} WHERE id IN ({placeholders})", vals)
        return c.rowcount


def get_blueprint_product_info(blueprint_type_id: int) -> dict | None:
    """获取蓝图的产物信息（名称、产量、制造时间）"""
    from core.eve_formulas import resolve_item_name

    with _default_db().connect("bp", "ref") as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT bp.product_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.blueprint_type_id = ? AND bp.activity = 'manufacturing'
            LIMIT 1
        """,
            (blueprint_type_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        prod_id, prod_qty, base_time = row
        prod_name = resolve_item_name(c, prod_id)
        return {
            "product_type_id": prod_id,
            "product_name": prod_name,
            "product_quantity": prod_qty or 1,
            "base_time": base_time,
        }


def get_blueprint_product_info_batch(bp_ids: list[int]) -> dict[int, dict]:
    """批量获取蓝图产物信息，返回 {blueprint_type_id: {product_type_id, product_name, product_quantity, base_time}}"""
    from core.eve_formulas import resolve_item_name

    if not bp_ids:
        return {}
    result = {}
    with _default_db().connect("bp", "ref") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bp_ids))
        c.execute(
            f"""
            SELECT bp.blueprint_type_id, bp.product_type_id, bp.quantity, ba.time
            FROM blueprint_products bp
            JOIN blueprint_activities ba ON ba.blueprint_type_id = bp.blueprint_type_id
                AND ba.activity = bp.activity
            WHERE bp.blueprint_type_id IN ({placeholders}) AND bp.activity = 'manufacturing'
        """,
            tuple(bp_ids),
        )
        for bpid, prod_id, prod_qty, base_time in c.fetchall():
            prod_name = resolve_item_name(c, prod_id)
            result[bpid] = {
                "product_type_id": prod_id,
                "product_name": prod_name,
                "product_quantity": prod_qty or 1,
                "base_time": base_time,
            }
    return result


def get_blueprint_materials_batch(bp_ids: list[int]) -> dict[int, list[tuple[int, int]]]:
    """批量获取蓝图材料，返回 {blueprint_type_id: [(material_type_id, quantity), ...]}"""
    if not bp_ids:
        return {}
    result: dict[int, list[tuple[int, int]]] = {bpid: [] for bpid in bp_ids}
    with _default_db().connect("bp") as conn:
        c = conn.cursor()
        placeholders = ",".join("?" * len(bp_ids))
        c.execute(
            f"""
            SELECT blueprint_type_id, material_type_id, quantity
            FROM blueprint_materials
            WHERE blueprint_type_id IN ({placeholders}) AND activity = 'manufacturing'
        """,
            tuple(bp_ids),
        )
        for bpid, mid, qty in c.fetchall():
            result.setdefault(bpid, []).append((mid, qty))
    return result


def check_blueprint_exists(blueprint_type_id: int) -> bool:
    """检查用户蓝图库中是否已存在指定类型的蓝图"""
    with _default_db().connect("user") as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_blueprints WHERE blueprint_type_id = ?", (blueprint_type_id,))
        return bool(c.fetchone()[0])


def get_blueprint_tech_levels():
    """从 reference.db 获取各蓝图的科技等级

    返回 dict[blueprint_type_id, int] — 1=T1, 2=T2, 3=T3
    """
    levels = {}
    with _default_db().connect("bp") as conn:
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
    with _default_db().connect("bp") as conn:
        c = conn.cursor()
        c.execute("SELECT DISTINCT blueprint_type_id FROM blueprint_activities WHERE activity = 'reaction'")
        return {r[0] for r in c.fetchall()}
