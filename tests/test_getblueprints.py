"""蓝图数据拉取单元测试 — services/workers/getblueprints.py"""

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from tools.downloaders.getblueprints import (
    CACHE_FILE,
    CREATE_TABLES_SQL,
    SDE_ZIP_PATH,
    SDE_ZIP_URL,
    ensure_cache,
    parse_activities,
    run_blueprint_update,
)


class TestCreateTables:
    def test_creates_all_tables(self):
        """建表 SQL 含全部 4 张蓝图表（同步断言，不依赖 pytest-asyncio await 计数）。

        create_tables 的 executescript/commit 调用行为由
        TestRunBlueprintUpdate.test_full_update_flow 间接覆盖（run_blueprint_update 内部调用）。
        """
        for tbl in ("blueprint_activities", "blueprint_materials", "blueprint_products", "blueprint_skills"):
            assert f"CREATE TABLE IF NOT EXISTS {tbl}" in CREATE_TABLES_SQL


class TestEnsureCache:
    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.os.path.exists")
    @patch("tools.downloaders.getblueprints.os.path.getsize")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    async def test_returns_cached_path_when_exists(self, mock_makedirs, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 1 * 1024 * 1024
        result = await ensure_cache()
        assert result == CACHE_FILE

    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.os.path.exists")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    @patch("tools.downloaders.getblueprints.open", new_callable=mock_open)
    @patch("tools.downloaders.getblueprints.os.path.getsize")
    async def test_downloads_and_extracts_when_missing(self, mock_getsize, mock_file, mock_makedirs, mock_exists):
        # CACHE_FILE 与共享 SDE zip 都不存在 → 走下载路径
        mock_exists.side_effect = [False, False]
        mock_getsize.return_value = 2 * 1024 * 1024

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.read = AsyncMock(return_value=b"fake_zip_content")
        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_cm)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.downloaders.getblueprints.aiohttp.ClientSession", return_value=mock_session):
            with patch("zipfile.ZipFile") as mock_zf:
                mock_zf_instance = MagicMock()
                mock_zf_instance.namelist.return_value = ["sde/fsd/blueprints.yaml"]
                mock_zf_instance.read.return_value = b"blueprint: data"
                mock_zf.return_value.__enter__.return_value = mock_zf_instance
                result = await ensure_cache()

        assert result == CACHE_FILE
        assert mock_session.get.call_args[0][0] == SDE_ZIP_URL

    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.os.path.exists")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    @patch("tools.downloaders.getblueprints.open", new_callable=mock_open)
    async def test_reuses_shared_sde_zip_when_present(self, mock_file, mock_makedirs, mock_exists):
        # CACHE_FILE 缺失但共享 data/sde.zip 已存在 → 复用，不重复下载
        mock_exists.side_effect = [False, True]  # CACHE_FILE 不存在, SDE_ZIP_PATH 存在

        mock_zf_instance = MagicMock()
        mock_zf_instance.namelist.return_value = ["sde/fsd/blueprints.yaml"]
        mock_zf_instance.read.return_value = b"blueprint: data"

        with patch("zipfile.ZipFile") as mock_zf:
            mock_zf.return_value.__enter__.return_value = mock_zf_instance
            result = await ensure_cache()

        assert result == CACHE_FILE
        # 未触发任何下载请求
        mock_zf.return_value.__enter__.assert_called_once()
        mock_zf.assert_called_once_with(SDE_ZIP_PATH, "r")

    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.os.path.exists")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    async def test_raises_when_no_yaml_in_zip(self, mock_makedirs, mock_exists):
        mock_exists.return_value = False

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.read = AsyncMock(return_value=b"fake_zip")
        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_cm)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("tools.downloaders.getblueprints.aiohttp.ClientSession", return_value=mock_session):
            with patch("zipfile.ZipFile") as mock_zf:
                mock_zf_instance = MagicMock()
                mock_zf_instance.namelist.return_value = ["sde/fsd/other.yaml"]
                mock_zf.return_value.__enter__.return_value = mock_zf_instance
                with pytest.raises(FileNotFoundError, match="blueprints.yaml"):
                    await ensure_cache()


