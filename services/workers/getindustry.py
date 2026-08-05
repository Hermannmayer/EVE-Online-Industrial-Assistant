"""
从 ESI 拉取工业系统成本指数和设施数据写入 reference.db 和 user.db
用法: python -m services.workers.getindustry
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import aiosqlite

from core.logger import log
from core.paths import reference_db_path, user_db_path
from services.client import APIClient
from services.db_locks import get_db_write_lock

REF_DB_PATH = reference_db_path()
USR_DB_PATH = user_db_path()
ESI_BASE = "https://esi.evetech.net/latest"


@asynccontextmanager
async def _ref_db():
    """reference.db 写库上下文：per-DB 写锁 + 连接。

    并行初始化时 industry 与 implants/rigs/sde_data 同时写 reference.db，
    写库阶段显式串行防 database is locked。
    """
    async with get_db_write_lock("ref"):
        async with aiosqlite.connect(REF_DB_PATH, timeout=30) as db:
            yield db


# 关键制造技能ID
KEY_MANUFACTURING_SKILLS = [
    (3380, "Industry", 5, "制造时间 -4%/级"),
    (3388, "Advanced Industry", 5, "制造时间 -3%/级"),
    (24268, "Supply Chain Management", 5, "制造时间 -3%/级"),
    (3387, "Mass Production", 5, "生产线 +1/级"),
    (24625, "Advanced Mass Production", 5, "生产线 +1/级"),
    (3402, "Science", 5, "复制速度 +5%/级"),
    (3395, "Advanced Small Ship Construction", 5, "小型舰船制造"),
    (3396, "Advanced Industrial Ship Construction", 5, "工业舰制造"),
    (3397, "Advanced Medium Ship Construction", 5, "中型舰船制造"),
    (3398, "Advanced Large Ship Construction", 5, "大型舰船制造"),
    (77725, "Advanced Capital Ship Construction", 5, "旗舰制造"),
]


async def create_tables():
    """创建 reference.db 和 user.db 中的表"""
    # reference.db: 工业系统成本指数 + 工业设施
    async with _ref_db() as db:
        await db.executescript("""
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
        """)
        await db.commit()

    # user.db: 用户技能
    async with aiosqlite.connect(USR_DB_PATH, timeout=30) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS user_skills (
                skill_type_id INTEGER PRIMARY KEY,
                level INTEGER DEFAULT 5
            );
        """)
        # Insert default skill values on first run
        cursor = await db.execute("SELECT COUNT(*) FROM user_skills")
        row = await cursor.fetchone()
        if row and row[0] == 0:
            for sk_id, _name, default_lvl, _desc in KEY_MANUFACTURING_SKILLS:
                await db.execute(
                    "INSERT OR IGNORE INTO user_skills VALUES (?, ?)",
                    (sk_id, default_lvl),
                )
        await db.commit()


async def run_industry_update(progress_cb=None):
    if progress_cb:
        progress_cb(5, "创建表结构")
    await create_tables()

    async with APIClient(concurrency=10) as client:
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")

        # ── 系统成本指数 (reference.db) ──
        log.info("获取工业系统成本指数...")
        systems = await client.fetch_required(f"{ESI_BASE}/industry/systems/")
        log.info(f"  {len(systems)} 个星系")
        if progress_cb:
            progress_cb(25, f"获取系统成本指数 ({len(systems)} 个星系)")

        sys_rows = [
            (sys["solar_system_id"], ci["activity"], ci["cost_index"], now)
            for sys in systems
            for ci in sys.get("cost_indices", [])
        ]
        async with _ref_db() as db:
            total = len(sys_rows)
            for i in range(0, total, 1000):
                await db.executemany(
                    "INSERT OR REPLACE INTO industry_system_costs VALUES (?, ?, ?, ?)",
                    sys_rows[i : i + 1000],
                )
                if progress_cb:
                    done = min(i + 1000, total)
                    progress_cb(25 + int(done / max(total, 1) * 25), f"系统成本 {done}/{total}")
            await db.commit()

        # ── 工业设施 (reference.db) ──
        log.info("获取工业设施数据...")
        facilities = await client.fetch_required(f"{ESI_BASE}/industry/facilities/")
        log.info(f"  {len(facilities)} 个设施")
        if progress_cb:
            progress_cb(65, f"获取工业设施数据 ({len(facilities)} 个设施)")

        fac_rows = [
            (
                fac["facility_id"],
                fac["solar_system_id"],
                fac["type_id"],
                fac.get("owner_id"),
                fac.get("region_id"),
                fac.get("tax", 0.0),
                now,
            )
            for fac in facilities
        ]
        async with _ref_db() as db:
            total_f = len(fac_rows)
            for i in range(0, total_f, 1000):
                await db.executemany(
                    "INSERT OR REPLACE INTO industry_facilities VALUES (?, ?, ?, ?, ?, ?, ?)",
                    fac_rows[i : i + 1000],
                )
                if progress_cb:
                    done = min(i + 1000, total_f)
                    progress_cb(65 + int(done / max(total_f, 1) * 30), f"设施 {done}/{total_f}")
            await db.commit()

    if progress_cb:
        progress_cb(100, "工业数据完成")
    log.info("工业数据拉取完成")


if __name__ == "__main__":
    asyncio.run(run_industry_update())
