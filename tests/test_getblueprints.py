"""蓝图数据拉取单元测试 — services/workers/getblueprints.py"""

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from tools.downloaders.getblueprints import (
    CACHE_FILE,
    CREATE_TABLES_SQL,
    SDE_ZIP_PATH,
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
    @patch("tools.downloaders.sde_cache.ensure_sde_zip", new_callable=AsyncMock)
    async def test_downloads_and_extracts_when_missing(self, mock_ensure_zip, mock_file, mock_makedirs, mock_exists):
        # CACHE_FILE 与共享 SDE zip 都不存在 → 复用 ensure_sde_zip 下载
        mock_exists.side_effect = [False, False]

        mock_zf_instance = MagicMock()
        mock_zf_instance.namelist.return_value = ["sde/fsd/blueprints.yaml"]
        mock_zf_instance.read.return_value = b"blueprint: data"
        with patch("zipfile.ZipFile") as mock_zf:
            mock_zf.return_value.__enter__.return_value = mock_zf_instance
            result = await ensure_cache()

        assert result == CACHE_FILE
        mock_ensure_zip.assert_awaited_once()
        mock_zf.assert_called_once_with(SDE_ZIP_PATH, "r")

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
    @patch("tools.downloaders.sde_cache.ensure_sde_zip", new_callable=AsyncMock)
    async def test_raises_when_no_yaml_in_zip(self, mock_ensure_zip, mock_makedirs, mock_exists):
        mock_exists.return_value = False

        mock_zf_instance = MagicMock()
        mock_zf_instance.namelist.return_value = ["sde/fsd/other.yaml"]
        with patch("zipfile.ZipFile") as mock_zf:
            mock_zf.return_value.__enter__.return_value = mock_zf_instance
            with pytest.raises(FileNotFoundError, match="blueprints.yaml"):
                await ensure_cache()
        mock_ensure_zip.assert_awaited_once()


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
    @patch("tools.downloaders.getblueprints.yaml.load")
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
        # 蓝图名称补拉已移到 sde_data 步骤（需 item 表就绪），blueprints 主体不再触发
        mock_fill.assert_not_awaited()


class TestParseActivitiesInvention:
    """parse_activities — 发明活动（概率 < 1.0 + 技能要求）"""

    def test_invention_activity_preserves_probability_and_skills(self):
        """发明产物含概率字段，技能表正确填充"""
        bp_data = {
            "maxProductionLimit": 1,
            "activities": {
                "invention": {
                    "time": 14400,
                    "materials": [
                        {"typeID": 20418, "quantity": 1},
                        {"typeID": 20420, "quantity": 1},
                    ],
                    "products": [
                        {"typeID": 20416, "quantity": 1, "probability": 0.2},
                        {"typeID": 20417, "quantity": 1, "probability": 0.2},
                    ],
                    "skills": [
                        {"typeID": 3413, "level": 5},
                        {"typeID": 3411, "level": 4},
                    ],
                }
            },
        }
        a_rows, m_rows, p_rows, s_rows = parse_activities(20414, bp_data)

        assert len(a_rows) == 1
        assert a_rows[0] == (20414, "invention", 14400, 1)

        assert len(m_rows) == 2
        assert m_rows[0] == (20414, "invention", 20418, 1, 10)
        assert m_rows[1] == (20414, "invention", 20420, 1, 10)

        # 概率字段保留
        assert len(p_rows) == 2
        assert p_rows[0] == (20414, "invention", 20416, 1, 0.2)
        assert p_rows[1] == (20414, "invention", 20417, 1, 0.2)

        assert len(s_rows) == 2
        assert s_rows[0] == (20414, "invention", 3413, 5)
        assert s_rows[1] == (20414, "invention", 3411, 4)


class TestParseActivitiesCopying:
    """parse_activities — 复制活动（无材料/产物，仅有时间）"""

    def test_copying_activity_produces_only_activity_row(self):
        """复制活动只有 time 字段，materials/products/skills 均为空"""
        bp_data = {
            "maxProductionLimit": 30,
            "activities": {
                "copying": {
                    "time": 24000,
                    "materials": [],
                    "products": [],
                }
            },
        }
        a_rows, m_rows, p_rows, s_rows = parse_activities(3001, bp_data)

        assert len(a_rows) == 1
        assert a_rows[0] == (3001, "copying", 24000, 30)
        assert m_rows == []
        assert p_rows == []
        assert s_rows == []


class TestParseActivitiesMultiple:
    """parse_activities — 同时拥有制造 + 材料效率 + 时间效率研究"""

    def test_multiple_activities_all_parsed(self):
        """同一蓝图下多个活动各自产出独立行"""
        bp_data = {
            "maxProductionLimit": 10,
            "activities": {
                "manufacturing": {
                    "time": 7200,
                    "materials": [{"typeID": 34, "quantity": 100}],
                    "products": [{"typeID": 587, "quantity": 1}],
                },
                "research_material": {
                    "time": 36000,
                    "materials": [{"typeID": 34, "quantity": 10}],
                    "products": [],
                },
                "research_time": {
                    "time": 36000,
                    "materials": [{"typeID": 34, "quantity": 10}],
                    "products": [],
                },
            },
        }
        a_rows, m_rows, p_rows, s_rows = parse_activities(3001, bp_data)

        assert len(a_rows) == 3
        activities = {r[1] for r in a_rows}
        assert activities == {"manufacturing", "research_material", "research_time"}

        for r in a_rows:
            assert r[3] == 10

        assert len(m_rows) == 3
        assert len(p_rows) == 1
        assert p_rows[0][1] == "manufacturing"
        assert s_rows == []


class TestEnsureCacheHttpError:
    """ensure_cache — 下载阶段 HTTP 异常"""

    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.os.path.exists")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    @patch(
        "tools.downloaders.sde_cache.ensure_sde_zip",
        new_callable=AsyncMock,
        side_effect=Exception("HTTP 403 Forbidden"),
    )
    async def test_raises_on_http_error(self, mock_ensure_zip, mock_makedirs, mock_exists):
        """S3 下载失败时 ensure_sde_zip 抛异常，ensure_cache 原样传播"""
        mock_exists.return_value = False  # CACHE_FILE 与 SDE_ZIP_PATH 都不存在 → 走下载

        with pytest.raises(Exception, match="HTTP 403 Forbidden"):
            await ensure_cache()

        mock_ensure_zip.assert_awaited_once()


