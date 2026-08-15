"""
SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

被 getitems.py、geticon.py、getimplantdata.py、sde_loader.py 等模块共用。
"""

import asyncio
import json
import os
import pickle
import tempfile
import threading
import time
import zipfile
from collections.abc import Callable

import aiohttp
import yaml

from core.logger import log
from core.paths import reference_db_path

CACHE_DIR = os.path.join(os.path.dirname(reference_db_path()), "..", "data")
SDE_ZIP_URL = "https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip"
SDE_ZIP_PATH = os.path.join(CACHE_DIR, "sde.zip")
ZIP_PART_PATH = SDE_ZIP_PATH + ".part"  # 下载中断残留 = 断点，下次 Range 续传

# 已知的 SDE YAML 文件名（来自 sde.zip/fsd/ 或 bsd/）
YAML_FILES = {
    "typeIDs.yaml",  # ← 缓存名，zip 内实际名为 types.yaml（见 ZIP_LOOKUP）
    "groupIDs.yaml",  # ← 缓存名，zip 内实际名为 groups.yaml（见 ZIP_LOOKUP）
    "marketGroups.yaml",
    "metaGroups.yaml",
    "typeMaterials.yaml",
    "dogmaAttributes.yaml",
    "dogmaEffects.yaml",
    "iconIDs.yaml",
    "categories.yaml",
    "staStations.yaml",
    "stationOperations.yaml",
    "stationServices.yaml",
    "researchAgents.yaml",
    "npcCorporations.yaml",
    "agents.yaml",
}

# 缓存文件名 → zip 内实际文件名（当两者不一致时）
ZIP_LOOKUP = {
    "typeIDs.yaml": "types.yaml",
    "groupIDs.yaml": "groups.yaml",
}

# Universe 数据 JSON 缓存路径（避免每次从 ZIP 解析 50K+ YAML 文件）
UNIVERSE_CACHE_PATH = os.path.join(CACHE_DIR, "universe_data.json")

# 进程内 YAML 解析缓存：避免初始化时反复解析大文件（typeIDs.yaml 148MB 解析 ~29s）
# 初始化完成后由 clear_yaml_cache() 释放，避免长期占用内存
_YAML_CACHE: dict[str, dict] = {}
_YAML_CACHE_LOCK = threading.Lock()

# 大 YAML 首次解析的并发锁（load_yaml_async 双检锁，避免并发重复解析）
_load_lock: asyncio.Lock | None = None

# SDE zip 下载+提取的跨线程锁：asyncio.Lock 绑定事件循环，并行初始化步骤
# （items/sde_core/blueprints）及重试跨 asyncio.run 时会报 "bound to a different
# event loop"，并发下载冲突；threading.Lock 与线程/事件循环无关，保证只下载一次。
_zip_dl_lock = threading.Lock()


def cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, name)


def _all_cached() -> bool:
    return all(os.path.exists(cache_path(fname)) for fname in YAML_FILES)


def _universe_cache_has_names(systems: list) -> bool:
    """universe JSON 缓存有效性：至少一个星系带非空名。

    旧版缓存（名称全空，写入后污染 solar_system 表）应视为损坏，触发重新解析。
    """
    for s in systems:
        if (s.get("solar_system_name") or "").strip():
            return True
    return False


def _validate_and_finalize() -> None:
    """校验 zip 完整性并原子 rename；损坏则删 .part 抛错（下次从头下载）。"""
    try:
        with zipfile.ZipFile(ZIP_PART_PATH) as zf:
            if zf.testzip() is not None:
                raise zipfile.BadZipFile("corrupted member")
    except (zipfile.BadZipFile, zipfile.LargeZipFile):
        os.remove(ZIP_PART_PATH)
        raise
    os.replace(ZIP_PART_PATH, SDE_ZIP_PATH)


