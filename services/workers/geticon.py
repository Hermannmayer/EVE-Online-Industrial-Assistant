"""
geticon.py — 从 EVE Image Server 批量拉取物品图标

用法：
    python services/workers/geticon.py          # 下载所有可交易物品的图标
    python services/workers/geticon.py 34 35 36 # 仅下载指定 type_id 的图标

图标缓存位置：data/caches/icons/{type_id}.png
图片来源：https://images.evetech.net/types/{type_id}/icon?size=64
"""
import asyncio
import aiohttp
import os
import sys
from pathlib import Path
from core.paths import icon_cache_dir, database_path

# ── 配置 ──
ICON_CACHE_DIR = Path(icon_cache_dir())
ESI_IMAGE_BASE = "https://images.evetech.net/types"
CONCURRENCY = 20   # 并发数
ICON_SIZE = 64     # 图标尺寸(px): 32, 64, 128, 256

# 确保缓存目录存在
ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)


async def download_icon(session: aiohttp.ClientSession, type_id: int,
                        semaphore: asyncio.Semaphore, progress: list) -> bool:
    """下载单个物品图标，已存在则跳过。返回 True 表示成功/已存在"""
    icon_path = ICON_CACHE_DIR / f"{type_id}.png"
    if icon_path.exists():
        progress[0] += 1
        return True

    url = f"{ESI_IMAGE_BASE}/{type_id}/icon?size={ICON_SIZE}"
    async with semaphore:
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    icon_path.write_bytes(data)
                    progress[0] += 1
                    progress[1] += 1
                    return True
                elif resp.status in (404, 304):
                    # 无图标：存一个空标记文件避免重复请求
                    icon_path.with_suffix(".noicon").touch()
                    progress[0] += 1
                    return False
                else:
                    print(f"  ⚠ type_id={type_id} 状态码={resp.status}")
                    return False
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"  ❌ type_id={type_id} 下载失败: {e}")
            return False


async def download_all(session: aiohttp.ClientSession, type_ids: list):
    """批量下载所有图标"""
    semaphore = asyncio.Semaphore(CONCURRENCY)
    progress = [0, 0]  # [total, new_downloads]
    total = len(type_ids)

    print(f"图标缓存目录: {ICON_CACHE_DIR.resolve()}")
    print(f"并发数: {CONCURRENCY}")
    print(f"图片尺寸: {ICON_SIZE}x{ICON_SIZE}")

    # 过滤：跳过已有图标和无图标准记
    need_download = []
    existing_count = 0
    no_icon_count = 0
    for tid in type_ids:
        icon_path = ICON_CACHE_DIR / f"{tid}.png"
        noicon_path = ICON_CACHE_DIR / f"{tid}.noicon"
        if icon_path.exists():
            existing_count += 1
        elif noicon_path.exists():
            no_icon_count += 1
        else:
            need_download.append(tid)

    print(f"\n统计: 总计={total}, 已有图标={existing_count}, 无图标标记={no_icon_count}, 需下载={len(need_download)}")
    progress[0] = existing_count + no_icon_count

    if not need_download:
        print("✅ 所有图标已缓存，无需下载")
        return

    # 分批下载
    batch_size = 50
    batches = [need_download[i:i + batch_size] for i in range(0, len(need_download), batch_size)]

    for batch_idx, batch in enumerate(batches):
        tasks = [download_icon(session, tid, semaphore, progress) for tid in batch]
        await asyncio.gather(*tasks)
        done = progress[0]
        new_dl = progress[1]
        print(f"  批次 {batch_idx + 1}/{len(batches)}: 进度 {done}/{total}, 新下载 {new_dl}")

    print(f"\n✅ 完成! 总计处理 {total}, 新下载 {progress[1]} 个图标")


async def main():
    import sqlite3

    # 如果有命令行参数，只下载指定 type_id
    if len(sys.argv) > 1:
        type_ids = [int(arg) for arg in sys.argv[1:] if arg.isdigit()]
    else:
        # 从数据库获取所有可交易物品
        db_path = database_path()
        if not os.path.exists(db_path):
            print(f"❌ 数据库不存在: {db_path}")
            sys.exit(1)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT type_id FROM item WHERE market_group_id IS NOT NULL AND market_group_id > 0"
        )
        type_ids = [row[0] for row in cursor.fetchall()]
        conn.close()

    print(f"=== EVE 物品图标下载器 ===")
    print(f"需处理物品数: {len(type_ids)}")

    async with aiohttp.ClientSession(
        headers={'Accept': 'image/png', 'User-Agent': 'EveDataCrawler/1.0'},
        timeout=aiohttp.ClientTimeout(total=30)
    ) as session:
        await download_all(session, type_ids)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
