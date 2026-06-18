"""
蓝图数据拉取 — 从 SDE 解析 blueprints.yaml

流程：
  1. 检查本地缓存 data/blueprints.yaml 是否存在
  2. 若不存在 → 下载 SDE zip(~112MB)，提取 blueprints.yaml 并缓存
  3. 解析 YAML → 写入 blueprint_* 表
  4. 后续打包分发时：带上 reference.db 即可（表已填充），无需重新下载

首次拉取需要下载一次，后续跳过。
"""
import asyncio
import io
import os

import aiohttp
import aiosqlite
import yaml
from tqdm import tqdm

from core.logger import log
from core.paths import reference_db_path

DATABASE_PATH = reference_db_path()
CACHE_DIR = os.path.join(os.path.dirname(DATABASE_PATH), "..", "data")
CACHE_FILE = os.path.join(CACHE_DIR, "blueprints.yaml")
SDE_ZIP_URL = "https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip"


async def create_tables(db: aiosqlite.Connection):
    await db.executescript("""
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
    """)
    await db.commit()


async def ensure_cache() -> str:
    """
    确保 blueprints.yaml 缓存文件存在。
    返回缓存文件路径。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(CACHE_FILE):
        size = os.path.getsize(CACHE_FILE)
        log.info(f"使用本地缓存: {CACHE_FILE} ({size / 1024 / 1024:.1f} MB)")
        return CACHE_FILE

    # 下载 SDE zip（仅首次）
    log.info("本地无缓存，从 S3 下载 SDE 数据包...")
    log.info(f"  URL: {SDE_ZIP_URL}")
    log.info("  大小: ~112 MB，首次下载后会自动缓存，后续跳过\n")

    async with aiohttp.ClientSession() as session:
        async with session.get(SDE_ZIP_URL, timeout=aiohttp.ClientTimeout(total=600)) as resp:
            resp.raise_for_status()
            data = await resp.read()

    log.info(f"下载完成: {len(data) / 1024 / 1024:.1f} MB")

    # 从 zip 中提取 blueprints.yaml
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [p for p in zf.namelist() if p.endswith("blueprints.yaml")]
        if not candidates:
            raise FileNotFoundError("SDE 包中未找到 blueprints.yaml")
        yaml_path = candidates[0]
        log.info(f"找到: {yaml_path}")
        raw = zf.read(yaml_path).decode("utf-8")

    # 写入缓存
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        f.write(raw)
    log.info(f"缓存已保存: {CACHE_FILE} ({len(raw) / 1024 / 1024:.1f} MB)")

    return CACHE_FILE


def parse_activities(bp_id: int, bp_data: dict):
    max_limit = bp_data.get("maxProductionLimit", 1)
    activities_rows = []
    materials_rows = []
    products_rows = []
    skills_rows = []

    for activity, detail in bp_data.get("activities", {}).items():
        activities_rows.append((bp_id, activity, detail.get("time", 0), max_limit))

        for mat in detail.get("materials", []):
            materials_rows.append((bp_id, activity, mat["typeID"], mat["quantity"]))

        for prod in detail.get("products", []):
            products_rows.append((
                bp_id, activity, prod["typeID"],
                prod.get("quantity", 1),
                prod.get("probability", 1.0),
            ))

        for skill in detail.get("skills", []):
            skills_rows.append((bp_id, activity, skill["typeID"], skill["level"]))

    return activities_rows, materials_rows, products_rows, skills_rows


async def run_blueprint_update():
    os.makedirs(CACHE_DIR, exist_ok=True)

    # 检查是否已填充
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM blueprint_activities")
        row = await cursor.fetchone()
        if row and row[0] > 1000:
            log.info(f"蓝图数据已就绪 ({row[0]} 条活动记录)，跳过")
            return

    # 确保表存在
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await create_tables(db)

    # 获取 blueprints.yaml 缓存
    yaml_path = await ensure_cache()

    # 解析 YAML
    log.info("解析 YAML...")
    with open(yaml_path, "r", encoding="utf-8") as f:
        blueprints = yaml.safe_load(f)

    if not isinstance(blueprints, dict):
        raise ValueError(f"期望 dict，实际为 {type(blueprints)}")
    log.info(f"共 {len(blueprints)} 个蓝图，写入数据库...")

    # 分批写入
    batch_size = 200
    bp_items = list(blueprints.items())

    for i in tqdm(range(0, len(bp_items), batch_size), desc="蓝图"):
        batch = bp_items[i:i + batch_size]
        async with aiosqlite.connect(DATABASE_PATH) as db:
            for bp_id_str, bp_data in batch:
                bp_id = int(bp_id_str)
                a_rows, m_rows, p_rows, s_rows = parse_activities(bp_id, bp_data)
                for rows, table in [
                    (a_rows, "blueprint_activities"),
                    (m_rows, "blueprint_materials"),
                    (p_rows, "blueprint_products"),
                    (s_rows, "blueprint_skills"),
                ]:
                    if rows:
                        placeholders = ",".join("?" * len(rows[0]))
                        await db.executemany(
                            f"INSERT OR REPLACE INTO {table} VALUES ({placeholders})",
                            rows,
                        )
            await db.commit()

    # 统计
    async with aiosqlite.connect(DATABASE_PATH) as db:
        for t in ["blueprint_activities", "blueprint_materials", "blueprint_products", "blueprint_skills"]:
            cursor = await db.execute(f"SELECT COUNT(*) FROM {t}")
            log.info(f"  {t}: {cursor.fetchone()[0]}")

    log.info("完成！缓存文件可保留用于后续重建，打包时只带 reference.db 即可。")


if __name__ == "__main__":
    asyncio.run(run_blueprint_update())