class TestParseActivities:
    def test_parse_manufacturing_blueprint(self):
        bp_data = {
            "maxProductionLimit": 10,
            "activities": {
                "manufacturing": {
                    "time": 3600,
                    "materials": [{"typeID": 34, "quantity": 100}],
                    "products": [{"typeID": 587, "quantity": 1, "probability": 1.0}],
                    "skills": [{"typeID": 3380, "level": 1}],
                }
            },
        }
        a_rows, m_rows, p_rows, s_rows = parse_activities(3001, bp_data)
        assert a_rows[0] == (3001, "manufacturing", 3600, 10)
        assert m_rows[0] == (3001, "manufacturing", 34, 100, 10)
        assert p_rows[0] == (3001, "manufacturing", 587, 1, 1.0)
        assert s_rows[0] == (3001, "manufacturing", 3380, 1)

    def test_parse_reaction_blueprint(self):
        bp_data = {
            "maxProductionLimit": 1,
            "activities": {
                "reaction": {
                    "time": 7200,
                    "materials": [{"typeID": 100, "quantity": 10}],
                    "products": [{"typeID": 200, "quantity": 5, "probability": 0.8}],
                }
            },
        }
        *_, p_rows, s_rows = parse_activities(4001, bp_data)
        assert p_rows[0][3] == 5
        assert p_rows[0][4] == 0.8
        assert len(s_rows) == 0

    def test_empty_activities(self):
        a_rows, m_rows, p_rows, s_rows = parse_activities(5000, {"maxProductionLimit": 1})
        assert a_rows == []


class TestRunBlueprintUpdate:
    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.aiosqlite.connect")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    async def test_skips_when_data_exists(self, mock_makedirs, mock_connect):
        mock_cursor = MagicMock()
        mock_cursor.fetchone = AsyncMock(return_value=(2000,))
        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_cursor)
        # Use AsyncMock for context manager — __aenter__ auto-returns a coroutine
        mock_connect.return_value = AsyncMock()
        mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_db)
        mock_connect.return_value.__aexit__ = AsyncMock(return_value=False)
        await run_blueprint_update()
        mock_makedirs.assert_called_once()

    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.aiosqlite.connect")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    @patch("tools.downloaders.getblueprints.ensure_cache")
    @patch("tools.downloaders.getblueprints.yaml.safe_load")
    @patch("tools.downloaders.getblueprints.open", new_callable=mock_open)
    async def test_full_update_flow(self, mock_file, mock_yaml, mock_ensure_cache, mock_makedirs, mock_connect):
        # Connection 1: Check count
        mock_cursor_check = MagicMock()
        mock_cursor_check.fetchone = AsyncMock(return_value=(0,))
        mock_db_check = MagicMock()
        mock_db_check.execute = AsyncMock(return_value=mock_cursor_check)

        # Connection 2: create_tables + Connection 3: write batch
        mock_db_write = MagicMock()
        mock_db_write.executescript = AsyncMock()
        mock_db_write.executemany = AsyncMock()
        mock_db_write.commit = AsyncMock()
        mock_cursor_write = MagicMock()
        mock_db_write.execute = AsyncMock(return_value=mock_cursor_write)

        # Connection 4: Stats (fetchone NOT awaited here)
        mock_cursor_stat = MagicMock()
        mock_cursor_stat.fetchone = AsyncMock(return_value=(1,))
        mock_db_stat = MagicMock()
        mock_db_stat.execute = AsyncMock(return_value=mock_cursor_stat)

        mock_cm_check = AsyncMock()
        mock_cm_check.__aenter__ = AsyncMock(return_value=mock_db_check)
        mock_cm_check.__aexit__ = AsyncMock(return_value=False)

        mock_cm_write = AsyncMock()
        mock_cm_write.__aenter__ = AsyncMock(return_value=mock_db_write)
        mock_cm_write.__aexit__ = AsyncMock(return_value=False)

        mock_cm_stat = AsyncMock()
        mock_cm_stat.__aenter__ = AsyncMock(return_value=mock_db_stat)
        mock_cm_stat.__aexit__ = AsyncMock(return_value=False)

        call_count = [0]

        def connect_side_effect(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_cm_check
            elif call_count[0] <= 3:
                return mock_cm_write
            return mock_cm_stat

        mock_connect.side_effect = connect_side_effect
        mock_ensure_cache.return_value = "/tmp/blueprints.yaml"
        mock_yaml.return_value = {
            "3001": {
                "maxProductionLimit": 10,
                "activities": {
                    "manufacturing": {
                        "time": 3600,
                        "materials": [{"typeID": 34, "quantity": 100}],
                        "products": [{"typeID": 587, "quantity": 1}],
                    }
                },
            }
        }
        mock_file.return_value.__enter__.return_value.read.return_value = "fake_yaml"

        with patch("tools.downloaders.getitems.fill_missing_blueprint_names", AsyncMock()) as mock_fill:
            await run_blueprint_update()

        assert mock_db_check.execute.called
        assert mock_db_write.executemany.call_count >= 1
        mock_fill.assert_awaited_once()
