import aiohttp
import asyncio
import aiosqlite
import json
import os
from datetime import datetime, timezone
from core.paths import database_path, progress_file


def write_progress(current: int, total: int, phase: str = ""):
    """写入进度供 Main.py 读取"""
    try:
        filepath = progress_file()
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump({"current": current, "total": total, "phase": phase}, f)
    except Exception:
        pass


# 配置常量
DATABASE_PATH = database_path()
ESI_BASE_URL = 'https://esi.evetech.net/latest'
BATCH_SIZE = 500


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


async def main():
    """
    从 ESI /markets/prices/ 获取全量价格数据（1次请求，无分页）
    然后写入数据库，用于查询页面的价格展示
    """
    print("=== 全量市场价格抓取 (markets/prices) ===")
    now_utc = datetime.now(timezone.utc)
    print(f"当前时间: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"数据库路径: {DATABASE_PATH}")

    write_progress(0, 3, "初始化数据库...")
    await initialize_database()
    print("数据库表已就绪 (market_prices)")
    write_progress(1, 3, "从 ESI 获取全量价格数据...")

    # 发起单次 HTTP 请求获取所有物品价格
    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(
        headers={
            'Accept': 'application/json',
            'User-Agent': 'EveDataCrawler/1.0'
        },
        timeout=timeout
    ) as session:
        url = f"{ESI_BASE_URL}/markets/prices/"
        print(f"请求: {url}")
        async with session.get(url) as resp:
            resp.raise_for_status()
            price_data = await resp.json()

    print(f"收到 {len(price_data)} 条价格记录（单次请求，无分页）")
    write_progress(2, 3, "写入数据库...")

    # 将 price_data 转换为 (type_id, buy_price, sell_price, buy_volume, sell_volume)
    # 注意：markets/prices 返回的是 adjusted_price 和 average_price
    # 我们将 adjusted_price 视为 sell_price，average_price 视为 buy_price
    records = []
    for item in price_data:
        type_id = item["type_id"]
        adjusted_price = item.get("adjusted_price")
        average_price = item.get("average_price")
        # 用 average_price 作为 buy_price，adjusted_price 作为 sell_price
        records.append((type_id, average_price, adjusted_price, 0, 0))

    print(f"写入 {len(records)} 条价格记录到数据库...")

    async with aiosqlite.connect(DATABASE_PATH) as db:
        for i in range(0, len(records), BATCH_SIZE):
            batch = records[i:i + BATCH_SIZE]
            await db.executemany('''
                INSERT INTO market_prices (type_id, buy_price, sell_price, buy_volume, sell_volume)
                VALUES (?, ?, ?, ?, ?)
            ''', batch)
        await db.commit()

    write_progress(3, 3, "完成")
    fetch_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n✅ 价格数据已更新完成！")
    print(f"   抓取时间: {fetch_time} UTC")
    print(f"   记录总数: {len(records)}")
    print(f"   (数据来源: ESI /markets/prices/ — 含 average_price 与 adjusted_price)")


def run_price_update():
    """同步运行价格更新（供 Main.py 直接调用，无需 subprocess）"""
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n用户中断")


if __name__ == "__main__":
    run_price_update()