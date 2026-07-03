"""
拉取工业/贸易相关植入体的 dogma 属性
从 SDE zip 本地解析 typeIDs.yaml 中的 dogmaAttributes/dogmaEffects

流程：
  1. 检查本地缓存 data/typeIDs.yaml 是否存在
  2. 若不存在 → 下载 SDE zip(~112MB)，提取并缓存
  3. 解析 YAML → 写入 item_dogma 表
"""

import asyncio
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.logger import log
from core.paths import reference_db_path

DB_PATH = reference_db_path()

# 工业相关的物品组（全部拉取）
INDUSTRY_GROUP_NAMES = [
    "Cyber Armor",
    "Cyber Electronic Systems",
    "Cyber Engineering",
    "Cyber Gunnery",
    "Cyber Leadership",
    "Cyber Learning",
    "Cyber Missile",
    "Cyber Navigation",
    "Cyber Shields",
    "Cyber Targeting",
]


def init_db(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS item_dogma (
            type_id INTEGER PRIMARY KEY,
            dogma_attrs TEXT,
            dogma_effects TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def get_industry_type_ids(db_path):
    """从数据库获取工业相关 type_id 列表"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    type_ids = set()
    for group_name in INDUSTRY_GROUP_NAMES:
        cur.execute("SELECT type_id FROM item WHERE en_group_name = ?", (group_name,))
        rows = cur.fetchall()
        for row in rows:
            type_ids.add(row[0])
        log.info(f"  {group_name}: {len(rows)} items")

    conn.close()
    return sorted(type_ids)


async def main():
    log.info("=" * 50)
    log.info("  植入体 dogma 数据拉取")
    log.info("=" * 50)

    init_db(DB_PATH)

    type_ids = get_industry_type_ids(DB_PATH)
    log.info(f"共计 {len(type_ids)} 个植入体")

    # 确保 SDE 缓存就绪
    from services.workers.sde_cache import ensure_sde_cache, load_yaml

    await ensure_sde_cache()
    data = load_yaml("typeIDs.yaml")

    if not data:
        log.error("typeIDs.yaml 缓存不可用")
        return

    # 查已缓存
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT type_id FROM item_dogma")
    existing = {row[0] for row in cur.fetchall()}
    conn.close()

    to_fetch = [t for t in type_ids if t not in existing]
    log.info(f"已缓存: {len(existing)}, 新拉取: {len(to_fetch)}")

    if not to_fetch:
        log.info("数据已最新，跳过")
        return

    # 从 typeIDs.yaml 提取 dogma 数据
    rows = []
    for tid in to_fetch:
        entry = data.get(str(tid))
        if not entry:
            continue

        dogma_attrs = entry.get("dogmaAttributes", []) or []
        dogma_effects = entry.get("dogmaEffects", []) or []

        rows.append((
            tid,
            json.dumps(dogma_attrs, ensure_ascii=False),
            json.dumps(dogma_effects, ensure_ascii=False),
        ))

    if not rows:
        log.info("没有找到 dogma 数据")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO item_dogma (type_id, dogma_attrs, dogma_effects) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    log.info(f"写入 {len(rows)} 条 dogma 数据")

    # 展示摘要
    log.info(f"\n=== 植入体属性摘要 ===")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT i.type_id, i.en_name, i.en_group_name, d.dogma_attrs
        FROM item i
        JOIN item_dogma d ON i.type_id = d.type_id
        ORDER BY i.en_name
    """)
    for tid, en_name, group, dogma_json in cur.fetchall():
        attrs = json.loads(dogma_json) if dogma_json else []
        attr_summary = ", ".join(f"{a['attribute_id']}={a['value']}" for a in attrs[:5])
        log.info(f"  ID={tid} | {en_name} [{group}]  {attr_summary}{'...' if len(attrs) > 5 else ''}")
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())

