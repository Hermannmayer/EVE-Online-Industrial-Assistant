"""
数据初始化检测 — 检查各组件是否已就绪
"""
import os
import sqlite3

from core.paths import REF_DB_PATH, MKT_DB_PATH


def check_items() -> int:
    """返回 item 表行数，<10000 视为未初始化"""
    try:
        conn = sqlite3.connect(REF_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM item")
        cnt = c.fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return 0


def check_prices() -> int:
    """返回 market_prices 行数"""
    try:
        conn = sqlite3.connect(MKT_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM market_prices")
        cnt = c.fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return 0


def check_blueprints() -> int:
    """返回 blueprint_activities 行数，>1000 视为已初始化"""
    try:
        conn = sqlite3.connect(REF_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='blueprint_activities'")
        if not c.fetchone():
            conn.close()
            return 0
        c.execute("SELECT COUNT(*) FROM blueprint_activities")
        cnt = c.fetchone()[0]
        conn.close()
        return cnt
    except Exception:
        return 0


def check_implants() -> int:
    """返回 item_dogma 行数"""
    try:
        conn = sqlite3.connect(REF_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='item_dogma'")
        if not c.fetchone():
            conn.close()
            return 0
        c.execute("SELECT COUNT(*) FROM item_dogma")
        cnt = c.fetchone()[0]
        conn.close()
        return cnt
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
        conn = sqlite3.connect(REF_DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM item WHERE iconID > 0")
        total = c.fetchone()[0]
        conn.close()
    except Exception:
        total = 0
    return cached + noicon, max(total, 1)


def check_all() -> dict:
    """
    返回各组件状态:
    { "items": bool, "prices": bool, "blueprints": bool, "implants": bool, "icons": bool }
    """
    return {
        "items": check_items() >= 10000,
        "prices": check_prices() > 0,
        "blueprints": check_blueprints() >= 1000,
        "implants": check_implants() > 0,
        "icons": check_icons()[0] >= check_icons()[1],
    }


def missing_count() -> int:
    """返回未就绪的组件数量"""
    status = check_all()
    return sum(1 for v in status.values() if not v)
