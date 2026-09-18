"""SDE 缓存工具测试 — services/importers/sde_cache.py

覆盖:
  - load_yaml 进程内缓存（避免初始化反复解析 typeIDs.yaml 大文件）
  - clear_yaml_cache 释放缓存
  - universe YAML 解析（新格式：名称走 name_map、stargates 内嵌 destination）
"""

import asyncio
import io
import json
import os
import time
import zipfile
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
import yaml

from services.importers.sde_cache import (
    _universe_cache_has_names,
    clear_yaml_cache,
    ensure_sde_zip,
    ensure_universe_cache,
    load_yaml,
    load_yaml_async,
)

pytestmark = pytest.mark.fast


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


def _make_large_universe_zip(n_systems=210):
    """构造含 n 个 solarsystem 的 SDE zip（≥200 个才触发进程池分支判定）。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(n_systems):
            sid = 30000000 + i
            zf.writestr(
                f"universe/eve/10000001/1000000001/{sid}/solarsystem.yaml",
                f"solarSystemID: {sid}\nsecurity: 0.5\nconstellationID: 1000000001\nregionID: 10000001\n",
            )
        zf.writestr("bsd/invNames.yaml", "- itemID: 30000142\n  itemName: Jita\n")
    buf.seek(0)
    return buf


def _make_loader(tmp_path, monkeypatch, filename="test.yaml", content="key: value"):
    """写临时 YAML 文件并把 cache_path 指向临时目录"""
    (tmp_path / filename).write_text(content, encoding="utf-8")
    monkeypatch.setattr("services.importers.sde_cache.cache_path", lambda name: str(tmp_path / name))


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

        with patch("services.importers.sde_cache.yaml.load", side_effect=counting_load):
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

        with patch("services.importers.sde_cache.yaml.load", side_effect=counting_load):
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
        monkeypatch.setattr("services.importers.sde_cache.cache_path", lambda name: str(tmp_path / name))
        assert load_yaml("nonexistent.yaml") == {}
        clear_yaml_cache()


class TestLoadYamlPickleCache:
    """磁盘 pickle 缓存 — 大 YAML 解析一次后从 pkl 秒级加载"""

    def test_big_yaml_writes_and_reuses_pkl(self, tmp_path, monkeypatch):
        """首次解析写 pkl；清进程缓存后从 pkl 读（不再 yaml.load）"""
        _make_loader(tmp_path, monkeypatch)
        monkeypatch.setattr("services.importers.sde_cache._PICKLE_SIZE_THRESHOLD", 0)
        clear_yaml_cache()

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("services.importers.sde_cache.yaml.load", side_effect=counting_load):
            first = load_yaml("test.yaml")
            assert (tmp_path / "test.pkl").exists(), "首次解析应生成 pkl 缓存"

            clear_yaml_cache()  # 模拟下次启动（清进程内缓存，pkl 保留）
            second = load_yaml("test.yaml")

        assert calls["n"] == 1, "命中 pkl 缓存不应再次 yaml.load"
        assert first == second
        clear_yaml_cache()

    def test_modified_yaml_forces_reparse(self, tmp_path, monkeypatch):
        """yaml mtime 更新 → pkl 失效，重新解析"""
        _make_loader(tmp_path, monkeypatch)
        monkeypatch.setattr("services.importers.sde_cache._PICKLE_SIZE_THRESHOLD", 0)
        clear_yaml_cache()

        load_yaml("test.yaml")  # 生成 pkl
        clear_yaml_cache()

        # touch yaml 使其比 pkl 新 → 应重新解析
        future = time.time() + 10
        os.utime(tmp_path / "test.yaml", (future, future))

        calls = {"n": 0}
        real_load = yaml.load

        def counting_load(stream, Loader=None):
            calls["n"] += 1
            return real_load(stream, Loader=Loader)

        with patch("services.importers.sde_cache.yaml.load", side_effect=counting_load):
            load_yaml("test.yaml")
        assert calls["n"] == 1, "yaml mtime 更新后应重新解析"
        clear_yaml_cache()


class TestUniverseParsing:
    """universe YAML 解析 — 新格式（名称走 name_map / stargates 内嵌）"""

    def test_parse_universe_chunk_new_format(self, tmp_path):
        """新格式：region/constellation/system 名称从 name_map 解析，stargates 键为 destination"""
        from services.importers.sde_cache import _parse_universe_chunk

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
        from services.importers.sde_cache import _parse_universe_chunk

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
        from services.importers.sde_cache import _build_name_map

        zip_path = tmp_path / "mini_sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())

        name_map = _build_name_map(str(zip_path))
        assert name_map[10000001] == "The Forge"
        assert name_map[1000000001] == "Perimeter"
        assert name_map[30000142] == "Jita"

    def test_parse_region_name_fallback_when_no_name_map(self, tmp_path):
        """无 name_map 时 region_name 兜底为空串而非报错"""
        from services.importers.sde_cache import _parse_universe_chunk

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
        monkeypatch.setattr("services.importers.sde_cache.UNIVERSE_CACHE_PATH", str(cache_file))

        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(zip_path))
        monkeypatch.setattr("services.importers.sde_cache.ensure_sde_cache", self._async_noop)

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
        monkeypatch.setattr("services.importers.sde_cache.UNIVERSE_CACHE_PATH", str(cache_file))
        # ensure_sde_cache 总是被调用（快速路径也确保 zip 就绪），但不应触发 ZIP 重解析
        monkeypatch.setattr("services.importers.sde_cache.ensure_sde_cache", self._async_noop)
        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(b"placeholder")  # 快速路径不读取 zip 内容
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(zip_path))

        def _fail(*args, **kwargs):
            raise AssertionError("星系名非空缓存不应触发重新解析")

        monkeypatch.setattr("services.importers.sde_cache._build_name_map", _fail)

        _regions, _const, systems, _sg = asyncio.run(ensure_universe_cache())
        assert systems[0]["solar_system_name"] == "Jita"

    def test_universe_only_parses_systems(self, tmp_path, monkeypatch):
        """只解析星系文件：返回的 regions/constellations/stargates 恒为空

        mini zip 含 region.yaml/constellation.yaml/solarsystem.yaml（含内嵌 stargates），
        但 ensure_universe_cache 只应解析并返回 solarsystem。
        """
        cache_file = tmp_path / "universe_data.json"  # 不存在 → 触发解析
        monkeypatch.setattr("services.importers.sde_cache.UNIVERSE_CACHE_PATH", str(cache_file))
        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(_make_mini_universe_zip().getvalue())
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(zip_path))
        monkeypatch.setattr("services.importers.sde_cache.ensure_sde_cache", self._async_noop)

        regions, constellations, systems, stargates = asyncio.run(ensure_universe_cache())

        assert regions == []
        assert constellations == []
        assert stargates == []
        assert len(systems) == 1
        assert systems[0]["solar_system_id"] == 30000142
        assert systems[0]["solar_system_name"] == "Jita"

    def test_frozen_mode_uses_thread_pool_not_process_pool(self, tmp_path, monkeypatch):
        """冻结（PyInstaller）环境一律走线程池，绝不实例化 ProcessPoolExecutor

        冻结 exe 里 spawn 子进程会重入主模块，无 freeze_support 时挂起且不抛异常，
        回退兜底救不了 → 必须在构建进程池前就拦截（is_frozen 分支）。
        用 ≥200 个星系的 zip 让 <200 的线程池分支不生效，唯一能走线程池的
        开关就是 is_frozen（若被绕过，会撞上 patched ProcessPoolExecutor 抛错）。
        """
        from unittest.mock import patch as _patch

        cache_file = tmp_path / "universe_data.json"  # 不存在 → 触发解析
        monkeypatch.setattr("services.importers.sde_cache.UNIVERSE_CACHE_PATH", str(cache_file))
        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(_make_large_universe_zip().getvalue())
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(zip_path))
        monkeypatch.setattr("services.importers.sde_cache.ensure_sde_cache", self._async_noop)
        monkeypatch.setattr("services.importers.sde_cache.is_frozen", lambda: True)

        with _patch(
            "concurrent.futures.ProcessPoolExecutor",
            MagicMock(side_effect=AssertionError("冻结模式下不应创建进程池")),
        ) as pool_cls:
            _regions, _const, systems, _sg = asyncio.run(ensure_universe_cache())

        pool_cls.assert_not_called()
        assert len(systems) >= 200, "冻结模式应通过线程池正常解析大量星系"


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
    @patch("services.importers.sde_cache.os.path.exists")
    @patch("services.importers.sde_cache.os.path.getsize")
    @patch("services.importers.sde_cache.os.replace")
    @patch("zipfile.ZipFile")
    @patch("services.importers.sde_cache.open", new_callable=mock_open)
    @patch("services.importers.sde_cache.aiohttp.ClientSession")
    async def test_resume_with_range(
        self, mock_session_cls, mock_file, mock_zf, mock_replace, mock_getsize, mock_exists
    ):
        """SDE_ZIP_PATH 不存在但 .part 残留 → Range 续传 + 追加模式 + 原子 rename"""
        from services.importers.sde_cache import SDE_ZIP_PATH, ZIP_PART_PATH

        # 首次 exists 判断 SDE_ZIP_PATH → False；ZIP_PART_PATH → True（断点）
        mock_exists.side_effect = [False, True]
        mock_getsize.return_value = 5000  # 已下载 5000 字节

        # zip 完整性校验通过
        mock_zf_instance = MagicMock()
        mock_zf_instance.testzip.return_value = None
        mock_zf.return_value.__enter__.return_value = mock_zf_instance

        mock_session = self._mock_http(
            mock_session_cls, 206, {"Content-Range": "bytes=5000-117964799/117964800"}, [b"x"]
        )

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
    @patch("services.importers.sde_cache.os.path.exists")
    @patch("services.importers.sde_cache.os.remove")
    @patch("zipfile.ZipFile")
    @patch("services.importers.sde_cache.open", new_callable=mock_open)
    @patch("services.importers.sde_cache.aiohttp.ClientSession")
    async def test_zip_integrity_failure_deletes_part(
        self, mock_session_cls, mock_file, mock_zf, mock_remove, mock_exists
    ):
        """下载完成后 testzip 校验损坏 → 删 .part 并抛错（下次从头下载）"""
        from services.importers.sde_cache import ZIP_PART_PATH

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

        with patch("services.importers.sde_cache.yaml.load", side_effect=counting_load):
            first = await load_yaml_async("test.yaml")
            second = await load_yaml_async("test.yaml")

        assert calls["n"] == 1, "二次调用应命中进程内缓存，不重复解析"
        assert first is second
        clear_yaml_cache()


class TestSdeCacheManifest:
    """完成标记：只有全部 YAML 原子落盘后才算缓存完整（P1-1 回归）"""

    def _stage(self, tmp_path, monkeypatch, manifest: bool):
        """把 cache_path / MANIFEST_PATH / SDE_ZIP_PATH 指到临时目录，并造出全部 YAML"""
        from services.importers.sde_cache import YAML_FILES

        monkeypatch.setattr("services.importers.sde_cache.cache_path", lambda name: str(tmp_path / name))
        monkeypatch.setattr("services.importers.sde_cache.MANIFEST_PATH", str(tmp_path / "manifest.json"))
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(tmp_path / "sde.zip"))
        for fname in YAML_FILES:
            (tmp_path / fname).write_text("key: value", encoding="utf-8")
        if manifest:
            from services.importers.sde_cache import _write_manifest

            _write_manifest()
        return YAML_FILES

    def test_all_cached_requires_manifest(self, tmp_path, monkeypatch):
        """文件全在但没有完成标记 → 不算完整（旧实现会误判为完整缓存）"""
        from services.importers.sde_cache import _all_cached

        self._stage(tmp_path, monkeypatch, manifest=False)
        assert _all_cached() is False

    def test_all_cached_true_after_manifest(self, tmp_path, monkeypatch):
        from services.importers.sde_cache import _all_cached

        self._stage(tmp_path, monkeypatch, manifest=True)
        assert _all_cached() is True

    @pytest.mark.parametrize("damage", ["empty", "removed", "file_set_changed"])
    def test_all_cached_rejects_incomplete_cache(self, tmp_path, monkeypatch, damage):
        """空文件 / 缺文件 / 标记里的集合与当前 YAML_FILES 不一致 → 一律判为不完整"""
        from services.importers.sde_cache import _all_cached

        fnames = self._stage(tmp_path, monkeypatch, manifest=True)
        if damage == "empty":
            (tmp_path / sorted(fnames)[0]).write_text("", encoding="utf-8")
        elif damage == "removed":
            (tmp_path / sorted(fnames)[0]).unlink()
        else:
            (tmp_path / "manifest.json").write_text(
                json.dumps({"version": 1, "files": ["only-this.yaml"]}), encoding="utf-8"
            )
        assert _all_cached() is False

    def test_write_yaml_atomic_replaces_via_part(self, tmp_path, monkeypatch):
        """写 .part 后原子替换：替换前目标文件内容不变"""
        from services.importers import sde_cache

        monkeypatch.setattr(sde_cache, "cache_path", lambda name: str(tmp_path / name))
        dest = tmp_path / "x.yaml"
        dest.write_text("old", encoding="utf-8")
        with patch.object(sde_cache.os, "replace") as mock_replace:
            sde_cache._write_yaml_atomic("x.yaml", "new")
        mock_replace.assert_called_once_with(str(tmp_path / "x.yaml.part"), str(dest))
        assert (tmp_path / "x.yaml.part").read_text(encoding="utf-8") == "new"
        assert dest.read_text(encoding="utf-8") == "old"

    def test_write_yaml_atomic_cleans_part_on_failure(self, tmp_path, monkeypatch):
        """替换失败 → 清掉 .part 并上抛，目标文件保持旧内容"""
        from services.importers import sde_cache

        monkeypatch.setattr(sde_cache, "cache_path", lambda name: str(tmp_path / name))
        dest = tmp_path / "x.yaml"
        dest.write_text("old", encoding="utf-8")
        with patch.object(sde_cache.os, "replace", side_effect=OSError("locked")):
            with pytest.raises(OSError):
                sde_cache._write_yaml_atomic("x.yaml", "new")
        assert not (tmp_path / "x.yaml.part").exists()
        assert dest.read_text(encoding="utf-8") == "old"

    def _mini_zip(self, tmp_path, skip: str | None = None):
        """构造含全部 YAML_FILES 成员的 mini zip（成员名走 ZIP_LOOKUP 映射）"""
        from services.importers.sde_cache import YAML_FILES, ZIP_LOOKUP

        zip_path = tmp_path / "sde.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for fname in YAML_FILES:
                if fname == skip:
                    continue
                zf.writestr(f"fsd/{ZIP_LOOKUP.get(fname, fname)}", "key: value")
        return zip_path

    def test_backfill_manifest_when_sizes_match(self, tmp_path, monkeypatch):
        """升级兼容：老缓存无标记但大小与 zip 中央目录一致 → 补写标记，不重新提取"""
        from services.importers.sde_cache import _all_cached, _backfill_manifest_from_zip

        self._stage(tmp_path, monkeypatch, manifest=False)
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(self._mini_zip(tmp_path)))
        assert _backfill_manifest_from_zip() is True
        assert _all_cached() is True

    def test_backfill_manifest_rejects_size_mismatch(self, tmp_path, monkeypatch):
        """任一文件大小对不上 zip → 不补写标记（交回正常提取路径）"""
        from services.importers.sde_cache import _all_cached, _backfill_manifest_from_zip

        fnames = self._stage(tmp_path, monkeypatch, manifest=False)
        monkeypatch.setattr("services.importers.sde_cache.SDE_ZIP_PATH", str(self._mini_zip(tmp_path)))
        (tmp_path / sorted(fnames)[0]).write_text("key: value-too-long", encoding="utf-8")
        assert _backfill_manifest_from_zip() is False
        assert _all_cached() is False

    def test_extract_reuses_existing_zip(self, tmp_path, monkeypatch):
        """本地已有可用 sde.zip → 不重新下载（112MB），直接重新提取

        实测场景：升级后老缓存无完成标记、走到重新提取时，若 zip 已在本地，
        再下载一遍 112MB 纯属浪费（`_download_zip` 只看 .part，从不看已存在的 zip）。
        """
        from services.importers import sde_cache

        monkeypatch.setattr(sde_cache, "cache_path", lambda name: str(tmp_path / name))
        monkeypatch.setattr(sde_cache, "MANIFEST_PATH", str(tmp_path / "manifest.json"))
        monkeypatch.setattr(sde_cache, "SDE_ZIP_PATH", str(self._mini_zip(tmp_path)))
        monkeypatch.setattr(sde_cache, "_download_zip", AsyncMock(side_effect=AssertionError("不应重新下载")))

        asyncio.run(sde_cache._download_and_extract())

        assert sde_cache._all_cached() is True

    def test_corrupt_zip_is_discarded(self, tmp_path, monkeypatch):
        """本地 sde.zip 损坏 → 删除它，让下载路径从头来（不能拿坏包去解）"""
        from services.importers import sde_cache

        zip_path = tmp_path / "sde.zip"
        zip_path.write_bytes(b"not a zip at all")
        monkeypatch.setattr(sde_cache, "SDE_ZIP_PATH", str(zip_path))

        assert sde_cache._zip_is_usable() is False
        assert not zip_path.exists()

    def test_extract_missing_member_writes_no_manifest(self, tmp_path, monkeypatch):
        """zip 缺成员 → 不写完成标记，下次启动重新提取"""
        from services.importers import sde_cache
        from services.importers.sde_cache import YAML_FILES

        monkeypatch.setattr(sde_cache, "cache_path", lambda name: str(tmp_path / name))
        monkeypatch.setattr(sde_cache, "MANIFEST_PATH", str(tmp_path / "manifest.json"))
        monkeypatch.setattr(sde_cache, "SDE_ZIP_PATH", str(self._mini_zip(tmp_path, skip="agents.yaml")))
        monkeypatch.setattr(sde_cache, "_download_zip", AsyncMock())

        asyncio.run(sde_cache._download_and_extract())

        assert not (tmp_path / "manifest.json").exists()
        assert sde_cache._all_cached() is False
        assert not (tmp_path / "agents.yaml").exists()
        assert len([f for f in YAML_FILES if (tmp_path / f).exists()]) == len(YAML_FILES) - 1


class TestDownloadZipRetry:
    """SDE 裸下载的限流重试（P1-2 回归）"""

    @staticmethod
    def _response(status, headers, chunks):
        resp = MagicMock()
        resp.status = status
        resp.headers = headers

        async def _it():
            for c in chunks:
                yield c

        resp.content.iter_chunked.return_value = _it()
        resp.raise_for_status = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=resp)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    def _patch_env(self, tmp_path, monkeypatch, session_cls, responses):
        from services.importers import sde_cache

        part = tmp_path / "sde.zip.part"
        part.write_bytes(b"x" * 5000)  # 已下载 5000 字节的断点
        monkeypatch.setattr(sde_cache, "ZIP_PART_PATH", str(part))
        monkeypatch.setattr(sde_cache, "SDE_ZIP_PATH", str(tmp_path / "sde.zip"))
        monkeypatch.setattr(sde_cache.asyncio, "sleep", AsyncMock())
        session = MagicMock()
        session.get = MagicMock(side_effect=[self._response(*r) for r in responses])
        session_cls.return_value.__aenter__ = AsyncMock(return_value=session)
        session_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        return sde_cache, part, session

    @pytest.mark.asyncio
    @patch("zipfile.ZipFile")
    @patch("services.importers.sde_cache.aiohttp.ClientSession")
    async def test_429_waits_then_resumes(self, session_cls, mock_zf, tmp_path, monkeypatch):
        """首次 429（带 Retry-After）→ 等待后按原 Range 续传成功"""
        mock_zf.return_value.__enter__.return_value.testzip.return_value = None
        sde_cache, _part, session = self._patch_env(
            tmp_path,
            monkeypatch,
            session_cls,
            [
                (429, {"Retry-After": "1"}, []),
                (206, {"Content-Range": "bytes=5000-117964799/117964800"}, [b"x"]),
            ],
        )
        with patch.object(sde_cache.os, "replace"):
            result = await sde_cache._download_zip()

        assert result == str(tmp_path / "sde.zip")
        sde_cache.asyncio.sleep.assert_awaited_once_with(1.0)
        assert session.get.call_count == 2
        for call in session.get.call_args_list:
            assert call.kwargs["headers"] == {"Range": "bytes=5000-"}, "续传位置不应回退"

    @pytest.mark.asyncio
    @patch("services.importers.sde_cache.aiohttp.ClientSession")
    async def test_429_exhausted_raises_and_keeps_part(self, session_cls, tmp_path, monkeypatch):
        """连续 429 到上限 → 抛错且保留 .part（下次可续传）"""
        sde_cache, part, _session = self._patch_env(
            tmp_path, monkeypatch, session_cls, [(429, {"Retry-After": "0"}, [])] * 99
        )
        with pytest.raises(RuntimeError, match="限流"):
            await sde_cache._download_zip()
        assert sde_cache.asyncio.sleep.await_count == sde_cache._DL_MAX_RETRIES
        assert part.exists(), "限流不应删除断点文件"
