"""SDE universe 路径层级 → 星系区域归属（task-15）。

根因：SDE zip 的 `solarsystem.yaml` **不含** regionID/constellationID，归属只在路径
（`universe/<域>/<区域目录>/<星座目录>/<星系目录>/`）+ `region.yaml`/`constellation.yaml`
里；旧实现只写星系名，导致真实 `reference.db.solar_system.region_id` 全 NULL，订单
「是否在首位」反查挂单市场区域失败。

本文件用**临时迷你 zip**验证解析，用内存 sqlite 验证幂等回填 —— 不依赖真实库、不联网。
"""

import sqlite3
import zipfile

import aiosqlite
import pytest
import yaml

from services.importers import sde_cache, sde_loader


def _mini_sde_zip(tmp_path) -> str:
    """构造 SDE universe 路径层级的迷你 zip（结构照真实 data/sde.zip）。"""
    path = tmp_path / "sde_mini.zip"
    with zipfile.ZipFile(path, "w") as zf:
        # 普通星域：目录名 = 星域名（真实数据里 A821-A / KER-EU 这类）
        zf.writestr("universe/eve/10000002/region.yaml", yaml.safe_dump({"regionID": 10000002}))
        zf.writestr(
            "universe/eve/10000002/20000020/constellation.yaml",
            yaml.safe_dump({"constellationID": 20000020}),
        )
        zf.writestr(
            "universe/eve/10000002/20000020/Jita/solarsystem.yaml",
            yaml.safe_dump({"solarSystemID": 30000142}),
        )
        # 目录名与库内名有空格差异（OldManStar vs Old Man Star → 归一匹配）
        zf.writestr("universe/eve/10000003/region.yaml", yaml.safe_dump({"regionID": 10000003}))
        zf.writestr(
            "universe/eve/10000003/20000021/constellation.yaml",
            yaml.safe_dump({"constellationID": 20000021}),
        )
        zf.writestr(
            "universe/eve/10000003/20000021/OldManStar/solarsystem.yaml",
            yaml.safe_dump({"solarSystemID": 30000001}),
        )
        # 只有 region.yaml、没有 constellation.yaml → constellation_id 应为 None
        zf.writestr("universe/eve/10000004/region.yaml", yaml.safe_dump({"regionID": 10000004}))
        # 名称匹配不上 → 读该星系 YAML 的 solarSystemID 兜底
        zf.writestr(
            "universe/eve/10000004/20000022/Mystery/solarsystem.yaml",
            yaml.safe_dump({"solarSystemID": 30000999}),
        )
        # abyssal 域：目录名是数字 → 直接当 system id
        zf.writestr("universe/abyssal/12000001/region.yaml", yaml.safe_dump({"regionID": 12000001}))
        zf.writestr(
            "universe/abyssal/12000001/22000001/constellation.yaml",
            yaml.safe_dump({"constellationID": 22000001}),
        )
        zf.writestr(
            "universe/abyssal/12000001/22000001/32000001/solarsystem.yaml",
            yaml.safe_dump({"solarSystemID": 32000001}),
        )
        # 非星系文件必须被忽略
        zf.writestr("universe/landmarks/landmarks.yaml", yaml.safe_dump({"1": {"x": 1}}))
    return str(path)


def test_load_universe_geo_uses_path_hierarchy(tmp_path):
    """解析 region/constellation 层级；星系 YAML 不含归属也能从路径推出。"""
    zip_path = _mini_sde_zip(tmp_path)
    geo = sde_cache.load_universe_geo(zip_path, {"Jita": 30000142, "Old Man Star": 30000001})
    assert geo[30000142] == (10000002, 20000020)
    assert geo[30000001] == (10000003, 20000021), "OldManStar ↔ Old Man Star 应归一匹配"
    assert geo[30000999] == (10000004, None), "名称匹配不上时读 YAML solarSystemID 兜底"
    assert geo[32000001] == (12000001, 22000001), "数字目录名直接当 system id"


def test_parse_universe_chunk_attaches_region(tmp_path):
    """全量解析路径（ensure_universe_cache → _parse_universe_chunk）也要带区域归属。"""
    zip_path = _mini_sde_zip(tmp_path)
    with zipfile.ZipFile(zip_path) as zf:
        geo_maps = sde_cache._universe_geo_maps(zf)
    _regions, _consts, systems, _ = sde_cache._parse_universe_chunk(
        ["universe/eve/10000002/20000020/Jita/solarsystem.yaml"], zip_path, {}, geo_maps
    )
    assert len(systems) == 1
    assert systems[0]["region_id"] == 10000002
    assert systems[0]["constellation_id"] == 20000020


