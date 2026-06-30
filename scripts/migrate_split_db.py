"""
数据库拆分迁移脚本 — 将旧的 items.db 拆分为三个独立数据库

用法:
    python scripts/migrate_split_db.py

从单个 items.db 导出数据到:
    - reference.db  (item, market_tree, blueprint_*, industry_*, item_dogma)
    - market.db     (market_prices, market_volume_snapshots)
    - user.db       (hangars, inventory_items, production_plans, user_skills)
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import log
from core.paths import MKT_DB_PATH, REF_DB_PATH, USR_DB_PATH, database_path

# ── Schema 定义 ──

REFERENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS item (
    type_id INTEGER PRIMARY KEY,
    en_name TEXT,
    zh_name TEXT,
    group_id INTEGER,
    en_group_name TEXT,
    zh_group_name TEXT,
    market_group_id INTEGER,
    en_market_group_name TEXT,
    zh_market_group_name TEXT,
    volume REAL,
    iconID INTEGER
);

CREATE TABLE IF NOT EXISTS market_tree (
    market_group_id INTEGER PRIMARY KEY,
    parent_group_id INTEGER,
    en_name TEXT,
    zh_name TEXT,
    icon_id INTEGER
);

CREATE TABLE IF NOT EXISTS blueprint_activities (
    blueprint_type_id INTEGER,
    activity TEXT,
    time INTEGER,
    max_production_limit INTEGER DEFAULT 1,
    PRIMARY KEY (blueprint_type_id, activity)
);

CREATE TABLE IF NOT EXISTS blueprint_materials (
    blueprint_type_id INTEGER,
    activity TEXT,
    material_type_id INTEGER,
    quantity INTEGER,
    PRIMARY KEY (blueprint_type_id, activity, material_type_id)
);

CREATE TABLE IF NOT EXISTS blueprint_products (
    blueprint_type_id INTEGER,
    activity TEXT,
    product_type_id INTEGER,
    quantity INTEGER DEFAULT 1,
    probability REAL DEFAULT 1.0,
    PRIMARY KEY (blueprint_type_id, activity, product_type_id)
);

CREATE TABLE IF NOT EXISTS blueprint_skills (
    blueprint_type_id INTEGER,
    activity TEXT,
    skill_type_id INTEGER,
    level INTEGER,
    PRIMARY KEY (blueprint_type_id, activity, skill_type_id)
);

CREATE TABLE IF NOT EXISTS industry_system_costs (
    solar_system_id INTEGER,
    activity TEXT,
    cost_index REAL,
    fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (solar_system_id, activity)
);

CREATE TABLE IF NOT EXISTS industry_facilities (
    facility_id INTEGER PRIMARY KEY,
    solar_system_id INTEGER,
    type_id INTEGER,
    owner_id INTEGER,
    region_id INTEGER,
    tax REAL,
    fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS item_dogma (
    type_id INTEGER PRIMARY KEY,
    dogma_attrs TEXT,
    dogma_effects TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

MARKET_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_prices (
    type_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    buy_price REAL,
    sell_price REAL,
    buy_volume BIGINT DEFAULT 0,
    sell_volume BIGINT DEFAULT 0,
    fetch_time TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (type_id, region_id)
);

CREATE TABLE IF NOT EXISTS market_volume_snapshots (
    type_id INTEGER NOT NULL,
    region_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    buy_price REAL DEFAULT 0,
    sell_price REAL DEFAULT 0,
    buy_volume BIGINT DEFAULT 0,
    sell_volume BIGINT DEFAULT 0,
    PRIMARY KEY (type_id, region_id, date)
);
"""

