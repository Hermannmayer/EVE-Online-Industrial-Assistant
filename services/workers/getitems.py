import aiohttp
import asyncio
import aiosqlite
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm
from core.paths import database_path

# 配置常量
DATABASE_PATH = database_path()
API_BASE_URL = 'https://sde.jita.space/latest'
CONCURRENCY = 50
BATCH_SIZE = 100
START_TYPE_ID = 178

# 全局缓存
group_cache = {}
market_group_cache = {}

class APIClient:
    """异步API客户端"""
    def __init__(self):
        self.session = None
        self.semaphore = asyncio.Semaphore(CONCURRENCY)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            'Accept': 'application/json',
            'User-Agent': 'EveDataCrawler/1.0'
        })
        return self

    async def __aexit__(self, *exc):
        await self.session.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def fetch(self, url):
        """带重试机制的异步请求"""
        async with self.semaphore:
            try:
                async with self.session.get(url) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    print(f"资源不存在: {url}")
                    return None
                raise

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
            print(f"处理type_id {type_id} 失败: {str(e)}")
        finally:
            queue.task_done()
            pbar.update(1)

async def main():
    await initialize_database()

    async with APIClient() as client, DatabaseWriter() as writer:
        await initialize_type_ids(client)

        queue = asyncio.Queue()
        
        # 获取待处理type_id
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(f'''
                SELECT type_id FROM item 
                WHERE type_id >= {START_TYPE_ID}
                AND (en_name IS NULL OR market_group_id IS NULL)
            ''')
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
        # 等待关闭
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        
        # 显式关闭连接池
        await client.session.__aexit__(None, None, None)  # 新增
        # 清理工作协程
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
