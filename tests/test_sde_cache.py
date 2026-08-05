"""SDE 缓存工具测试 — tools/downloaders/sde_cache.py

覆盖:
  - load_yaml 进程内缓存（避免初始化反复解析 typeIDs.yaml 大文件）
  - clear_yaml_cache 释放缓存
  - universe YAML 解析（新格式：名称走 name_map、stargates 内嵌 destination）
"""

import asyncio
import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
import yaml

from tools.downloaders.sde_cache import (
    _universe_cache_has_names,
    clear_yaml_cache,
    ensure_sde_zip,
    ensure_universe_cache,
    load_yaml,
    load_yaml_async,
)


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


class TestUniverseCacheSelfHeal:
    """universe JSON 缓存星系名全空 → 判定损坏并重新解析（防污染 solar_system 表）"""

    async def _async_noop(self, *args, **kwargs):
        return None

    def test_has_names_detection(self):
        assert _universe_cache_has_names([{"solar_system_name": ""}, {"solar_system_name": None}]) is False
        assert _universe_cache_has_names([{"solar_system_name": ""}, {"solar_system_name": "Jita"}]) is True

    def test_empty_name_cache_triggers_reparse(self, tmp_path, monkeypatch):
        """星系名全空的旧缓存 → 丢弃并重新解析，缓存与返回数据均带名字"""
        cache_file = tmp_path / "universe_data.json"
        cache_file.write_text(
            json.dumps(
                {
                    "regions": [],
                    "constellations": [],
                    "systems": [{"solar_system_id": 30000142, "solar_system_name": ""}],
                    "stargates": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("tools.downloaders.sde_cache.UNIVERSE_CACHE_PATH", str(cache_file))

        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())
        monkeypatch.setattr("tools.downloaders.sde_cache.SDE_ZIP_PATH", str(zip_path))
        monkeypatch.setattr("tools.downloaders.sde_cache.ensure_sde_cache", self._async_noop)

        _regions, _const, systems, _sg = asyncio.run(ensure_universe_cache())

        jita = [s for s in systems if s["solar_system_id"] == 30000142][0]
        assert jita["solar_system_name"] == "Jita", "空名缓存应触发重新解析并补齐名称"
        # 缓存被重写为带名字
        with open(cache_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data["systems"][0]["solar_system_name"] == "Jita"

    def test_named_cache_uses_fast_path(self, tmp_path, monkeypatch):
        """星系名非空的缓存 → 走快速路径（不触发重新解析）"""
        cache_file = tmp_path / "universe_data.json"
        cache_file.write_text(
            json.dumps(
                {
                    "regions": [],
                    "constellations": [],
                    "systems": [{"solar_system_id": 30000142, "solar_system_name": "Jita"}],
                    "stargates": [],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr("tools.downloaders.sde_cache.UNIVERSE_CACHE_PATH", str(cache_file))
        # ensure_sde_cache 总是被调用（快速路径也确保 zip 就绪），但不应触发 ZIP 重解析
        monkeypatch.setattr("tools.downloaders.sde_cache.ensure_sde_cache", self._async_noop)
        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(b"placeholder")  # 快速路径不读取 zip 内容
        monkeypatch.setattr("tools.downloaders.sde_cache.SDE_ZIP_PATH", str(zip_path))

        def _fail(*args, **kwargs):
            raise AssertionError("星系名非空缓存不应触发重新解析")

        monkeypatch.setattr("tools.downloaders.sde_cache._build_name_map", _fail)

        _regions, _const, systems, _sg = asyncio.run(ensure_universe_cache())
        assert systems[0]["solar_system_name"] == "Jita"


class TestEnsureSdeZip:
    """ensure_sde_zip — 断点续传 + 完整性校验"""

    @staticmethod
    def _mock_http(session_cls, status, headers, chunks):
        """构造 aiohttp.ClientSession mock 链"""
        mock_resp = MagicMock()
        mock_resp.status = status
        mock_resp.headers = headers
        mock_resp.content = MagicMock()

        async def _chunks():
            for c in chunks:
                yield c

        mock_resp.content.iter_chunked.return_value = _chunks()
        mock_resp.raise_for_status = MagicMock()

        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_cm)
        session_cls.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        return mock_session

    @pytest.mark.asyncio
    @patch("tools.downloaders.sde_cache.os.path.exists")
    @patch("tools.downloaders.sde_cache.os.path.getsize")
    @patch("tools.downloaders.sde_cache.os.replace")
    @patch("zipfile.ZipFile")
    @patch("tools.downloaders.sde_cache.open", new_callable=mock_open)
    @patch("tools.downloaders.sde_cache.aiohttp.ClientSession")
    async def test_resume_with_range(
        self, mock_session_cls, mock_file, mock_zf, mock_replace, mock_getsize, mock_exists
    ):
        """SDE_ZIP_PATH 不存在但 .part 残留 → Range 续传 + 追加模式 + 原子 rename"""
        from tools.downloaders.sde_cache import SDE_ZIP_PATH, ZIP_PART_PATH

        # 首次 exists 判断 SDE_ZIP_PATH → False；ZIP_PART_PATH → True（断点）
        mock_exists.side_effect = [False, True]
        mock_getsize.return_value = 5000  # 已下载 5000 字节

        # zip 完整性校验通过
        mock_zf_instance = MagicMock()
        mock_zf_instance.testzip.return_value = None
        mock_zf.return_value.__enter__.return_value = mock_zf_instance

        mock_session = self._mock_http(mock_session_cls, 206, {"Content-Range": "bytes=5000-117964799/117964800"}, [b"x"])

        result = await ensure_sde_zip()

        assert result == SDE_ZIP_PATH
        # Range 头带断点偏移
        _args, kwargs = mock_session.get.call_args
        assert kwargs["headers"] == {"Range": "bytes=5000-"}
        # 追加模式写 .part
        assert mock_file.call_args[0] == (ZIP_PART_PATH, "ab")
        # 原子 rename 完成
        mock_replace.assert_called_once_with(ZIP_PART_PATH, SDE_ZIP_PATH)

    @pytest.mark.asyncio
    @patch("tools.downloaders.sde_cache.os.path.exists")
    @patch("tools.downloaders.sde_cache.os.remove")
    @patch("zipfile.ZipFile")
    @patch("tools.downloaders.sde_cache.open", new_callable=mock_open)
    @patch("tools.downloaders.sde_cache.aiohttp.ClientSession")
    async def test_zip_integrity_failure_deletes_part(
        self, mock_session_cls, mock_file, mock_zf, mock_remove, mock_exists
    ):
        """下载完成后 testzip 校验损坏 → 删 .part 并抛错（下次从头下载）"""
        from tools.downloaders.sde_cache import ZIP_PART_PATH

        # SDE_ZIP_PATH 与 ZIP_PART_PATH 都不存在 → 全量下载
        mock_exists.side_effect = [False, False]

        # zip 校验失败（testzip 返回损坏成员名）
        mock_zf_instance = MagicMock()
        mock_zf_instance.testzip.return_value = "some_bad_member"
        mock_zf.return_value.__enter__.return_value = mock_zf_instance

        self._mock_http(mock_session_cls, 200, {"Content-Length": "100"}, [b"x"])

        with pytest.raises(zipfile.BadZipFile):
            await ensure_sde_zip()
        # 损坏的 .part 被删除
        mock_remove.assert_called_once_with(ZIP_PART_PATH)


class TestLoadYamlAsync:
    """load_yaml_async — 进程内缓存 + to_thread 只解析一次"""

    @pytest.mark.asyncio
    async def test_parses_once_via_to_thread(self, tmp_path, monkeypatch):
        _make_loader(tmp_path, monkeypatch)
        clear_yaml_cache()

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("tools.downloaders.sde_cache.yaml.load", side_effect=counting_load):
            first = await load_yaml_async("test.yaml")
            second = await load_yaml_async("test.yaml")

        assert calls["n"] == 1, "二次调用应命中进程内缓存，不重复解析"
        assert first is second
        clear_yaml_cache()