USER_SCHEMA = """
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

CREATE TABLE IF NOT EXISTS production_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_type_id INTEGER NOT NULL,
    product_name TEXT,
    blueprint_type_id INTEGER,
    runs INTEGER DEFAULT 1,
    parallels INTEGER DEFAULT 1,
    me_level INTEGER DEFAULT 0,
    te_level INTEGER DEFAULT 0,
    mat_hub TEXT DEFAULT 'Jita',
    sell_hub TEXT DEFAULT 'Jita',
    facility TEXT DEFAULT '',
    char_name TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    profit REAL DEFAULT 0,
    margin REAL DEFAULT 0,
    score REAL DEFAULT 0,
    material_cost REAL DEFAULT 0,
    created_at TEXT,
    started_at TEXT,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS user_skills (
    skill_type_id INTEGER PRIMARY KEY,
    level INTEGER DEFAULT 5
);
"""


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    """检查表是否存在"""
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cursor.fetchone() is not None


def copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str):
    """从源库复制整个表到目标库"""
    if not table_exists(src, table):
        log.info(f"  ⏭ {table}: 源库中不存在")
        return

    cursor = src.execute(f"SELECT * FROM {table}")
    rows = cursor.fetchall()
    if not rows:
        log.info(f"  ⏭ {table}: 无数据")
        return

    # 获取列名
    col_names = [d[0] for d in cursor.description]
    placeholders = ",".join("?" * len(col_names))
    cols_str = ",".join(col_names)

    dst.executemany(f"INSERT OR IGNORE INTO {table} ({cols_str}) VALUES ({placeholders})", rows)
    log.info(f"  ✅ {table}: {len(rows)} 行")


def run_migration():
    """主迁移流程"""
    src_path = database_path()
    if not os.path.exists(src_path):
        log.info("旧 items.db 不存在，跳过迁移")
        return False

    log.info("=" * 50)
    log.info("  数据库拆分迁移")
    log.info(f"  来源: {src_path}")
    log.info(f"  参考库: {REF_DB_PATH}")
    log.info(f"  市场库: {MKT_DB_PATH}")
    log.info(f"  用户库: {USR_DB_PATH}")
    log.info("=" * 50)

    # 连接源数据库
    src_conn = sqlite3.connect(src_path)

    # ── 参考数据库 ──
    log.info("\n[1/3] 创建参考数据库 (reference.db)...")
    ref_tables = [
        "item", "market_tree",
        "blueprint_activities", "blueprint_materials", "blueprint_products", "blueprint_skills",
        "industry_system_costs", "industry_facilities", "item_dogma",
    ]
    ref_conn = sqlite3.connect(REF_DB_PATH)
    ref_conn.executescript(REFERENCE_SCHEMA)
    for table in ref_tables:
        copy_table(src_conn, ref_conn, table)
    ref_conn.commit()
    ref_conn.close()

    # ── 市场数据库 ──
    log.info("\n[2/3] 创建市场数据库 (market.db)...")
    mkt_tables = ["market_prices", "market_volume_snapshots"]
    mkt_conn = sqlite3.connect(MKT_DB_PATH)
    mkt_conn.executescript(MARKET_SCHEMA)
    for table in mkt_tables:
        copy_table(src_conn, mkt_conn, table)
    mkt_conn.commit()
    mkt_conn.close()

    # ── 用户数据库 ──
    log.info("\n[3/3] 创建用户数据库 (user.db)...")
    user_tables = ["hangars", "inventory_items", "production_plans", "user_skills"]
    usr_conn = sqlite3.connect(USR_DB_PATH)
    usr_conn.executescript(USER_SCHEMA)
    for table in user_tables:
        copy_table(src_conn, usr_conn, table)
    usr_conn.commit()
    usr_conn.close()

    src_conn.close()

    # ── 统计 ──
    log.info("\n" + "=" * 50)
    log.info("  迁移完成！")
    log.info(f"  reference.db: {os.path.getsize(REF_DB_PATH) / 1024 / 1024:.1f} MB")
    log.info(f"  market.db:    {os.path.getsize(MKT_DB_PATH) / 1024 / 1024:.1f} MB")
    log.info(f"  user.db:      {os.path.getsize(USR_DB_PATH) / 1024 / 1024:.1f} MB")
    log.info("=" * 50)
    return True


if __name__ == "__main__":
    from core.logger import set_debug
    set_debug(True)
    run_migration()
