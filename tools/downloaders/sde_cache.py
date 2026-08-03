"""
SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

被 getitems.py、geticon.py、getimplantdata.py、sde_loader.py 等模块共用。
"""

import asyncio
import io
import json
import os
import time
import zipfile

import aiohttp
import yaml

from core.logger import log
from core.paths import reference_db_path

CACHE_DIR = os.path.join(os.path.dirname(reference_db_path()), "..", "data")
SDE_ZIP_URL = "https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip"
SDE_ZIP_PATH = os.path.join(CACHE_DIR, "sde.zip")

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


async def ensure_sde_cache():
    """确保 SDE zip 中所需的 YAML 文件已缓存到本地

    只会下载一次 zip，提取所有需要的 YAML 文件后缓存到 data/ 目录，
    同时将完整 zip 保存到磁盘以便 universe/ 目录遍历。

    如果 universe JSON 缓存已存在（说明已有完整解析结果），
    则跳过非必要 YAML 文件的下载，仅确保 universe 必要的 typeIDs.yaml 就绪。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    # universe JSON 缓存存在时，只需确保 typeIDs.yaml 等小文件就绪即可
    if os.path.exists(UNIVERSE_CACHE_PATH):
        yamls_ok = _all_cached()
        if yamls_ok:
            sizes = ", ".join(
                f"{fname}={os.path.getsize(cache_path(fname)) / 1024 / 1024:.1f}MB" for fname in sorted(YAML_FILES)
            )
            log.info(f"SDE YAML 缓存已就绪 ({sizes})")
            return
        # 个别 YAML 缺失（如首次提取不完全），走下载流程补充

    yamls_ok = _all_cached()
    zip_ok = os.path.exists(SDE_ZIP_PATH)
    if yamls_ok and zip_ok:
        sizes = ", ".join(
            f"{fname}={os.path.getsize(cache_path(fname)) / 1024 / 1024:.1f}MB" for fname in sorted(YAML_FILES)
        )
        log.info(f"SDE YAML 缓存已就绪 ({sizes})")
        return

    log.info("本地无 SDE 缓存，从 S3 下载 SDE 数据包 (~112 MB)...")
    log.info(f"  URL: {SDE_ZIP_URL}")

    async with aiohttp.ClientSession() as session:
        async with session.get(SDE_ZIP_URL, timeout=aiohttp.ClientTimeout(total=600)) as resp:
            resp.raise_for_status()
            data = await resp.read()

    log.info(f"下载完成: {len(data) / 1024 / 1024:.1f} MB")

    # 保存 zip 到磁盘（供 universe/ 目录遍历使用）
    with open(SDE_ZIP_PATH, "wb") as f:
        f.write(data)

    # 提取各个 YAML 文件
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for fname in sorted(YAML_FILES):
            # 用 endswith 匹配，兼容 fsd/ bsd/ 等不同路径前缀
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


def _build_name_map(zip_path: str) -> dict[int, str]:
    """从 bsd/invNames.yaml 构建 {itemID: itemName} 映射（名称按 itemID 索引）。

    当前 SDE 的 region/constellation/solarsystem 名称不再内联，统一在 bsd/invNames.yaml。
    解析失败时返回空 dict（星系名降级为空串，不中断写库）。
    """
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


def _parse_universe_chunk(
    paths: list[str],
    zip_path: str,
    name_map: dict[int, str] | None = None,
) -> tuple[list, list, list, list]:
    """在线程池 worker 中解析一批 universe YAML 文件（CSafeLoader，每 worker 独立加载器）

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
                    data["solar_system_id"] = sid
                    data["solar_system_name"] = name_map.get(sid, data.get("solarSystemName", ""))
                    data["security"] = data.get("security", data.get("securityStatus", 0.0))
                    systems.append(data)
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


