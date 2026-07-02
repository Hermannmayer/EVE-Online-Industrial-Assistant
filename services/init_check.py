"""
数据初始化检测 — 检查各组件是否已就绪
"""

import os
import sqlite3

from core.paths import BP_DB_PATH, MKT_DB_PATH, REF_DB_PATH


def check_items() -> int:
    """返回 item 表行数，<10000 视为未初始化"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM item")
            return c.fetchone()[0]
    except Exception:
        return 0


def check_prices() -> int:
    """返回 market_prices 行数"""
    try:
        with sqlite3.connect(MKT_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM market_prices")
            return c.fetchone()[0]
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
            return c.fetchone()[0]
    except Exception:
        return 0


def check_implants() -> int:
    """返回 item_dogma 行数"""
    try:
        with sqlite3.connect(REF_DB_PATH) as conn:
            c = conn.cursor()
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item_dogma'")
            if not c.fetchone():
                return 0
            c.execute("SELECT COUNT(*) FROM item_dogma")
            return c.fetchone()[0]
    except Exception:
        return 0


def check_icons() -> tuple[int, int]:
    """返回 (已缓存/免下载数, 总数)"""
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


def check_all() -> dict:
    """返回各组件状态 { "items": bool, "prices": bool, "blueprints": bool, "implants": bool, "icons": bool }"""
    cached, total = check_icons()
    return {
        "items": check_items() >= 10000,
        "prices": check_prices() > 0,
        "blueprints": check_blueprints() >= 1000,
        "implants": check_implants() > 0,
        "icons": cached >= int(total * 0.8),  # 50% threshold
    }


def missing_count() -> int:
    """返回未就绪的组件数量"""
    status = check_all()
    return sum(1 for v in status.values() if not v)
