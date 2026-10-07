"""
蓝图数据访问层 — 统一蓝图查询接口。

替代多处分散的 SELECT FROM blueprint_materials 查询。
依赖 blueprint.db 中的 blueprint_materials 表。
"""

from __future__ import annotations

import sqlite3

from domain.formulas import DEFAULT_WASTEFACTOR

#: 蓝图表查找索引。三张表虽有复合主键（自带 sqlite_autoindex），但 `blueprint_products`
#: 的查询按 product_type_id（非主键前缀）过滤，另外两张按 (blueprint_type_id, activity)
#: 过滤时计划器仍选全表扫 —— 实测 `research_cost_for_item`（仍在用的逐件路径）：
#: 无索引 3.92 ms/件 → 建索引后 0.10 ms/件（**37×**，200 件 784ms → 21ms）。
#: 归因已排除 ANALYZE：只跑统计信息、不建索引仍是 ~760 ms。
_BLUEPRINT_INDEXES = (
    ("idx_bp_materials_bp_act", "blueprint_materials", "blueprint_type_id, activity"),
    ("idx_bp_products_prod_act", "blueprint_products", "product_type_id, activity"),
    ("idx_bp_activities_bp", "blueprint_activities", "blueprint_type_id"),
)


def blueprint_index_sql() -> list[str]:
    """蓝图表索引的 CREATE 语句（导入器与 schema 迁移共用这一处定义）。"""
    return [f"CREATE INDEX IF NOT EXISTS {name} ON {table}({cols})" for name, table, cols in _BLUEPRINT_INDEXES]


def get_blueprint_materials(
    conn: sqlite3.Connection,
    blueprint_type_id: int,
    activity: str = "manufacturing",
) -> list[tuple[int, int, int]]:
    """获取蓝图所需材料列表。

    Args:
        conn: blueprint.db 的数据库连接
        blueprint_type_id: 蓝图 type_id
        activity: 活动类型（默认 'manufacturing'）

    Returns:
        [(material_type_id, quantity, wastefactor), ...]
        空列表表示无材料。
    """
    cur = conn.execute(
        """
        SELECT material_type_id, quantity, COALESCE(wastefactor, ?)
        FROM blueprint_materials
        WHERE blueprint_type_id = ? AND activity = ?
        """,
        (DEFAULT_WASTEFACTOR, blueprint_type_id, activity),
    )
    return cur.fetchall()


#: CCP 在 SDE 里塞了两张**测试蓝图**：45732「Test Reaction Blueprint / 测试反应堆蓝图」、
#: 26843「…TEST Blueprint / …测试蓝图」。它们会污染「按产物取配方」的查询：
#: 碳化钨(16672) 同时挂在 45732（20/轮）与 46207「碳化钨反应配方」（10000/轮）上，
#: 旧查询 `... LIMIT 1` 没有 ORDER BY → 命中的是测试蓝图，自制成本被算成
#: 33,818.87/件（市价 86，真实配方 ≈76.4）。所以这里**永远优先非测试蓝图**，
#: 并且按 `blueprint_type_id` 升序取 —— 同一产物多张蓝图时结果必须确定，
#: 不能随插入顺序/rowid 变。
#:
#: 注意：**不隐藏全是测试蓝图的产物**（如 26842 狂暴级部族型，SDE 里只有那张测试蓝图）——
#: 整批排除会让界面凭空少掉配方，退化成「未找到蓝图」，比显示一个可疑配方更糟。
_TEST_BLUEPRINT_SQL = "(COALESCE(i.en_name, '') LIKE 'Test %' OR COALESCE(i.zh_name, '') LIKE '%测试%')"

_RECIPE_SQL_TMPL = """
    SELECT bp.blueprint_type_id, bp.quantity, ba.time
    FROM blueprint_products bp
    JOIN blueprint_activities ba
        ON ba.blueprint_type_id = bp.blueprint_type_id
        AND ba.activity = bp.activity
    {join}
    WHERE bp.product_type_id = ? AND bp.activity = ?
    ORDER BY {order}bp.blueprint_type_id
    LIMIT 1
"""


