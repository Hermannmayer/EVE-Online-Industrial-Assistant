import asyncio

import aiosqlite
from tqdm import tqdm

from core.logger import log
from core.paths import reference_db_path
from services.client import APIClient

# 配置常量
DATABASE_PATH = reference_db_path()
API_BASE_URL = 'https://sde.jita.space/latest'
CONCURRENCY = 50
BATCH_SIZE = 100
START_TYPE_ID = 178

# 全局缓存
group_cache = {}
market_group_cache = {}

async def initialize_database():
    """初始化数据库结构"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS item (
                type_id INTEGER PRIMARY KEY,
                en_name TEXT,
                zh_name TEXT,
                group_id INTEGER,
                en_group_name TEXT,
                zh_group_name TEXT,
                market_group_id INTEGER,
                en_market_group_name TEXT,
                zh_market_group_name TEXT,
                volume REAL,
                iconID INTEGER
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS market_tree (
                market_group_id INTEGER PRIMARY KEY,
                parent_group_id INTEGER,
                en_name TEXT,
                zh_name TEXT,
                icon_id INTEGER
            )
        ''')
        await db.commit()

async def fetch_valid_type_ids(client):
    """获取所有有效的type_id并过滤无market_group_id的条目"""
    url = f"{API_BASE_URL}/universe/types"
    data = await client.fetch(url)
    return sorted(tid for tid in data if tid >= START_TYPE_ID)

async def initialize_type_ids(client):
    """初始化有效type_id到数据库"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT type_id FROM item")
        existing_ids = {row[0] async for row in cursor}

        type_ids = await fetch_valid_type_ids(client)
        new_ids = [(tid,) for tid in type_ids if tid not in existing_ids]

        if new_ids:
            await db.executemany("INSERT OR IGNORE INTO item (type_id) VALUES (?)", new_ids)
            await db.commit()
            print(f"已初始化 {len(new_ids)} 个新type_id")
        else:
            log.info("无新的 type_id 需要初始化")

async def get_group_info(client, group_id):
    """获取组信息带缓存"""
    if not group_id:
        return ("", "", 0)

    if group_id in group_cache:
        return group_cache[group_id]

    url = f"{API_BASE_URL}/universe/groups/{group_id}"
    data = await client.fetch(url)
    if data:
        name_data = data.get('name', {})
        en = name_data.get('en', '') if isinstance(name_data, dict) else str(name_data)
        zh = name_data.get('zh', '') if isinstance(name_data, dict) else ''
        iconID = data.get('iconID', 0)
        group_cache[group_id] = (en, zh, iconID)
        return (en, zh, iconID)
    return ("", "", 0)

async def get_market_group_info(client, market_group_id):
    """获取市场组信息带缓存"""
    if not market_group_id:
        return ("", "", 0)

    if market_group_id in market_group_cache:
        return market_group_cache[market_group_id]

    url = f"{API_BASE_URL}/markets/groups/{market_group_id}"
    data = await client.fetch(url)
    if data:
        name_data = data.get('nameID', {})
        en = name_data.get('en', '') if isinstance(name_data, dict) else str(name_data)
        zh = name_data.get('zh', '') if isinstance(name_data, dict) else ''
        iconID = data.get('iconID', 0)
        market_group_cache[market_group_id] = (en, zh, iconID)
        return (en, zh, iconID)
    return ("", "", 0)

async def process_type(client, type_id):
    """处理单个type_id"""
    url = f"{API_BASE_URL}/universe/types/{type_id}"
    data = await client.fetch(url)
    if not data:
        return None

    # 不再过滤 market_group_id，收录所有物品（含PLEX等无市场分类但有交易的物品）
    market_group_id = data.get('marketGroupID')

    # 提取其他字段
    group_id = data.get('groupID')
    volume = data.get('volume', 0.0)
    iconID = data.get('iconID', 0)

    name_data = data.get('name', {})
    en_name = name_data.get('en', '') if isinstance(name_data, dict) else str(name_data)
    zh_name = name_data.get('zh', '') if isinstance(name_data, dict) else ''

    # 并行获取组信息
    group_task = get_group_info(client, group_id)
    market_task = get_market_group_info(client, market_group_id)
    en_group, zh_group, _ = await group_task
    en_market, zh_market, market_icon = await market_task

    return (
        en_name, zh_name,
        group_id, en_group, zh_group,
        market_group_id, en_market, zh_market,
        volume, iconID or market_icon,
        type_id
    )

class DatabaseWriter:
    """异步批量写入器"""
    def __init__(self):
        self.buffer = []
        self.conn = None

    async def __aenter__(self):
        self.conn = await aiosqlite.connect(DATABASE_PATH)
        return self

    async def __aexit__(self, *exc):
        await self.commit()
        await self.conn.close()

    async def add_data(self, data):
        """添加数据到缓冲区"""
        self.buffer.append(data)
        if len(self.buffer) >= BATCH_SIZE:
            await self.commit()

    async def commit(self):
        """提交缓冲区数据"""
        if not self.buffer:
            return

        query = '''
            UPDATE item SET
                en_name=?, zh_name=?,
                group_id=?, en_group_name=?, zh_group_name=?,
                market_group_id=?, en_market_group_name=?, zh_market_group_name=?,
                volume=?, iconID=?
            WHERE type_id=?
        '''
        await self.conn.executemany(query, self.buffer)
        await self.conn.commit()
        self.buffer.clear()

    async def delete_data(self, type_id):
        """删除无效条目"""
        await self.conn.execute("DELETE FROM item WHERE type_id=?", (type_id,))
        await self.conn.commit()