def test_attach_universe_geo_fills_only_none():
    geo = {30000142: (10000002, 20000020), 30000001: (10000003, 20000021)}
    systems = [
        {"solar_system_id": 30000142, "region_id": None, "constellation_id": None},
        {"solar_system_id": 30000001, "region_id": 999, "constellation_id": 999},  # 已有值不覆盖
    ]
    filled = sde_cache._attach_universe_geo(systems, geo)
    assert filled == 1
    assert systems[0]["region_id"] == 10000002 and systems[0]["constellation_id"] == 20000020
    assert systems[1]["region_id"] == 999 and systems[1]["constellation_id"] == 999


def _ref_db_with_systems() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE solar_system ("
        "solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT, "
        "region_id INTEGER, constellation_id INTEGER, security REAL)"
    )
    conn.executemany(
        "INSERT INTO solar_system VALUES (?, ?, ?, ?, 0.0)",
        [
            (30000142, "Jita", None, None),
            (30000001, "Old Man Star", None, None),
            (30000200, "AlreadyFilled", 10000002, 20000020),
            (999999, "UnknownSystem", None, None),  # geo 里没有 → 保持 NULL
        ],
    )
    return conn


def test_region_backfill_only_null_and_idempotent(tmp_path):
    """增量回填：只补 NULL、已有值不动、geo 缺失的保留 NULL；第二轮为空（幂等）。"""
    zip_path = _mini_sde_zip(tmp_path)
    conn = _ref_db_with_systems()
    geo = sde_cache.load_universe_geo(zip_path, {"Jita": 30000142, "Old Man Star": 30000001})

    def _existing() -> list[tuple[int, int | None, int | None]]:
        return [
            (int(r[0]), r[1], r[2])
            for r in conn.execute("SELECT solar_system_id, region_id, constellation_id FROM solar_system")
        ]

    rows = sde_loader._region_backfill_rows(_existing(), geo)
    assert len(rows) == 2, "只补 Jita / Old Man Star，不碰已填行与 geo 缺失行"
    conn.executemany(sde_loader._SYSTEM_GEO_UPDATE_SQL, rows)

    got = {
        int(r[0]): (r[1], r[2])
        for r in conn.execute("SELECT solar_system_id, region_id, constellation_id FROM solar_system")
    }
    assert got[30000142] == (10000002, 20000020)
    assert got[30000001] == (10000003, 20000021)
    assert got[30000200] == (10000002, 20000020), "已有值不能被覆盖"
    assert got[999999] == (None, None), "SDE 没给的保留 NULL（不误写）"

    # 幂等：第二轮没有可补的行
    assert sde_loader._region_backfill_rows(_existing(), geo) == []


def test_region_backfill_rows_skips_systems_absent_from_geo():
    geo = {30000142: (10000002, 20000020)}
    assert sde_loader._region_backfill_rows([(30000142, None, None), (999, None, None)], geo) == [
        (10000002, 20000020, 30000142)
    ]


@pytest.mark.asyncio
async def test_region_zh_column_helper_adds_once_and_is_idempotent():
    """06-3 回归：业务侧的「可重建缓存补列」抽成唯一入口，只在缺列时 ALTER 一次。

    铁律禁止业务代码裸 `ALTER TABLE`；`reference.db` 是可重建缓存、不进 migrations，
    所以改成 `_ensure_region_zh_column()`：存在性检查 + 只在缺失时补 + log 说明。
    """
    from services.importers import sde_loader

    async with aiosqlite.connect(":memory:") as db:
        await db.execute("CREATE TABLE region (region_id INTEGER PRIMARY KEY, region_name TEXT)")
        assert await sde_loader._ensure_region_zh_column(db) is True, "缺列 → 应补"
        cols = {r[1] for r in await (await db.execute("PRAGMA table_info(region)")).fetchall()}
        assert "zh_name" in cols
        assert await sde_loader._ensure_region_zh_column(db) is False, "第二次应是零操作（幂等）"