def get_blueprint_type_for_product(
    conn: sqlite3.Connection,
    product_type_id: int,
    activity: str = "manufacturing",
) -> int | None:
    """按产物取**配方蓝图 type_id**（优先非测试蓝图，确定性）；无配方 → None。"""
    row = get_blueprint_products(conn, product_type_id, activity)
    return row[0] if row else None


def plan_output_qty(conn: sqlite3.Connection, plan: dict, *, activity: str | None = None) -> int:
    """一条产线的**总产出量** = `runs × parallels × 单轮产出`（0 轮 / 取不到配方 → 0）。

    单轮产出按计划自己的 `activity` 查（反应产物的产出挂在 `activity='reaction'` 行上），
    走 `get_blueprint_products` —— 所以同样排除 CCP 测试蓝图。
    `runs`/`parallels` 只有**字面 0** 才算「不产出」，缺失/None 兜底 1（与
    `plan_metrics.child_manufacturing_cost` 同一条规则，两处别各写一份）。
    """
    product_type_id = int(plan.get("product_type_id") or 0)
    if not product_type_id:
        return 0
    row = get_blueprint_products(conn, product_type_id, activity or str(plan.get("activity") or "manufacturing"))
    if not row:
        return 0
    per_run = int(row[1] or 0)
    runs = 1 if plan.get("runs") is None else int(plan["runs"])
    parallels = 1 if plan.get("parallels") is None else int(plan["parallels"])
    if per_run <= 0 or runs <= 0 or parallels <= 0:
        return 0
    return runs * parallels * per_run


def get_blueprint_products(
    conn: sqlite3.Connection,
    product_type_id: int,
    activity: str = "manufacturing",
) -> tuple[int, int, int] | None:
    """根据产品 type_id 查找对应的蓝图信息。

    Args:
        conn: blueprint.db 的连接（**带上 `ref` 才能排除测试蓝图**，见模块常量说明）
        product_type_id: 产品 type_id
        activity: 活动类型（默认 'manufacturing'）

    Returns:
        (blueprint_type_id, quantity, base_time) 或 None

    同一产物挂多张时：优先非测试蓝图，其次取 `blueprint_type_id` 最小的一张。
    连接里没有 `item` 表（只 attach 了 bp 库）时退化成「只按 type_id 取」——
    那种调用点应该改传 `db.connect("ref", "bp", …)`。
    """
    with_item = _RECIPE_SQL_TMPL.format(
        join="LEFT JOIN item i ON i.type_id = bp.blueprint_type_id",
        order=f"CASE WHEN {_TEST_BLUEPRINT_SQL} THEN 1 ELSE 0 END, ",
    )
    for sql in (with_item, _RECIPE_SQL_TMPL.format(join="", order="")):
        try:
            row = conn.execute(sql, (product_type_id, activity)).fetchone()
        except sqlite3.OperationalError:
            # 只吞「连接里没有 item 表」这一种：退回到不带名称过滤的确定性查询
            continue
        if row is None:
            return None
        return (int(row[0]), int(row[1]), int(row[2]))
    return None


class SqliteBlueprintReader:
    """BlueprintReader 适配 — 基于 sqlite 连接的蓝图查询（实现 domain.bom.BlueprintReader）。"""

    def __init__(self, conn):
        self._conn = conn

    def product(self, product_type_id: int, activity: str = "manufacturing") -> tuple[int, int] | None:
        row = get_blueprint_products(self._conn, product_type_id, activity)
        if row is None:
            return None
        return (row[0], row[1])  # (blueprint_type_id, per_run_output)

    def materials(self, blueprint_type_id: int, activity: str = "manufacturing") -> list[tuple[int, int, int]]:
        return get_blueprint_materials(self._conn, blueprint_type_id, activity)