async def ensure_universe_cache():
    """确保 SDE zip 已缓存，遍历 universe/ 目录树并返回解析后的数据字典

    返回: (regions, constellations, systems, stargates)
      每个元素是字典列表，供 sde_loader.write_universe 写入数据库
    """
    await ensure_sde_cache()

    if not os.path.exists(SDE_ZIP_PATH):
        log.warning("SDE 压缩包未缓存，无法处理 universe 数据")
        return [], [], [], []

    # JSON 缓存快速路径：避免每次从 ZIP 解析 50K+ YAML 文件
    if os.path.exists(UNIVERSE_CACHE_PATH):
        try:
            with open(UNIVERSE_CACHE_PATH, encoding="utf-8") as f:
                data = json.load(f)
            systems = data.get("systems", [])
            if not _universe_cache_has_names(systems):
                # 旧缓存星系名全空（写入会污染 solar_system 表）→ 丢弃缓存重新解析
                log.warning("universe 缓存星系名为空，丢弃并重新解析")
                data = None
            else:
                log.info(
                    f"Universe JSON 缓存已加载: "
                    f"{len(data.get('regions', []))} regions, "
                    f"{len(data.get('constellations', []))} constellations, "
                    f"{len(systems)} systems, "
                    f"{len(data.get('stargates', []))} stargates"
                )
                return (
                    data.get("regions", []),
                    data.get("constellations", []),
                    systems,
                    data.get("stargates", []),
                )
        except Exception as e:
            log.warning(f"Universe JSON 缓存读取失败，重新解析: {e}")

    log.info("正在并行解析 universe/ 目录下的 YAML 文件...")
    # 名称在 bsd/invNames.yaml（按 itemID 索引），解析前构建一次映射供各 worker 共享
    name_map = _build_name_map(SDE_ZIP_PATH)
    with zipfile.ZipFile(SDE_ZIP_PATH, "r") as zf:
        all_paths = [p for p in zf.namelist() if p.startswith("universe/") and p.endswith(".yaml")]
    total = len(all_paths)
    log.info(f"共 {total} 个 universe YAML 文件需要解析")

    # 按 CPU 核心数并行切块（yaml 解析为 CPU 密集型）
    workers = min(os.cpu_count() or 2, 8)
    chunks = [all_paths[i::workers] for i in range(workers) if all_paths[i::workers]]

    t0 = time.time()
    regions: list[dict] = []
    constellations: list[dict] = []
    systems: list[dict] = []
    stargates: list[dict] = []

    results = await asyncio.gather(
        *[asyncio.to_thread(_parse_universe_chunk, chunk, SDE_ZIP_PATH, name_map) for chunk in chunks]
    )
    for r_regions, r_const, r_sys, r_sg in results:
        regions.extend(r_regions)
        constellations.extend(r_const)
        systems.extend(r_sys)
        stargates.extend(r_sg)

    elapsed = time.time() - t0
    log.info(
        f"Universe 数据解析完成: "
        f"{len(regions)} regions, {len(constellations)} constellations, "
        f"{len(systems)} systems, {len(stargates)} stargates "
        f"(耗时 {elapsed:.0f}s, {workers} 线程)"
    )

    # 缓存为 JSON（下次启动秒级加载）
    try:
        with open(UNIVERSE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "regions": regions,
                    "constellations": constellations,
                    "systems": systems,
                    "stargates": stargates,
                },
                f,
                ensure_ascii=False,
            )
        log.info(f"Universe 数据已缓存至: {UNIVERSE_CACHE_PATH}")
    except Exception as e:
        log.warning(f"Universe JSON 缓存写入失败（不影响使用）: {e}")

    return regions, constellations, systems, stargates


def load_yaml(name: str) -> dict:
    """从本地缓存加载 SDE YAML 文件（使用 CLoader 加速，进程内二次解析缓存）

    注意：返回的是共享对象，调用方不得修改其内容。
    """
    if name in _YAML_CACHE:
        return _YAML_CACHE[name]
    path = cache_path(name)
    if not os.path.exists(path):
        return {}
    loader = getattr(yaml, "CLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f, Loader=loader) or {}
    _YAML_CACHE[name] = data
    return data


def clear_yaml_cache() -> None:
    """释放 YAML 解析缓存（初始化完成后调用，释放 typeIDs.yaml 等大文件内存）"""
    _YAML_CACHE.clear()
