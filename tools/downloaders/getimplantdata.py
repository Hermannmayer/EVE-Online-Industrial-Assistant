"""
拉取工业/发明相关植入体的 dogma 属性（从 ESI /universe/types/ 并发拉取）

只处理与应用相关的工业/发明植入体组，避免全量 443 个战斗/通用植入体：
  - Cyber Production          (3 个)  工业制造
  - Cyber Science             (13 个) 发明/研究/科学
  - Cyber Resource Processing (16 个) 采矿/精炼/冰

说明：SDE 的 typeIDs.yaml 导出不含 dogmaAttributes/dogmaEffects，
因此直接从 ESI 拉取真实 dogma 数据。
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

# 工业/发明相关的物品组（其余 Cyber 组为战斗/通用类，不需要 dogma）
INDUSTRY_GROUP_NAMES = [
    "Cyber Production",  # 工业制造（Beancounter Industry BX）
    "Cyber Science",  # 发明/研究/科学（Beancounter Research RR / Science SC）
    "Cyber Resource Processing",  # 采矿/精炼/冰（Highwall MX / Yeti IH / Beancounter RX）
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


async def fetch_type_dogma(client, type_id: int) -> dict | None:
    """从 ESI 获取 type 的 dogma 属性

    Args:
        client: ESI HTTP 客户端（需实现 async fetch(url) -> dict | None）
        type_id: 物品 type ID

    Returns:
        {"type_id": int, "dogma_attrs": json_str, "dogma_effects": json_str} | None
    """
    url = f"https://esi.evetech.net/latest/universe/types/{type_id}/?datasource=tranquility"
    data = await client.fetch(url)
    if data is None:
        return None
    return {
        "type_id": type_id,
        "dogma_attrs": json.dumps(data.get("dogma_attributes", []) or []),
        "dogma_effects": json.dumps(data.get("dogma_effects", []) or []),
    }


async def fetch_attribute_name(client, attribute_id: int) -> tuple[int, str]:
    """从 ESI 获取 dogma attribute 的名称

    Args:
        client: ESI HTTP 客户端（需实现 async fetch(url) -> dict | None）
        attribute_id: dogma attribute ID

    Returns:
        (attribute_id, name) | (attribute_id, "unknown")
    """
    url = f"https://esi.evetech.net/latest/dogma/attributes/{attribute_id}/?datasource=tranquility"
    data = await client.fetch(url)
    if data is None:
        return (attribute_id, "unknown")
    return (attribute_id, data.get("name", "unknown"))


async def main(progress_cb=None):
    log.info("=" * 50)
    log.info("  工业/发明植入体 dogma 数据拉取（ESI）")
    log.info("=" * 50)

    if progress_cb:
        progress_cb(5, "初始化数据库")
    init_db(DB_PATH)

    type_ids = get_industry_type_ids(DB_PATH)
    log.info(f"共计 {len(type_ids)} 个工业/发明植入体")

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
        if progress_cb:
            progress_cb(100, "植入体数据已最新")
        return

    # 从 ESI 并发拉取 dogma（APIClient 自带 20 req/s 全局限流 + 429 重试）
    from services.client import APIClient

    if progress_cb:
        progress_cb(20, f"从 ESI 拉取 {len(to_fetch)} 个植入体 dogma")
    rows = []
    BATCH = 20
    async with APIClient(concurrency=10, timeout=15) as client:
        for start in range(0, len(to_fetch), BATCH):
            batch = to_fetch[start : start + BATCH]
            results = await asyncio.gather(*[fetch_type_dogma(client, tid) for tid in batch])
            for r in results:
                if r:
                    rows.append((r["type_id"], r["dogma_attrs"], r["dogma_effects"]))
            pct = 20 + int((start + BATCH) / max(len(to_fetch), 1) * 65)
            if progress_cb:
                progress_cb(min(pct, 90), f"ESI 拉取 {min(start + BATCH, len(to_fetch))}/{len(to_fetch)}")

    if not rows:
        log.info("ESI 未返回有效 dogma 数据")
        if progress_cb:
            progress_cb(100, "未获取到 dogma 数据")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany(
        "INSERT OR REPLACE INTO item_dogma (type_id, dogma_attrs, dogma_effects) VALUES (?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    if progress_cb:
        progress_cb(92, f"写入 {len(rows)} 条 dogma 数据")
    log.info(f"写入 {len(rows)} 条 dogma 数据")

    # 展示摘要
    log.info("\n=== 植入体属性摘要 ===")
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
    if progress_cb:
        progress_cb(100, "植入体数据完成")


if __name__ == "__main__":
    asyncio.run(main())