# ─── 市场分类树（market_tree） ───

async def ensure_market_tree(client):
    """确保 market_tree 表已填充（仅当为空时执行）"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM market_tree")
        count = (await cursor.fetchone())[0]
        if count > 0:
            log.info(f"market_tree 已有 {count} 条记录，跳过")
            return

    log.info("正在拉取市场分类树 (market_tree)...")
    # 获取所有 market_group_id 列表
    ids_url = f"{API_BASE_URL}/markets/groups"
    all_ids = await client.fetch(ids_url)
    if not all_ids:
        log.info("获取市场分类列表失败")
        return

    log.info(f"共 {len(all_ids)} 个市场分类，开始拉取详情...")
    # 并发拉取每个组的详情
    semaphore = asyncio.Semaphore(CONCURRENCY)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def fetch_group_detail(gid):
        async with semaphore:
            url = f"{API_BASE_URL}/markets/groups/{gid}"
            return await client.fetch(url)

    async def fetch_group_with_retry(gid):
        try:
            return await fetch_group_detail(gid)
        except Exception as e:
            log.error(f"获取市场分类 {gid} 失败: {e}")
            return None

    tasks = [fetch_group_with_retry(gid) for gid in all_ids]
    results = await asyncio.gather(*tasks)

    # 写入数据库
    rows = []
    for data in results:
        if data is None:
            continue
        gid = data.get('marketGroupID')
        parent = data.get('parentGroupID')  # 根节点没有此字段
        name_data = data.get('name', {})
        en = name_data.get('en', '') if isinstance(name_data, dict) else ''
        zh = name_data.get('zh', '') if isinstance(name_data, dict) else ''
        icon = data.get('iconID', 0)
        rows.append((gid, parent, en, zh, icon))

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM market_tree")  # 清空重写
        await db.executemany(
            "INSERT INTO market_tree (market_group_id, parent_group_id, en_name, zh_name, icon_id) VALUES (?, ?, ?, ?, ?)",
            rows
        )
        await db.commit()

    log.info(f"market_tree 写入完成，共 {len(rows)} 条记录")

async def worker(client, queue, writer, pbar):
    """工作协程"""
    while True:
        type_id = await queue.get()
        try:
            result = await process_type(client, type_id)
            if result:
                await writer.add_data(result)
            else:
                await writer.delete_data(type_id)
        except Exception as e:
            log.exception(f"处理type_id {type_id} 失败: {e}")
        finally:
            queue.task_done()
            pbar.update(1)

async def main():
    await initialize_database()

    async with APIClient(concurrency=CONCURRENCY) as client, DatabaseWriter() as writer:
        # 拉取市场分类树（首次）
        await ensure_market_tree(client)

        await initialize_type_ids(client)

        queue = asyncio.Queue()

        # 获取待处理type_id
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute('''
                SELECT type_id FROM item
                WHERE type_id >= ?
                AND (en_name IS NULL OR market_group_id IS NULL)
            ''', (START_TYPE_ID,))
            type_ids = [row[0] async for row in cursor]

        total = len(type_ids)
        pbar = tqdm(total=total, desc='数据抓取进度', unit='item')

        for tid in type_ids:
            await queue.put(tid)

        # 启动工作协程
        workers = [asyncio.create_task(worker(client, queue, writer, pbar))
                  for _ in range(CONCURRENCY)]

        await queue.join()
        pbar.close()
        # 清理工作协程
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def fill_missing_blueprint_names():
    """补充 item 表中缺失的 T2/T3 蓝图名称（从 SDE API 拉取）"""
    import aiosqlite as _aiosqlite

    # 收集所有 blueprint_type_id
    async with _aiosqlite.connect(DATABASE_PATH) as db:
        # 从 blueprint.db 获取所有 blueprint_type_id
        from core.paths import blueprint_db_path
        bp_db = blueprint_db_path()
        await db.execute(f"ATTACH DATABASE '{bp_db.replace(chr(92), '/')}' AS bp")
        cursor = await db.execute("SELECT DISTINCT blueprint_type_id FROM bp.blueprint_activities")
        all_bp_ids = [row[0] async for row in cursor]

        # 找出 item 表中缺名称的
        placeholders = ",".join("?" * len(all_bp_ids))
        cursor = await db.execute(
            f"SELECT type_id FROM item WHERE type_id IN ({placeholders}) AND (zh_name IS NULL OR zh_name = '')",
            all_bp_ids)
        missing = [row[0] async for row in cursor]

    if not missing:
        log.info("所有蓝图名称已完整，无需补拉")
        return

    log.info(f"发现 {len(missing)} 个蓝图缺少名称，开始补拉...")

    client = APIClient()
    batch = []
    for i, tid in enumerate(missing):
        try:
            url = f"{API_BASE_URL}/universe/types/{tid}"
            data = await client.fetch(url)
            if data:
                name_data = data.get('name', {})
                en = name_data.get('en', '') if isinstance(name_data, dict) else str(name_data)
                zh = name_data.get('zh', '') if isinstance(name_data, dict) else ''
                if en or zh:
                    batch.append((en, zh, tid))
        except Exception:
            pass

        if len(batch) >= 50 or (i == len(missing) - 1 and batch):
            async with _aiosqlite.connect(DATABASE_PATH) as db:
                await db.executemany("UPDATE item SET en_name=?, zh_name=? WHERE type_id=?", batch)
                await db.commit()
            log.info(f"  已写入 {len(batch)} 条 ({i + 1}/{len(missing)})")
            batch.clear()

    await client.close()
    log.info(f"补拉完成，共修复 {len(missing)} 个蓝图名称")
    asyncio.run(main())
