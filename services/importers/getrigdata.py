"""拉取结构改装件（Standup Engineering Rigs）的制造加成（从 ESI /universe/types/ 并发拉取）

只处理制造相关的工程站改装件组（reference.db item 表 group 1816-1870，剔除
1818 Strong Boxes 与 1817 空组，共 53 组 111 个改件）：
  - 材料效率钻机（attributeEngRigMatBonus=2594）
  - 时间效率钻机（attributeEngRigTimeBonus=2593）
  - 成本优化钻机（attributeEngRigCostBonus=2595；发明/ME/TE 研究/拷贝成本）

说明：SDE 的 typeIDs.yaml 导出不含 dogmaAttributes，改件加成直接走 ESI 拉取，
写入 reference.db 的 structure_rigs 表（机库设置 UI 展示与成本解析使用）。

`cost_bonus` 是 2026-10-17 审计 01-13 补的列：旧缓存库没有该列，`init_db()` 会
「列不存在则 ALTER TABLE 补列」（reference.db 是可重建缓存，不走 user.db 迁移）；
旧库补列后该列为 NULL = 从未拉取过，`main()` 会把这些行重新拉一遍（不能把
「未拉取」的 0 当成真实加成）。
"""

import asyncio
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.logger import log
from core.paths import reference_db_path
from services.db_locks import get_db_write_lock

DB_PATH = reference_db_path()

MAT_BONUS_ATTR = 2594  # attributeEngRigMatBonus（百分比，-2 = -2%）
TIME_BONUS_ATTR = 2593  # attributeEngRigTimeBonus（百分比，-20 = -20%）
#: attributeEngRigCostBonus（ESI /dogma/attributes/2595/：name=attributeEngRigCostBonus,
#: display_name="Cost Reduction Bonus", unit 105=百分比；成本优化改件 I=-10 / II=-12，
#: 制造类改件该属性为 0）。实测取值见 audit 01-13。
COST_BONUS_ATTR = 2595

# 制造相关的结构改装件组（1816-1870 剔除 1818 Strong Boxes / 1817 空组）
RIG_GROUP_IDS = [
    1816,
    1819,
    1820,
    1821,
    1822,
    1823,
    1824,
    1825,
    1826,
    1827,
    1828,
    1829,
    1830,
    1831,
    1832,
    1833,
    1834,
    1835,
    1836,
    1837,
    1838,
    1839,
    1840,
    1841,
    1842,
    1843,
    1844,
    1845,
    1846,
    1847,
    1848,
    1849,
    1850,
    1851,
    1852,
    1853,
    1854,
    1855,
    1856,
    1857,
    1858,
    1859,
    1860,
    1861,
    1862,
    1863,
    1864,
    1865,
    1866,
    1867,
    1868,
    1869,
    1870,
]


