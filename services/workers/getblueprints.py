"""
从 CCP SDE 导出包中拉取蓝图数据并写入 items.db

从 S3 下载 SDE zip (~107MB)，提取 fsd/blueprints.yaml，
解析后写入 blueprint_activities/materials/products/skills 表。
"""
import json
import zipfile
import yaml
import io
import aiohttp
import asyncio
import aiosqlite
from tqdm import tqdm
from core.paths import database_path

DATABASE_PATH = database_path()
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


def parse_activities(bp_id: int, bp_data: dict):
    """Parse a single blueprint entry into row tuples for all 4 tables."""
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
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await create_tables(db)

    # Check if already populated
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM blueprint_activities")
        row = await cursor.fetchone()
        if row and row[0] > 1000:
            print(f"蓝图数据已就绪 ({row[0]} 条活动记录)，跳过拉取")
            return

    # Download SDE zip from S3
    print(f"从 S3 下载 SDE 数据包 ({SDE_ZIP_URL})...")
    async with aiohttp.ClientSession() as session:
        async with session.get(SDE_ZIP_URL, timeout=aiohttp.ClientTimeout(total=600)) as resp:
            resp.raise_for_status()
            data = await resp.read()
    print(f"下载完成: {len(data) / 1024 / 1024:.1f} MB")

    # Find and extract the blueprint YAML file
    print("搜索蓝图文件...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        candidates = [p for p in zf.namelist() if "blueprint" in p.lower()]
        # Prefer YAML files over directories
        yaml_candidates = [p for p in candidates if p.endswith(".yaml")]
        if not yaml_candidates:
            raise FileNotFoundError(f"在 SDE zip 中找不到蓝图的 YAML 文件 (候选: {candidates[:5]})")
        yaml_path = yaml_candidates[0]
        print(f"找到: {yaml_path}")
        raw = zf.read(yaml_path).decode("utf-8")

    # Parse YAML
    print("解析 YAML...")
    blueprints = yaml.safe_load(raw)
    if not isinstance(blueprints, dict):
        raise ValueError(f"期望 YAML 为 dict，实际为 {type(blueprints)}")
    print(f"共 {len(blueprints)} 个蓝图，开始写入数据库...")

    # Batch insert
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

    # Verify
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM blueprint_activities")
        row = await cursor.fetchone()
        activities_count = row[0] if row else 0
        cursor = await db.execute("SELECT COUNT(*) FROM blueprint_materials")
        row = await cursor.fetchone()
        materials_count = row[0] if row else 0
        cursor = await db.execute("SELECT COUNT(*) FROM blueprint_products")
        row = await cursor.fetchone()
        products_count = row[0] if row else 0
        cursor = await db.execute("SELECT COUNT(*) FROM blueprint_skills")
        row = await cursor.fetchone()
        skills_count = row[0] if row else 0
    print(f"\n写入完成:")
    print(f"  blueprint_activities: {activities_count}")
    print(f"  blueprint_materials: {materials_count}")
    print(f"  blueprint_products:  {products_count}")
    print(f"  blueprint_skills:    {skills_count}")


if __name__ == "__main__":
    asyncio.run(run_blueprint_update())