async def _download_zip(progress_cb: Callable[[int, str], None] | None = None) -> str:
    """下载 SDE zip 到 .part（断点续传 + 流式写盘）。由 _zip_dl_lock 保证串行。"""
    offset = os.path.getsize(ZIP_PART_PATH) if os.path.exists(ZIP_PART_PATH) else 0
    headers = {"Range": f"bytes={offset}-"} if offset else {}
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(SDE_ZIP_URL, headers=headers) as resp:
            if resp.status == 206:  # 断点续传
                mode = "ab"
                total = int(resp.headers.get("Content-Range", "/0").rsplit("/", 1)[1])
            elif resp.status == 200:  # 服务器不支持 Range → 全量重下
                offset = 0
                mode = "wb"
                total = int(resp.headers.get("Content-Length", 0))
            elif resp.status == 416 and offset > 0:
                # Range 不满足：.part 已完整（并发下载残留）→ 直接校验完成
                log.info("SDE 包 Range 不满足（.part 已完整），直接校验...")
                _validate_and_finalize()
                return SDE_ZIP_PATH
            else:
                resp.raise_for_status()
                return SDE_ZIP_PATH

            log.info(
                f"下载 SDE 数据包: {total / 1024 / 1024:.1f} MB"
                + (f"（从 {offset / 1024 / 1024:.1f} MB 续传）" if offset else "")
            )
            t_start = time.time()
            with open(ZIP_PART_PATH, mode) as f:
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    f.write(chunk)
                    if progress_cb:
                        done = os.path.getsize(ZIP_PART_PATH)
                        elapsed = max(0.001, time.time() - t_start)
                        speed = done / elapsed / 1024 / 1024
                        progress_cb(
                            min(99, int(done / max(total, 1) * 100)),
                            f"SDE 包下载 {done // 1048576}/{total // 1048576} MB ({speed:.1f} MB/s)",
                        )

    _validate_and_finalize()
    return SDE_ZIP_PATH


def _sync_ensure_zip(progress_cb: Callable[[int, str], None] | None = None) -> str:
    """线程安全的 zip 下载（threading.Lock 串行，跨线程/事件循环安全）。"""
    with _zip_dl_lock:
        if os.path.exists(SDE_ZIP_PATH):
            return SDE_ZIP_PATH
        asyncio.run(_download_zip(progress_cb))
        return SDE_ZIP_PATH


async def ensure_sde_zip(progress_cb: Callable[[int, str], None] | None = None) -> str:
    """确保 data/sde.zip 完整存在（断点续传 + 流式写盘 + 跨线程串行单飞）。

    - `.part` 残留 → 带 Range 头从断点续传（S3 静态托管支持 206）
    - 流式写盘：`iter_chunked` 边下边写，不再 112MB 全进内存
    - 完成后 zipfile.testzip() 校验，损坏删 `.part` 从头再来
    - 下载在后台线程执行：asyncio.Lock 绑定事件循环，并行步骤及重试跨
      asyncio.run 时不可靠；threading.Lock 与线程/事件循环无关，只下载一次。
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync_ensure_zip, progress_cb)
    return SDE_ZIP_PATH


def _sync_ensure_sde_cache(progress_cb: Callable[[int, str], None] | None = None) -> None:
    """线程安全的下载+提取（threading.Lock 串行）。"""
    with _zip_dl_lock:
        if _all_cached():
            return
        asyncio.run(_download_and_extract(progress_cb))


async def _download_and_extract(progress_cb: Callable[[int, str], None] | None = None) -> None:
    """下载 SDE zip + 提取所需 YAML（由 _zip_dl_lock 保证串行）。"""
    log.info("本地无 SDE 缓存，从 S3 下载 SDE 数据包 (~112 MB)...")
    log.info(f"  URL: {SDE_ZIP_URL}")
    await _download_zip(progress_cb)
    log.info("下载完成，提取 YAML 文件...")
    with zipfile.ZipFile(SDE_ZIP_PATH) as zf:
        for fname in sorted(YAML_FILES):
            zip_name = ZIP_LOOKUP.get(fname, fname)
            candidates = [p for p in zf.namelist() if p.endswith(zip_name)]
            if not candidates:
                log.warning(f"SDE 包中未找到 {zip_name} (→ {fname})")
                continue
            raw = zf.read(candidates[0]).decode("utf-8")
            dest = cache_path(fname)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(raw)
            log.info(f"  已缓存: {fname} ({len(raw) / 1024 / 1024:.1f} MB)")
    log.info("SDE YAML 缓存完成")


async def ensure_sde_cache(progress_cb: Callable[[int, str], None] | None = None):
    """确保 SDE zip 中所需的 YAML 文件已缓存到本地

    只会下载一次 zip，提取所有需要的 YAML 文件后缓存到 data/ 目录，
    同时将完整 zip 保存到磁盘以便 universe/ 目录遍历。

    下载+提取跨线程单飞（_zip_dl_lock）：items/sde_core/blueprints 等并行步骤
    同时进入时只执行一次，避免并发重复提取 148MB typeIDs.yaml。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if _all_cached():
        sizes = ", ".join(
            f"{fname}={os.path.getsize(cache_path(fname)) / 1024 / 1024:.1f}MB" for fname in sorted(YAML_FILES)
        )
        log.info(f"SDE YAML 缓存已就绪 ({sizes})")
        return

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync_ensure_sde_cache, progress_cb)


