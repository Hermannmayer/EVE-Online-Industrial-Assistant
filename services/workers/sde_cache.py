"""
SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

被 getitems.py、geticon.py、getimplantdata.py、sde_loader.py 等模块共用。
"""
import asyncio
import io
import os
import zipfile
from pathlib import Path

import aiohttp
import yaml

from core.logger import log
from core.paths import reference_db_path

CACHE_DIR = os.path.join(os.path.dirname(reference_db_path()), "..", "data")
SDE_ZIP_URL = "https://eve-static-data-export.s3-eu-west-1.amazonaws.com/tranquility/sde.zip"
SDE_ZIP_PATH = os.path.join(CACHE_DIR, "sde.zip")

# 已知的 SDE YAML 文件名（来自 sde.zip/fsd/ 或 bsd/）
YAML_FILES = {
    "typeIDs.yaml",
    "groupIDs.yaml",
    "marketGroups.yaml",
    "metaGroups.yaml",
    "typeMaterials.yaml",
    "dogmaAttributes.yaml",
    "dogmaEffects.yaml",
    "iconIDs.yaml",
    "categories.yaml",
    "staStations.yaml",
    "stationOperations.yaml",
    "operationServices.yaml",
    "stationServices.yaml",
    "researchAgents.yaml",
    "npcCorporations.yaml",
    "agents.yaml",
}


def cache_path(name: str) -> str:
    return os.path.join(CACHE_DIR, name)


def _all_cached() -> bool:
    return all(os.path.exists(cache_path(fname)) for fname in YAML_FILES)


async def ensure_sde_cache():
    """确保 SDE zip 中所需的 YAML 文件已缓存到本地

    只会下载一次 zip，提取所有需要的 YAML 文件后缓存到 data/ 目录，
    同时将完整 zip 保存到磁盘以便 universe/ 目录遍历。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    yamls_ok = _all_cached()
    zip_ok = os.path.exists(SDE_ZIP_PATH)
    if yamls_ok and zip_ok:
        sizes = ", ".join(
            f"{fname}={os.path.getsize(cache_path(fname)) / 1024 / 1024:.1f}MB"
            for fname in sorted(YAML_FILES)
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
            candidates = [p for p in zf.namelist() if p.endswith(fname)]
            if not candidates:
                log.warning(f"SDE 包中未找到 {fname}")
                continue
            raw = zf.read(candidates[0]).decode("utf-8")
            dest = cache_path(fname)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(raw)
            log.info(f"  已缓存: {fname} ({len(raw) / 1024 / 1024:.1f} MB)")

    log.info("SDE YAML 缓存完成")


async def ensure_universe_cache():
    """确保 SDE zip 已缓存，遍历 universe/ 目录树并返回解析后的数据字典

    返回: (regions, constellations, systems, stargates)
      每个元素是字典列表，供 sde_loader.write_universe 写入数据库
    """
    await ensure_sde_cache()

    if not os.path.exists(SDE_ZIP_PATH):
        log.warning("SDE 压缩包未缓存，无法处理 universe 数据")
        return [], [], [], []

    log.info("正在解析 universe/ 目录下的 YAML 文件...")
    regions: list[dict] = []
    constellations: list[dict] = []
    systems: list[dict] = []
    stargates: list[dict] = []

    with zipfile.ZipFile(SDE_ZIP_PATH, "r") as zf:
        all_paths = [p for p in zf.namelist() if p.startswith("universe/") and p.endswith(".yaml")]

        for path in all_paths:
            try:
                raw = zf.read(path).decode("utf-8")
            except Exception:
                continue

            try:
                data = yaml.safe_load(raw) or {}
            except Exception:
                continue

            parts = path.split("/")

            if "region.yaml" in path and len(parts) >= 3:
                # universe/<region_id>/region.yaml
                region_id = int(parts[1])
                data["region_id"] = region_id
                regions.append(data)

            elif "constellation.yaml" in path and len(parts) >= 5:
                # universe/<region_id>/constellations/<constellation_id>/constellation.yaml
                cid = data.get("constellationID")
                if cid is not None:
                    data["constellation_id"] = cid
                    constellations.append(data)

            elif "system.yaml" in path and len(parts) >= 7:
                # universe/<region_id>/constellations/<const_id>/systems/<system_id>/system.yaml
                sid = data.get("solarSystemID")
                if sid is not None:
                    data["solar_system_id"] = sid
                    systems.append(data)

            elif "stargates/" in path:
                # universe/<region_id>/constellations/<const_id>/systems/<sys_id>/stargates/<sgid>.yaml
                try:
                    sg_id = int(parts[-1].replace(".yaml", ""))
                    sys_id = int(parts[-3])
                except (ValueError, IndexError):
                    continue
                dest_id = data.get("destinationID")
                if sg_id and dest_id is not None:
                    stargates.append({
                        "stargate_id": sg_id,
                        "solar_system_id": sys_id,
                        "destination_system_id": dest_id,
                    })

    log.info(
        f"Universe 数据解析完成: "
        f"{len(regions)} regions, {len(constellations)} constellations, "
        f"{len(systems)} systems, {len(stargates)} stargates"
    )
    return regions, constellations, systems, stargates


def load_yaml(name: str) -> dict:
    """从本地缓存加载 SDE YAML 文件（使用 CLoader 加速）"""
    path = cache_path(name)
    if not os.path.exists(path):
        return {}
    loader = getattr(yaml, "CLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=loader) or {}
