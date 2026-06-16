"""
拉取工业/贸易相关植入体的 dogma 属性
从 ESI 获取并存入 item_dogma 表
"""
import asyncio
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.logger import log
from core.paths import database_path
from services.client import APIClient

DB_PATH = database_path()

# 工业相关的物品组（全部拉取）
INDUSTRY_GROUP_NAMES = [
    "Cyber Production",
    "Cyber Resource Processing",
    "Cyber Science",
]


def get_industry_type_ids(db_path):
    """从数据库获取工业相关 type_id 列表"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    type_ids = set()
    for group_name in INDUSTRY_GROUP_NAMES:
        cur.execute("SELECT type_id, en_name FROM item WHERE en_group_name = ?", (group_name,))
        rows = cur.fetchall()
        for row in rows:
            type_ids.add(row[0])
        log.info(f"  {group_name}: {len(rows)} items")

    conn.close()
    return sorted(type_ids)


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


async def fetch_type_dogma(client, type_id):
    """从 ESI 获取单个 type 的 dogma 数据"""
    url = f"https://esi.evetech.net/latest/universe/types/{type_id}/?datasource=tranquility"
    data = await client.fetch(url)
    if not data:
        return None
    return {
        "type_id": type_id,
        "dogma_attrs": json.dumps(data.get("dogma_attributes", []), ensure_ascii=False),
        "dogma_effects": json.dumps(data.get("dogma_effects", []), ensure_ascii=False),
    }


async def fetch_attribute_name(client, attr_id):
    """获取单个 attribute 名称"""
    url = f"https://esi.evetech.net/latest/dogma/attributes/{attr_id}/?datasource=tranquility"
    data = await client.fetch(url)
    if data:
        return attr_id, data.get("name", "unknown")
    return attr_id, "unknown"


async def main():
    log.info("=" * 50)
    log.info("  植入体 dogma 数据拉取")
    log.info("=" * 50)

    init_db(DB_PATH)

    type_ids = get_industry_type_ids(DB_PATH)
    log.info(f"\n数据库: {DB_PATH}")
    log.info(f"\n共计: {len(type_ids)} 个植入体")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT type_id FROM item_dogma")
    existing = {row[0] for row in cur.fetchall()}
    conn.close()

    to_fetch = [t for t in type_ids if t not in existing]
    log.info(f"已缓存: {len(existing)}, 新拉取: {len(to_fetch)}")

    async with APIClient(concurrency=20, timeout=30) as client:
        # 拉取 dogma 数据
        if to_fetch:
            log.info(f"\n拉取 {len(to_fetch)} 个物品的 dogma...")
            results = []
            sem = asyncio.Semaphore(20)

            async def fetch_one(tid):
                async with sem:
                    return await fetch_type_dogma(client, tid)

            for i in range(0, len(to_fetch), 20):
                batch = to_fetch[i:i + 20]
                batch_results = await asyncio.gather(*[fetch_one(t) for t in batch])
                results.extend([r for r in batch_results if r])

            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            for r in results:
                cur.execute(
                    "INSERT OR REPLACE INTO item_dogma (type_id, dogma_attrs, dogma_effects) VALUES (?, ?, ?)",
                    (r["type_id"], r["dogma_attrs"], r["dogma_effects"])
                )
            conn.commit()
            conn.close()
            log.info(f"✅ 写入 {len(results)} 条")
        else:
            log.info("数据已最新")

        # 解析并展示
        log.info("\n=== 植入体属性解析 ===")
        all_attr_ids = set()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("""
            SELECT i.type_id, i.en_name, i.en_group_name, d.dogma_attrs
            FROM item i
            JOIN item_dogma d ON i.type_id = d.type_id
            ORDER BY i.en_name
        """)
        rows = cur.fetchall()

        # 收集所有出现的 attribute_id
        for _, _, _, dogma_json in rows:
            attrs = json.loads(dogma_json) if dogma_json else []
            for a in attrs:
                all_attr_ids.add(a["attribute_id"])

        # 获取 attribute 名称
        log.info(f"\n解析 {len(all_attr_ids)} 个 unique attributes...")
        attr_names = {}
        for attr_id in sorted(all_attr_ids):
            name = await fetch_attribute_name(client, attr_id)
            attr_names[attr_id] = name

        # 显示每个植入体的属性
        for tid, en_name, group, dogma_json in rows:
            attrs = json.loads(dogma_json) if dogma_json else []
            log.info(f"\nID={tid} | {en_name} [{group}]")
            for a in attrs:
                aid = a["attribute_id"]
                name = attr_names.get(aid, f"attr_{aid}")
                log.info(f"  {name} = {a['value']}")

        conn.close()


if __name__ == "__main__":
    asyncio.run(main())
