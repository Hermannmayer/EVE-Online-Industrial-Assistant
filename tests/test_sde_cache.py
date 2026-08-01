"""SDE 缓存工具测试 — tools/downloaders/sde_cache.py

覆盖:
  - load_yaml 进程内缓存（避免初始化反复解析 typeIDs.yaml 大文件）
  - clear_yaml_cache 释放缓存
  - universe YAML 解析（新格式：名称走 name_map、stargates 内嵌 destination）
"""

import io
import zipfile
from unittest.mock import patch

import yaml

from tools.downloaders.sde_cache import clear_yaml_cache, load_yaml


def _make_mini_universe_zip():
    """构造迷你 SDE zip：新格式 region/constellation/solarsystem + bsd/invNames。

    对应真实 SDE 结构:
      - region.yaml / constellation.yaml 仅含 ID（名称在 bsd/invNames.yaml）
      - solarsystem.yaml 内嵌 stargates 字典（键 destination）
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "universe/eve/10000001/1000000001/30000142/solarsystem.yaml",
            "solarSystemID: 30000142\n"
            "security: 0.9\n"
            "constellationID: 1000000001\n"
            "regionID: 10000001\n"
            "stargates:\n"
            "  50000101:\n"
            "    destination: 30000143\n"
            "  50000102:\n"
            "    destination: 30000150\n",
        )
        zf.writestr(
            "universe/eve/10000001/1000000001/region.yaml",
            "regionID: 10000001\nconstellationID: 1000000001\n",
        )
        zf.writestr(
            "universe/eve/10000001/1000000001/constellation.yaml",
            "constellationID: 1000000001\nregionID: 10000001\n",
        )
        zf.writestr(
            "bsd/invNames.yaml",
            "- itemID: 10000001\n  itemName: The Forge\n"
            "- itemID: 1000000001\n  itemName: Perimeter\n"
            "- itemID: 30000142\n  itemName: Jita\n"
            "- itemID: 30000143\n  itemName: Maire\n"
            "- itemID: 30000150\n  itemName: Muvolailen\n",
        )
    buf.seek(0)
    return buf


def _make_loader(tmp_path, monkeypatch, filename="test.yaml", content="key: value"):
    """写临时 YAML 文件并把 cache_path 指向临时目录"""
    (tmp_path / filename).write_text(content, encoding="utf-8")
    monkeypatch.setattr("tools.downloaders.sde_cache.cache_path", lambda name: str(tmp_path / name))


class TestLoadYamlCache:
    def test_parses_once_and_reuses(self, tmp_path, monkeypatch):
        """同一文件二次加载走缓存，yaml.load 只执行一次"""
        _make_loader(tmp_path, monkeypatch)
        clear_yaml_cache()

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("tools.downloaders.sde_cache.yaml.load", side_effect=counting_load):
            first = load_yaml("test.yaml")
            second = load_yaml("test.yaml")

        assert calls["n"] == 1
        assert first is second  # 共享同一缓存对象
        clear_yaml_cache()

    def test_clear_yaml_cache_forces_reparse(self, tmp_path, monkeypatch):
        """clear_yaml_cache 后再次加载会重新解析"""
        _make_loader(tmp_path, monkeypatch)
        clear_yaml_cache()

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("tools.downloaders.sde_cache.yaml.load", side_effect=counting_load):
            load_yaml("test.yaml")
            load_yaml("test.yaml")
            assert calls["n"] == 1

            clear_yaml_cache()
            load_yaml("test.yaml")
            assert calls["n"] == 2

        clear_yaml_cache()

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        """文件不存在返回空 dict"""
        clear_yaml_cache()
        monkeypatch.setattr("tools.downloaders.sde_cache.cache_path", lambda name: str(tmp_path / name))
        assert load_yaml("nonexistent.yaml") == {}
        clear_yaml_cache()


class TestUniverseParsing:
    """universe YAML 解析 — 新格式（名称走 name_map / stargates 内嵌）"""

    def test_parse_universe_chunk_new_format(self, tmp_path):
        """新格式：region/constellation/system 名称从 name_map 解析，stargates 键为 destination"""
        from tools.downloaders.sde_cache import _parse_universe_chunk

        zip_path = tmp_path / "mini_sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())

        name_map = {
            10000001: "The Forge",
            1000000001: "Perimeter",
            30000142: "Jita",
            30000143: "Maire",
            30000150: "Muvolailen",
        }
        paths = [
            "universe/eve/10000001/1000000001/region.yaml",
            "universe/eve/10000001/1000000001/constellation.yaml",
            "universe/eve/10000001/1000000001/30000142/solarsystem.yaml",
        ]
        regions, constellations, systems, stargates = _parse_universe_chunk(paths, str(zip_path), name_map)

        assert len(regions) == 1
        assert regions[0]["region_id"] == 10000001
        assert regions[0]["region_name"] == "The Forge"
        assert len(constellations) == 1
        assert constellations[0]["constellation_id"] == 1000000001
        assert constellations[0]["constellation_name"] == "Perimeter"
        assert len(systems) == 1
        assert systems[0]["solar_system_id"] == 30000142
        assert systems[0]["solar_system_name"] == "Jita", "名称应从 name_map 解析而非空串"
        assert systems[0]["security"] == 0.9
        assert len(stargates) == 2, "内嵌 stargates 应解析出 2 条"
        dests = sorted(g["destination_system_id"] for g in stargates)
        assert dests == [30000143, 30000150]
        assert all(g["solar_system_id"] == 30000142 for g in stargates)

    def test_parse_universe_chunk_legacy_format(self, tmp_path):
        """旧格式兼容：system.yaml（名称内联）+ 独立 stargates/ 目录（destinationID）"""
        from tools.downloaders.sde_cache import _parse_universe_chunk

        zip_path = tmp_path / "legacy.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "universe/eve/10000001/1000000001/30000142/system.yaml",
                "solarSystemID: 30000142\nsolarSystemName: Jita\nsecurity: 0.9\n",
            )
            zf.writestr(
                "universe/eve/10000001/1000000001/30000142/stargates/50000101.yaml",
                "destinationID: 30000143\n",
            )
        paths = [
            "universe/eve/10000001/1000000001/30000142/system.yaml",
            "universe/eve/10000001/1000000001/30000142/stargates/50000101.yaml",
        ]
        regions, constellations, systems, stargates = _parse_universe_chunk(paths, str(zip_path))

        assert len(regions) == 0
        assert len(constellations) == 0
        assert len(systems) == 1
        assert systems[0]["solar_system_id"] == 30000142
        assert systems[0]["solar_system_name"] == "Jita"
        assert len(stargates) == 1
        assert stargates[0]["stargate_id"] == 50000101
        assert stargates[0]["destination_system_id"] == 30000143

    def test_build_name_map_from_inv_names(self, tmp_path):
        """从 bsd/invNames.yaml 构建 {itemID: itemName} 映射"""
        from tools.downloaders.sde_cache import _build_name_map

        zip_path = tmp_path / "mini_sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())

        name_map = _build_name_map(str(zip_path))
        assert name_map[10000001] == "The Forge"
        assert name_map[1000000001] == "Perimeter"
        assert name_map[30000142] == "Jita"

    def test_parse_region_name_fallback_when_no_name_map(self, tmp_path):
        """无 name_map 时 region_name 兜底为空串而非报错"""
        from tools.downloaders.sde_cache import _parse_universe_chunk

        zip_path = tmp_path / "mini_sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())

        regions, _const, _sys, _sg = _parse_universe_chunk(
            ["universe/eve/10000001/1000000001/region.yaml"], str(zip_path)
        )
        assert len(regions) == 1
        assert regions[0]["region_id"] == 10000001
        assert regions[0].get("region_name", "") == ""
