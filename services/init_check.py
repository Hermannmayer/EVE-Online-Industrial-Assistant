"""
数据初始化检测 — 检查各组件是否已就绪
"""

import os
import sqlite3

from core.paths import BP_DB_PATH, MKT_DB_PATH, REF_DB_PATH


def check_items() -> int:
    """返回 item 表中 **已填写名称** 的行数，<10000 视为未初始化"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM item WHERE en_name IS NOT NULL AND en_name != ''")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_item_names_ratio() -> float:
    """返回 item 表中缺名的比例（0~1），< 5% 视为可接受"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM item")
            total = int(c.fetchone()[0])
            if total < 10000:
                return 1.0  # 行数太少→未初始化
            c.execute("SELECT COUNT(*) FROM item WHERE en_name IS NULL OR en_name = ''")
            missing = int(c.fetchone()[0])
            return missing / max(total, 1)
    except Exception:
        return 1.0


def check_prices() -> int:
    """返回 market_prices 行数"""
    try:
        with sqlite3.connect(MKT_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM market_prices")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_blueprints() -> int:
    """返回 blueprint_activities 行数，>1000 视为已初始化"""
    try:
        with sqlite3.connect(BP_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blueprint_activities'")
            if not c.fetchone():
                return 0
            c.execute("SELECT COUNT(*) FROM blueprint_activities")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_blueprint_names() -> int:
    """返回蓝图 type_id 在 item 表中缺名的数量"""
    try:
        conn = sqlite3.connect(REF_DB_PATH)
        bp_path = BP_DB_PATH.replace("\\", "/")
        safe_path = bp_path.replace("'", "''")
        conn.execute(f"ATTACH DATABASE '{safe_path}' AS bp")
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM item"
            " WHERE (zh_name IS NULL OR zh_name = '')"
            " AND type_id IN (SELECT DISTINCT blueprint_type_id FROM bp.blueprint_activities)"
        )
        count = c.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 9999  # 无法判断时视为未就绪


def check_implants() -> int:
    """返回 item_dogma 行数，>200 视为已初始化（约 200-300 个植入体有 dogma）"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item_dogma'")
            if not c.fetchone():
                return 0
            c.execute("SELECT COUNT(*) FROM item_dogma")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_market_tree() -> int:
    """返回 market_tree 行数，>500 视为已初始化"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='market_tree'")
            if not c.fetchone():
                return 0
            c.execute("SELECT COUNT(*) FROM market_tree")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_industry() -> int:
    """返回 industry_system_costs 行数，>100 视为已初始化"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='industry_system_costs'")
            if not c.fetchone():
                return 0
            c.execute("SELECT COUNT(*) FROM industry_system_costs")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_icons() -> tuple[int, int]:
    """返回 (已缓存/免下载数, 总数)，缓存达到 80% 视为已初始化"""
    from core.paths import icon_cache_dir

    cache_dir = icon_cache_dir()
    if not os.path.exists(cache_dir):
        return 0, 0
    cached = len([f for f in os.listdir(cache_dir) if f.endswith(".png")])
    noicon = len([f for f in os.listdir(cache_dir) if f.endswith(".noicon")])
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM item WHERE market_group_id IS NOT NULL AND market_group_id > 0")
            total = c.fetchone()[0]
    except Exception:
        total = 0
    return cached + noicon, max(total, 1)


def check_meta_groups() -> int:
    """返回 meta_group 表行数"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM meta_group")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_type_materials() -> int:
    """返回 reprocessing_materials 表行数"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM reprocessing_materials")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_dogma_attrs() -> int:
    """返回 dogma_attribute 表行数"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM dogma_attribute")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_stations() -> int:
    """返回 station 表行数"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM station")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_universe() -> int:
    """返回 region 表行数"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM region")
            return int(c.fetchone()[0])
    except Exception:
        return 0


def check_all() -> dict:
    """返回各组件状态 { "items": bool, "prices": bool, "blueprints": bool, ... }"""
    cached, total = check_icons()
    return {
        "items": check_items() >= 10000 and check_item_names_ratio() < 0.05 and check_market_tree() > 500,
        "prices": check_prices() > 0,
        "blueprints": check_blueprints() >= 1000 and check_blueprint_names() < 100,
        "implants": check_implants() > 200,
        "icons": cached >= int(total * 0.8),
        "industry": check_industry() > 100,
        "sde_data": (
            check_meta_groups() > 0
            and check_type_materials() > 0
            and check_dogma_attrs() > 0
            and check_stations() > 0
            and check_universe() > 0
        ),
    }


def missing_count() -> int:
    """返回未就绪的组件数量"""
    status = check_all()
    return sum(1 for v in status.values() if not v)