def _build_name_map(zip_path: str) -> dict[int, str]:
    """从 bsd/invNames.yaml 构建 {itemID: itemName} 映射（名称按 itemID 索引）。

    当前 SDE 的 region/constellation/solarsystem 名称不再内联，统一在 bsd/invNames.yaml。
    解析失败时返回空 dict（星系名降级为空串，不中断写库）。

    50 万条 itemID→name 首次解析约 28s，用 zip 同目录的 pkl 缓存持久化，
    后续加载 <0.1s；zip mtime 更新（SDE 新版本）自动失效重解析。
    """
    pkl_path = os.path.splitext(zip_path)[0] + "_invnames.pkl"
    try:
        if os.path.exists(pkl_path) and os.path.getmtime(pkl_path) >= os.path.getmtime(zip_path):
            with open(pkl_path, "rb") as f:
                cached = pickle.load(f)
            if isinstance(cached, dict):
                return cached
    except Exception:
        pass  # 缓存读失败 → 走正常解析

    result: dict[int, str] = {}
    _Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            raw = zf.read("bsd/invNames.yaml").decode("utf-8")
        rows = yaml.load(raw, Loader=_Loader) or []
        for row in rows:
            if isinstance(row, dict) and row.get("itemName"):
                try:
                    result[int(row["itemID"])] = row["itemName"]
                except (TypeError, ValueError):
                    continue
    except Exception as e:
        log.warning("invNames 名称解析失败，星系名将为空: %s", e)
        return result

    # 解析成功才原子写 pkl（写失败/并发写不中断主流程；临时文件名唯一避免多进程互踩）
    try:
        d = os.path.dirname(pkl_path)
        if d:
            os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".invnames_", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(result, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, pkl_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass
    return result


def _parse_universe_chunk(
    paths: list[str],
    zip_path: str,
    name_map: dict[int, str] | None = None,
) -> tuple[list, list, list, list]:
    """在线程池/进程池 worker 中解析一批 universe YAML 文件（CSafeLoader）

    兼容新旧两种 SDE 格式：
      - 新格式：region/constellation/solarsystem.yaml 仅含 ID，名称走 name_map
        （bsd/invNames.yaml 按 itemID 索引）；stargates 内嵌在 solarsystem.yaml（键 destination）
      - 旧格式：system.yaml 内联 solarSystemName；stargates 独立目录（destinationID）

    Args:
        paths: 该 worker 负责的 universe YAML 路径列表
        zip_path: SDE zip 路径
        name_map: {itemID: itemName} 名称映射（可选，缺失时名称兜底空串）

    Returns:
        (regions, constellations, systems, stargates)
    """
    _Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    name_map = name_map or {}
    regions: list[dict] = []
    constellations: list[dict] = []
    systems: list[dict] = []
    stargates: list[dict] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for path in paths:
            try:
                raw = zf.read(path).decode("utf-8")
            except Exception:
                continue

            try:
                data = yaml.load(raw, Loader=_Loader) or {}
            except Exception:
                continue

            parts = path.split("/")

            if "region.yaml" in path:
                region_id = data.get("regionID")
                if region_id is not None:
                    rid = int(region_id)
                    data["region_id"] = rid
                    data["region_name"] = name_map.get(rid, data.get("regionName", ""))
                    regions.append(data)

            elif "constellation.yaml" in path:
                cid = data.get("constellationID")
                if cid is not None:
                    cid = int(cid)
                    data["constellation_id"] = cid
                    data["constellation_name"] = name_map.get(cid, data.get("constellationName", ""))
                    constellations.append(data)

            elif path.endswith("solarsystem.yaml") or path.endswith("system.yaml"):
                sid = data.get("solarSystemID")
                if sid is not None:
                    sid = int(sid)
                    # 只保留业务字段（写入 solar_system 表用），避免把整个 YAML
                    # （stargates/planets/position 等）塞进 JSON 缓存导致体积膨胀
                    systems.append(
                        {
                            "solar_system_id": sid,
                            "solar_system_name": name_map.get(sid, data.get("solarSystemName", "")),
                            "security": data.get("security", data.get("securityStatus", 0.0)),
                            # 兼容键：write_universe 走 solar_system_id/solarSystemID 等 or 读取
                            "solarSystemID": sid,
                            "solarSystemName": data.get("solarSystemName", ""),
                            "regionID": data.get("regionID"),
                            "constellationID": data.get("constellationID"),
                        }
                    )
                    # 新格式：stargates 内嵌（键为 stargate_id，值为 {"destination": system_id}）
                    for sg_id, sg in (data.get("stargates") or {}).items():
                        dest = sg.get("destination") if isinstance(sg, dict) else None
                        if dest is not None:
                            stargates.append(
                                {
                                    "stargate_id": int(sg_id),
                                    "solar_system_id": sid,
                                    "destination_system_id": int(dest),
                                }
                            )

            elif "stargates/" in path:
                # 旧格式：独立目录，destinationID
                try:
                    sg_id = int(parts[-1].replace(".yaml", ""))
                    sys_id = int(parts[-3])
                except (ValueError, IndexError):
                    continue
                dest_id = data.get("destinationID")
                if sg_id and dest_id is not None:
                    stargates.append(
                        {
                            "stargate_id": sg_id,
                            "solar_system_id": sys_id,
                            "destination_system_id": int(dest_id),
                        }
                    )

    return regions, constellations, systems, stargates


def _parse_universe_chunk_with_names(paths: list[str], zip_path: str) -> tuple[list, list, list, list]:
    """进程池 worker：先加载名称映射（pkl 缓存秒级），再解析一批星系 YAML。

    name_map 有 50 万条 itemID→name，若作为参数 pickle 传给每个子进程开销大；
    改为各子进程独立从磁盘 pkl（_build_name_map 缓存）加载，参数只剩 paths/zip_path。
    """
    name_map = _build_name_map(zip_path)
    return _parse_universe_chunk(paths, zip_path, name_map)


async def ensure_universe_cache(progress_cb: Callable[[int, str], None] | None = None):
    """确保 SDE zip 已缓存，解析 universe/ 下全部星系并返回星系数据

    region/constellation/stargate 无业务读取，不再解析与写入——
    只保留 solar_system（星系名/安全等级），供星系搜索与星系名解析使用。

    返回: (regions, constellations, systems, stargates)，其中 regions/constellations/
          stargates 恒为空，systems 为星系 dict 列表，供 sde_loader.write_universe 写入。
    """
    await ensure_sde_cache(progress_cb)

    if not os.path.exists(SDE_ZIP_PATH):
        log.warning("SDE 压缩包未缓存，无法处理 universe 数据")
        return [], [], [], []

    # JSON 缓存快速路径：避免每次从 ZIP 解析 6000+ 星系 YAML
    if os.path.exists(UNIVERSE_CACHE_PATH):
        try:
            with open(UNIVERSE_CACHE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            cached_systems = data.get("systems", [])
            if not _universe_cache_has_names(cached_systems):
                # 旧缓存星系名全空（写入会污染 solar_system 表）→ 丢弃缓存重新解析
                log.warning("universe 缓存星系名为空，丢弃并重新解析")
            else:
                log.info(f"Universe JSON 缓存已加载: {len(cached_systems)} systems")
                return [], [], cached_systems, []
        except Exception as e:
            log.warning(f"Universe JSON 缓存读取失败，重新解析: {e}")

    log.info("正在并行解析 universe/ 星系 YAML 文件...")
    if progress_cb:
        progress_cb(10, "解析星系目录...")
    # 名称在 bsd/invNames.yaml（按 itemID 索引），解析前先确保主进程构建好
    # invnames.pkl（首次 ~28s，之后秒级；子进程 worker 各自从 pkl 加载）
    _build_name_map(SDE_ZIP_PATH)
    with zipfile.ZipFile(SDE_ZIP_PATH, "r") as zf:
        # 只解析星系文件（region/constellation/stargates 无业务使用，跳过以提速）
        all_paths = [
            p
            for p in zf.namelist()
            if p.startswith("universe/") and (p.endswith("solarsystem.yaml") or p.endswith("system.yaml"))
        ]
    total = len(all_paths)
    log.info(f"共 {total} 个星系 YAML 文件需要解析")
    if progress_cb:
        progress_cb(15, f"解析 {total} 个星系 YAML...")

    # 按 CPU 核心数并行切块（yaml 解析为 CPU 密集型）
    workers = min(os.cpu_count() or 2, 8)
    chunks = [all_paths[i::workers] for i in range(workers) if all_paths[i::workers]]

    t0 = time.time()
    systems: list[dict] = []

    # PyYAML C loader 的构造阶段持有 GIL，线程并行无效（8 线程 ≈ 单线程 ~168s），
    # 多进程真并行是唯一出路。文件量小（<200）时进程池启动开销不划算，直接线程池；
    # spawn 失败（如打包环境缺 freeze_support）时回退线程池。
    if len(all_paths) < 200:
        results = await asyncio.gather(
            *[asyncio.to_thread(_parse_universe_chunk_with_names, chunk, SDE_ZIP_PATH) for chunk in chunks]
        )
    else:
        loop = asyncio.get_running_loop()
        try:
            from concurrent.futures import ProcessPoolExecutor

            with ProcessPoolExecutor(max_workers=workers) as pool:
                results = await asyncio.gather(
                    *[
                        loop.run_in_executor(pool, _parse_universe_chunk_with_names, chunk, SDE_ZIP_PATH)
                        for chunk in chunks
                    ]
                )
        except Exception:
            log.warning("多进程解析不可用，回退线程池（较慢）", exc_info=True)
            results = await asyncio.gather(
                *[asyncio.to_thread(_parse_universe_chunk_with_names, chunk, SDE_ZIP_PATH) for chunk in chunks]
            )
    for _r_regions, _r_const, r_sys, _r_sg in results:
        systems.extend(r_sys)

    elapsed = time.time() - t0
    log.info(f"Universe 星系解析完成: {len(systems)} systems（耗时 {elapsed:.0f}s, {workers} workers）")
    if progress_cb:
        progress_cb(70, "星系数据解析完成")

    # 缓存为 JSON（下次启动秒级加载）
    try:
        with open(UNIVERSE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"systems": systems}, f, ensure_ascii=False)
        log.info(f"Universe 数据已缓存至: {UNIVERSE_CACHE_PATH}")
    except Exception as e:
        log.warning(f"Universe JSON 缓存写入失败（不影响使用）: {e}")

    return [], [], systems, []


def load_yaml(name: str) -> dict:
    """从本地缓存加载 SDE YAML 文件（CSafeLoader 加速；≥1MB 走磁盘 pickle 缓存；进程内二次缓存）

    磁盘 pickle 缓存：typeIDs.yaml（148MB，解析 ~29s）解析一次后持久化到 name.pkl，
    下次加载约 1-2s。SDE 版本更新（yaml 文件 mtime 变化）自动触发重新解析。

    注意：返回的是共享对象，调用方不得修改其内容。
    """
    with _YAML_CACHE_LOCK:
        if name in _YAML_CACHE:
            return _YAML_CACHE[name]
        path = cache_path(name)
        if not os.path.exists(path):
            return {}
        data = _load_yaml_from_disk(name, path)
        _YAML_CACHE[name] = data
        return data


_PICKLE_SIZE_THRESHOLD = 1024 * 1024  # ≥1MB 的 YAML 才启用磁盘 pickle 缓存（小文件解析本就快）


def _pickle_cache_path(name: str) -> str:
    """YAML 解析结果的磁盘缓存路径（name.yaml → name.pkl）"""
    return cache_path(name[: -len(".yaml")] + ".pkl") if name.endswith(".yaml") else cache_path(name + ".pkl")


def _load_yaml_from_disk(name: str, path: str) -> dict:
    """解析 YAML，优先命中磁盘 pickle 缓存（缓存不可用/损坏时静默回退正常解析）"""
    try:
        if os.path.getsize(path) >= _PICKLE_SIZE_THRESHOLD:
            pkl_path = _pickle_cache_path(name)
            if os.path.exists(pkl_path) and os.path.getmtime(pkl_path) >= os.path.getmtime(path):
                with open(pkl_path, "rb") as f:
                    cached = pickle.load(f)
                return cached if isinstance(cached, dict) else {}
    except Exception:
        pass  # 缓存读失败 → 走正常解析

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f, Loader=loader) or {}

    # 原子写 pkl（临时文件 + os.replace），解析失败/并发写不中断主流程
    try:
        if os.path.getsize(path) >= _PICKLE_SIZE_THRESHOLD:
            pkl_path = _pickle_cache_path(name)
            os.makedirs(os.path.dirname(pkl_path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(pkl_path), prefix=".yaml_", suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as f:
                    pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
                os.replace(tmp, pkl_path)
            except Exception:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception:
        pass
    return data


async def load_yaml_async(name: str) -> dict:
    """异步加载 SDE YAML：首次大文件（typeIDs.yaml 148MB 约 29s）在
    to_thread 中解析，不阻塞事件循环；二次命中进程内缓存（瞬时）。

    用模块级 asyncio.Lock 双检锁保证并发调用只解析一次。
    """
    global _load_lock
    if name in _YAML_CACHE:
        return _YAML_CACHE[name]
    if _load_lock is None:
        _load_lock = asyncio.Lock()
    async with _load_lock:
        if name in _YAML_CACHE:  # double-check：等待期间可能已被其它协程解析
            return _YAML_CACHE[name]
        return await asyncio.to_thread(load_yaml, name)


def clear_yaml_cache() -> None:
    """释放 YAML 解析缓存（初始化完成后调用，释放 typeIDs.yaml 等大文件内存）"""
    with _YAML_CACHE_LOCK:
        _YAML_CACHE.clear()


def reset_async_locks() -> None:
    """重置模块级 asyncio.Lock（_load_lock）。

    asyncio.Lock 惰性绑定首次使用的事件循环，初始化重试会新建 asyncio.run()
    导致跨循环复用报错，故每次 asyncio.run 前调用（由 InitService.start 负责）。
    SDE 下载用 threading.Lock（_zip_dl_lock），与事件循环无关，无需重置。
    """
    global _load_lock
    _load_lock = None