class TestRunBlueprintUpdateYamlError:
    """run_blueprint_update — YAML 异常时整体流程的行为"""

    @staticmethod
    def _make_db_mocks():
        """构造 4 个 db context manager mock，对应 4 次 aiosqlite.connect 调用。

        注意：
          - 连接 1（检查）:  await cursor.fetchone() → AsyncMock
          - 连接 2（建表）:  不使用 fetchone
          - 连接 3（写入）:  不使用 fetchone
          - 连接 4（统计）:  cursor.fetchone()[0] → 同步 MagicMock
        """
        configs = [
            {"fetchone_async": True, "count": 0},
            {"fetchone_async": False, "count": 0},
            {"fetchone_async": False, "count": 0},
            {"fetchone_async": False, "count": 1},
        ]
        mocks = []
        for cfg in configs:
            cursor = MagicMock()
            if cfg["fetchone_async"]:
                cursor.fetchone = AsyncMock(return_value=(cfg["count"],))
            else:
                cursor.fetchone = MagicMock(return_value=(cfg["count"],))

            db = MagicMock()
            db.execute = AsyncMock(return_value=cursor)
            db.executescript = AsyncMock()
            db.executemany = AsyncMock()
            db.commit = AsyncMock()

            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=db)
            cm.__aexit__ = AsyncMock(return_value=False)
            mocks.append(cm)
        return mocks

    @pytest.mark.asyncio
    @patch("tools.downloaders.getblueprints.aiosqlite.connect")
    @patch("tools.downloaders.getblueprints.os.makedirs")
    @patch("tools.downloaders.getblueprints.ensure_cache")
    @patch("tools.downloaders.getblueprints.yaml.load")
    @patch("tools.downloaders.getblueprints.open", new_callable=mock_open)
    async def test_raises_value_error_when_yaml_is_not_dict(
        self, mock_file, mock_yaml, mock_ensure_cache, mock_makedirs, mock_connect
    ):
        """yaml.load 返回非 dict 时抛出 ValueError，且异常消息包含实际类型名"""
        cms = self._make_db_mocks()
        mock_connect.side_effect = iter(cms)
        mock_ensure_cache.return_value = "/tmp/blueprints.yaml"
        mock_yaml.return_value = ["this", "is", "a", "list"]
        mock_file.return_value.__enter__.return_value.read.return_value = "bad"

        with pytest.raises(ValueError) as exc_info:
            await run_blueprint_update()

        assert "list" in str(exc_info.value)
        # 验证 yaml.load 确实被调用（而非提前跳过）
        mock_yaml.assert_called_once()
        # 验证读取的是缓存文件
        mock_file.assert_called_once_with("/tmp/blueprints.yaml", encoding="utf-8")
