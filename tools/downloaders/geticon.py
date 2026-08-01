"""
geticon.py — 从 EVE Image Server 批量拉取物品图标

用共享的 SDE 缓存（typeIDs.yaml）预筛出有图标的物品，跳过无图标条目。
按 iconID 去重，相同图标只下载一次后复制到其余 type_id。

图标缓存位置：data/caches/icons/{type_id}.png
"""

import asyncio
import os
import sys
from pathlib import Path

import aiohttp

from core.logger import log
from core.paths import icon_cache_dir, reference_db_path

# ── 配置 ──
ICON_CACHE_DIR = Path(icon_cache_dir())
ESI_IMAGE_BASE = "https://images.evetech.net/types"
CONCURRENCY = 100  # 并发数（EVE Image Server 可承受）
ICON_SIZE = 64  # 图标尺寸(px): 32, 64, 128, 256

ICON_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _load_type_ids_with_icons() -> set[int]:
    """从 SDE 缓存（typeIDs.yaml）读取有 iconID 的 type_id，避免无效请求"""
    from tools.downloaders.sde_cache import load_yaml

    data = load_yaml("typeIDs.yaml")
    if not data:
        return set()

    result = set()
    for tid_str, tdata in data.items():
        tid = int(tid_str) if isinstance(tid_str, str) else tid_str
        if tid < 178:
            continue
        icon_id = (
            tdata.get("iconID") or tdata.get("icon", {}).get("iconID") if isinstance(tdata.get("icon"), dict) else 0
        )
        if icon_id and int(icon_id) > 0:
            result.add(tid)
    return result


def _get_type_ids_from_db() -> list[int]:
    """从数据库获取所有可交易物品（兜底方案）"""
    import sqlite3

    db_path = reference_db_path()
    if not os.path.exists(db_path):
        log.error(f"数据库不存在: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT type_id FROM item WHERE market_group_id IS NOT NULL AND market_group_id > 0")
    type_ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return type_ids


def _load_type_icon_map() -> dict[int, int]:
    """从 typeIDs.yaml 构建 {type_id: iconID} 映射，用于 iconID 去重"""
    from tools.downloaders.sde_cache import load_yaml

    data = load_yaml("typeIDs.yaml")
    if not data:
        return {}

    result: dict[int, int] = {}
    for tid_str, tdata in data.items():
        tid = int(tid_str) if isinstance(tid_str, str) else tid_str
        if tid < 178:
            continue
        icon_id = tdata.get("iconID") or 0
        if not icon_id:
            icon = tdata.get("icon", {})
            if isinstance(icon, dict):
                icon_id = icon.get("iconID", 0)
        if icon_id and int(icon_id) > 0:
            result[tid] = int(icon_id)
    return result


def _build_icon_groups(type_ids: list[int], type_icon_map: dict[int, int]) -> dict[int, list[int]]:
    """按 iconID 对 type_id 分组，相同 iconID 的 type 共享同一个图标文件"""
    groups: dict[int, list[int]] = {}
    for tid in type_ids:
        icon_id = type_icon_map.get(tid, tid)  # 无映射时以自身为分组 key
        groups.setdefault(icon_id, []).append(tid)
    return groups


async def download_icon(
    session: aiohttp.ClientSession,
    type_id: int,
    semaphore: asyncio.Semaphore,
    progress: list,
) -> bool:
    """为单个 type_id 下载图标（向后兼容包装，委托给 download_icon_for_group）"""
    return await download_icon_for_group(session, type_id, [type_id], semaphore, progress)


async def download_icon_for_group(
    session: aiohttp.ClientSession,
    icon_id: int,
    type_ids: list[int],
    semaphore: asyncio.Semaphore,
    progress: list,
) -> bool:
    """为同一 iconID 的一组 type_id 下载/复制图标（组内只下载一次）"""
    representative = type_ids[0]
    dest_path = ICON_CACHE_DIR / f"{representative}.png"
    noicon_path = ICON_CACHE_DIR / f"{representative}.noicon"

    # 检查代表 type_id 的缓存状态
    if dest_path.exists():
        progress[0] += len(type_ids)
        return True
    if noicon_path.exists():
        progress[0] += len(type_ids)
        return False

    # 下载代表 type_id 的图标
    url = f"{ESI_IMAGE_BASE}/{representative}/icon?size={ICON_SIZE}"
    async with semaphore:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    icon_data = await resp.read()
                    dest_path.write_bytes(icon_data)
                    # 为组内其他 type_id 复制图标（不重复下载）
                    for dup_tid in type_ids[1:]:
                        dup_path = ICON_CACHE_DIR / f"{dup_tid}.png"
                        if not dup_path.exists():
                            dup_path.write_bytes(icon_data)
                    progress[1] += 1
                    progress[0] += len(type_ids)
                    return True
                else:
                    # 标记组内所有 type_id 为无图标
                    for dup_tid in type_ids:
                        (ICON_CACHE_DIR / f"{dup_tid}.noicon").touch()
                    progress[0] += len(type_ids)
                    return False
        except (TimeoutError, aiohttp.ClientError) as e:
            log.error(f"  icon_id={icon_id} (代表 type_id={representative}) 下载失败: {e}")
            return False


async def download_all(session: aiohttp.ClientSession, type_ids: list, progress_cb=None):
    """批量下载所有图标（按 iconID 去重，相同图标只下载一次）"""
    semaphore = asyncio.Semaphore(CONCURRENCY)
    progress: list = [0, 0]  # [total, new_downloads]

    # 构建 iconID 分组
    type_icon_map = _load_type_icon_map()
    icon_groups = _build_icon_groups(type_ids, type_icon_map)

    total = len(type_ids)
    log.info(f"总计={total}, 按 iconID 分组后共 {len(icon_groups)} 个唯一图标")

    tasks = [
        download_icon_for_group(session, icon_id, tids, semaphore, progress) for icon_id, tids in icon_groups.items()
    ]
    if tasks:
        # 后台轮询共享进度并上报（不侵入单个下载函数）
        async def _monitor():
            last = -1
            while progress[0] < total:
                processed = min(progress[0], total)
                if processed != last and progress_cb:
                    progress_cb(int(processed / max(total, 1) * 100), f"图标 {processed}/{total}")
                    last = processed
                await asyncio.sleep(0.2)

        await asyncio.gather(_monitor(), *tasks)

    if progress_cb:
        progress_cb(100, f"图标 {total}/{total}")

    log.info(f"完成! 总计 {total}, 新下载 {progress[1]} 个图标（{len(icon_groups)} 组）")


async def main(progress_cb=None):
    # 命令行参数：只下载指定 type_id
    if len(sys.argv) > 1:
        type_ids = [int(arg) for arg in sys.argv[1:] if arg.isdigit()]
    else:
        # 优先从 SDE 缓存获取有图标的 type_id（减少无效 404 请求）
        type_ids = list(_load_type_ids_with_icons())
        if not type_ids:
            log.info("SDE 缓存不可用，降级到数据库查询")
            type_ids = _get_type_ids_from_db()

    if not type_ids:
        log.error("没有需要下载图标的物品")
        return

    log.info(f"需处理物品数: {len(type_ids)}")

    async with aiohttp.ClientSession(
        headers={"Accept": "image/png", "User-Agent": "EveDataCrawler/1.0"},
        timeout=aiohttp.ClientTimeout(total=30),
        connector=aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=CONCURRENCY),
    ) as session:
        await download_all(session, type_ids, progress_cb)


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
