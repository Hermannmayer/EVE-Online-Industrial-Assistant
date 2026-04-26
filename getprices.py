import aiohttp
import asyncio
import aiosqlite
from tenacity import retry, stop_after_attempt, wait_exponential
from datetime import datetime, timezone
from tqdm import tqdm

# 配置常量
DATABASE_PATH = './database/items.db'
ESI_BASE_URL = 'https://esi.evetech.net/latest'
REGION_ID = 10000002  # 伏尔戈星域（The Forge，包含吉他）
CONCURRENCY = 10
BATCH_SIZE = 500

class APIClient:
    """异步API客户端，复用getitems.py的设计"""
    def __init__(self):
        self.session = None
        self.semaphore = asyncio.Semaphore(CONCURRENCY)

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(total=60)
        self.session = aiohttp.ClientSession(
            headers={
                'Accept': 'application/json',
                'User-Agent': 'EveDataCrawler/1.0'
            },
            timeout=timeout
        )
        return self

    async def __aexit__(self, *exc):
        await self.session.close()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def fetch(self, url, params=None):
        """带重试机制的异步请求"""
        async with self.semaphore:
            try:
                async with self.session.get(url, params=params) as response:
                    response.raise_for_status()
                    return await response.json()
            except aiohttp.ClientResponseError as e:
                if e.status == 404:
                    print(f"资源不存在: {url}")
                    return None
                print(f"请求失败 [{e.status}]: {url}")
                raise
            except asyncio.TimeoutError:
                print(f"超时: {url}")
                raise

    async def fetch_paginated(self, url, params=None):
        """自动处理分页，返回所有页数据的合并列表"""
        if params is None:
            params = {}
        all_data = []
        page = 1

        while True:
            page_params = dict(params)
            page_params['page'] = page
            data = await self.fetch(url, params=page_params)
            if data is None:
                break
            if not data:
                break
            all_data.extend(data)
            if page == 1:
                print(f"  第1页: {len(data)} 条")
            page += 1

        print(f"  总页数: {page - 1}, 总条数: {len(all_data)}")
        return all_data


async def initialize_database():
    """创建market_prices表，支持历史价格跟踪"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS market_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id INTEGER NOT NULL,
                buy_price REAL,
                sell_price REAL,
                buy_volume BIGINT DEFAULT 0,
                sell_volume BIGINT DEFAULT 0,
                fetch_time TIMESTAMP NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (type_id) REFERENCES item(type_id)
            )
        ''')
        await db.execute('''
            CREATE INDEX IF NOT EXISTS idx_market_prices_type_time 
            ON market_prices(type_id, fetch_time)
        ''')
        await db.commit()


async def get_tradable_type_ids():
    """从item表获取有market_group_id的可交易物品type_id列表"""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute('''
            SELECT type_id FROM item 
            WHERE market_group_id IS NOT NULL AND market_group_id > 0
            ORDER BY type_id
        ''')
        return [row[0] async for row in cursor]


def aggregate_orders(all_orders):
    """
    聚合所有订单数据，按type_id分组
    买单：取最高价（max price）及其对应数量
    卖单：取最低价（min price）及其对应数量
    """
    buy_agg = {}
    sell_agg = {}

    for order in all_orders:
        type_id = order['type_id']
        price = order['price']
        volume_remain = order['volume_remain']
        is_buy = order['is_buy_order']

        if is_buy:
            if type_id not in buy_agg or price > buy_agg[type_id][0]:
                buy_agg[type_id] = (price, volume_remain)
        else:
            if type_id not in sell_agg or price < sell_agg[type_id][0]:
                sell_agg[type_id] = (price, volume_remain)

    return buy_agg, sell_agg


async def main():
    print("=== 伏尔戈星域市场价格抓取 ===")
    now_utc = datetime.now(timezone.utc)
    print(f"当前时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"数据库路径: {DATABASE_PATH}")

    await initialize_database()
    print("数据库表已就绪 (market_prices)")

    async with APIClient() as client:
        # 先获取所有可交易type_id用于统计
        tradable_type_ids = await get_tradable_type_ids()
        print(f"可交易物品数量: {len(tradable_type_ids)}")

        # 1. 拉取所有买单
        print("\n正在拉取买单数据...")
        buy_url = f"{ESI_BASE_URL}/markets/{REGION_ID}/orders/"
        buy_orders = await client.fetch_paginated(buy_url, params={'order_type': 'buy'})
        print(f"买单总计: {len(buy_orders)}")

        # 2. 拉取所有卖单
        print("\n正在拉取卖单数据...")
        sell_url = f"{ESI_BASE_URL}/markets/{REGION_ID}/orders/"
        sell_orders = await client.fetch_paginated(sell_url, params={'order_type': 'sell'})
        print(f"卖单总计: {len(sell_orders)}")

        # 3. 聚合数据
        print("\n正在聚合订单数据...")
        buy_agg, sell_agg = aggregate_orders(buy_orders + sell_orders)
        print(f"有买单的物品: {len(buy_agg)}")
        print(f"有卖单的物品: {len(sell_agg)}")

        # 4. 合并数据并写入数据库
        all_type_ids = sorted(set(buy_agg.keys()) | set(sell_agg.keys()))
        records = []
        for type_id in all_type_ids:
            buy_price, buy_vol = buy_agg.get(type_id, (None, 0))
            sell_price, sell_vol = sell_agg.get(type_id, (None, 0))
            records.append((type_id, buy_price, sell_price, buy_vol, sell_vol))

        print(f"\n写入 {len(records)} 条价格记录到数据库...")

        async with aiosqlite.connect(DATABASE_PATH) as db:
            for i in range(0, len(records), BATCH_SIZE):
                batch = records[i:i + BATCH_SIZE]
                await db.executemany('''
                    INSERT INTO market_prices (type_id, buy_price, sell_price, buy_volume, sell_volume)
                    VALUES (?, ?, ?, ?, ?)
                ''', batch)
            await db.commit()

            fetch_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n✅ 价格数据已更新完成！")
            print(f"   抓取时间: {fetch_time} UTC")
            print(f"   记录总数: {len(records)}")
            print(f"   包含买单的物品: {len(buy_agg)}")
            print(f"   包含卖单的物品: {len(sell_agg)}")


if __name__ == "__main__":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断")
