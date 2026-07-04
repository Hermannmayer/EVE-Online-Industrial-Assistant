"""
SDE zip 缓存共享工具 — 下载/缓存/加载 SDE 的 YAML 数据文件

被 getitems.py、geticon.py、getimplantdata.py、sde_loader.py 等模块共用。
"""
import io
import json
import os
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
            log.info(
                f"Universe JSON 缓存已加载: "
                f"{len(data.get('regions', []))} regions, "
                f"{len(data.get('constellations', []))} constellations, "
                f"{len(data.get('systems', []))} systems, "
                f"{len(data.get('stargates', []))} stargates"
            )
            return (
                data.get("regions", []),
                data.get("constellations", []),
                data.get("systems", []),
                data.get("stargates", []),
            )
        except Exception as e:
            log.warning(f"Universe JSON 缓存读取失败，重新解析: {e}")

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

            if "region.yaml" in path:
                # universe/<region_id>/region.yaml
                region_id = data.get("regionID")
                if region_id is not None:
                    data["region_id"] = int(region_id)
                    regions.append(data)

            elif "constellation.yaml" in path:
                # universe/<region_id>/constellations/<constellation_id>/constellation.yaml
                cid = data.get("constellationID")
                if cid is not None:
                    data["constellation_id"] = int(cid)
                    constellations.append(data)

            elif "system.yaml" in path:
                # universe/<region_id>/constellations/<const_id>/systems/<system_id>/system.yaml
                sid = data.get("solarSystemID")
                if sid is not None:
                    data["solar_system_id"] = int(sid)
                    data["solar_system_name"] = data.get("solarSystemName", "")
                    data["security"] = data.get("security", data.get("securityStatus", 0.0))
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
                        "destination_system_id": int(dest_id),
                    })

    log.info(
        f"Universe 数据解析完成: "
        f"{len(regions)} regions, {len(constellations)} constellations, "
        f"{len(systems)} systems, {len(stargates)} stargates"
    )

    # 缓存为 JSON（下次启动秒级加载）
    try:
        with open(UNIVERSE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "regions": regions,
                "constellations": constellations,
                "systems": systems,
                "stargates": stargates,
            }, f, ensure_ascii=False)
        log.info(f"Universe 数据已缓存至: {UNIVERSE_CACHE_PATH}")
    except Exception as e:
        log.warning(f"Universe JSON 缓存写入失败（不影响使用）: {e}")

    return regions, constellations, systems, stargates


def load_yaml(name: str) -> dict:
    """从本地缓存加载 SDE YAML 文件（使用 CLoader 加速）"""
    path = cache_path(name)
    if not os.path.exists(path):
        return {}
    loader = getattr(yaml, "CLoader", yaml.SafeLoader)
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=loader) or {}
