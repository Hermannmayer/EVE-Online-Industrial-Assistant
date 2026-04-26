import aiohttp
import asyncio

async def test():
    async with aiohttp.ClientSession() as session:
        # 测试第一页买单
        url = "https://esi.evetech.net/latest/markets/10000002/orders/?order_type=buy&page=1"
        print(f"请求: {url}")
        async with session.get(url) as resp:
            print(f"状态码: {resp.status}")
            data = await resp.json()
            print(f"数据条数: {len(data)}")
            if data:
                print(f"第一条: {data[0]}")
        
        # 测试卖单第一页
        url2 = "https://esi.evetech.net/latest/markets/10000002/orders/?order_type=sell&page=1"
        print(f"\n请求: {url2}")
        async with session.get(url2) as resp:
            print(f"状态码: {resp.status}")
            data = await resp.json()
            print(f"数据条数: {len(data)}")

asyncio.run(test())