def init_db(db_path: str):
    """建表 / 给旧缓存库补 `cost_bonus` 列（列不存在则 ALTER，幂等）。

    `database/reference.db` 是可重建缓存，不走 `services.schema_migrations` 的
    user.db 迁移；旧库补列后该列保持 NULL（= 尚未拉取），由 `main()` 重新拉取。
    """
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS structure_rigs (
                type_id INTEGER PRIMARY KEY,
                mat_bonus REAL DEFAULT 0.0,
                time_bonus REAL DEFAULT 0.0,
                cost_bonus REAL DEFAULT 0.0,
                fetch_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {r[1] for r in conn.execute("PRAGMA table_info(structure_rigs)")}
        if "cost_bonus" not in columns:
            # 旧库：加可空列（NULL = 未拉取），让 main() 知道哪些行需要重拉
            conn.execute("ALTER TABLE structure_rigs ADD COLUMN cost_bonus REAL")
            log.info("structure_rigs 升级：新增 cost_bonus 列（旧行标记为待拉取）")
        conn.commit()
    finally:
        conn.close()


def get_rig_type_ids(db_path: str) -> list[int]:
    """从 item 表按改装件组查询 type_id 列表"""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        placeholders = ",".join("?" * len(RIG_GROUP_IDS))
        rows = conn.execute(
            f"SELECT type_id FROM item WHERE group_id IN ({placeholders}) ORDER BY type_id",
            RIG_GROUP_IDS,
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


async def fetch_rig_bonuses(client, type_id: int) -> dict | None:
    """从 ESI 获取 type 的材料/时间/成本加成

    Returns:
        {"type_id", "mat_bonus", "time_bonus", "cost_bonus"} | None（ESI 失败）。
        类型里没有某属性（非对应效果的改件）时该值为 0.0 —— 这是「确实没有加成」，
        与旧库补列后的 NULL（「还没拉取过」）含义不同。
    """
    url = f"https://esi.evetech.net/latest/universe/types/{type_id}/?datasource=tranquility"
    data = await client.fetch(url)
    if data is None:
        return None
    attrs = {a["attribute_id"]: a["value"] for a in (data.get("dogma_attributes") or [])}
    return {
        "type_id": type_id,
        "mat_bonus": float(attrs.get(MAT_BONUS_ATTR, 0) or 0),
        "time_bonus": float(attrs.get(TIME_BONUS_ATTR, 0) or 0),
        "cost_bonus": float(attrs.get(COST_BONUS_ATTR, 0) or 0),
    }


async def main(progress_cb=None):
    """初始化表 → 查已缓存 → 增量并发拉取缺失 → 写入 structure_rigs"""
    log.info("=" * 50)
    log.info("  结构改装件制造加成数据拉取（ESI）")
    log.info("=" * 50)

    if progress_cb:
        progress_cb(5, "初始化数据库")
    init_db(DB_PATH)

    type_ids = get_rig_type_ids(DB_PATH)
    log.info(f"共计 {len(type_ids)} 个结构改装件")

    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        existing = {int(r[0]): r[1] for r in conn.execute("SELECT type_id, cost_bonus FROM structure_rigs").fetchall()}
    finally:
        conn.close()
    # NULL cost_bonus = 旧库补列后从未拉取过 → 重新拉取（不能把「未拉取」当 0 加成）
    to_fetch = [t for t in type_ids if t not in existing or existing[t] is None]
    log.info(f"已缓存: {len(existing)}, 新拉取: {len(to_fetch)}")

    if not to_fetch:
        log.info("数据已最新，跳过")
        if progress_cb:
            progress_cb(100, "改件数据已最新")
        return

    from services.client import APIClient

    if progress_cb:
        progress_cb(20, f"从 ESI 拉取 {len(to_fetch)} 个改装件加成")
    rows: list[tuple[int, float, float, float]] = []
    BATCH = 20
    async with APIClient(concurrency=10, timeout=15) as client:
        for start in range(0, len(to_fetch), BATCH):
            batch = to_fetch[start : start + BATCH]
            results = await asyncio.gather(*[fetch_rig_bonuses(client, tid) for tid in batch])
            for r in results:
                if r:
                    rows.append((r["type_id"], r["mat_bonus"], r["time_bonus"], r["cost_bonus"]))
            pct = 20 + int((start + BATCH) / max(len(to_fetch), 1) * 70)
            if progress_cb:
                progress_cb(min(pct, 92), f"ESI 拉取 {min(start + BATCH, len(to_fetch))}/{len(to_fetch)}")

    if not rows:
        log.info("ESI 未返回有效改件加成数据")
        if progress_cb:
            progress_cb(100, "未获取到改件数据")
        return

    async with get_db_write_lock("ref"):
        conn = sqlite3.connect(DB_PATH, timeout=30)
        try:
            conn.executemany(
                "INSERT OR REPLACE INTO structure_rigs (type_id, mat_bonus, time_bonus, cost_bonus) VALUES (?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    log.info(f"写入 {len(rows)} 条改件加成数据")
    if progress_cb:
        progress_cb(100, f"写入 {len(rows)} 条改件数据")


if __name__ == "__main__":
    asyncio.run(main())
