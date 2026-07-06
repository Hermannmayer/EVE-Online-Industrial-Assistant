"""蓝图数据拉取逻辑测试 — services/workers/getblueprints.py

覆盖现有 test_getblueprints.py 未触及的场景：
  - parse_activities: 发明、复制、多活动
  - ensure_cache: HTTP 下载失败
  - run_blueprint_update: YAML 格式异常

全部使用 AsyncMock 避免真实 ESI / S3 请求。
"""

from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from tools.downloaders.getblueprints import (
    SDE_ZIP_URL,
    ensure_cache,
    parse_activities,
    run_blueprint_update,
)


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
        assert m_rows[0] == (20414, "invention", 20418, 1)
        assert m_rows[1] == (20414, "invention", 20420, 1)

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
    @patch("services.workers.getblueprints.os.path.exists")
    @patch("services.workers.getblueprints.os.makedirs")
    async def test_raises_on_http_error(self, mock_makedirs, mock_exists):
        """S3 返回非 200 时 raise_for_status 抛出异常"""
        mock_exists.return_value = False

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("HTTP 403 Forbidden"))
        mock_resp.read = AsyncMock()
        mock_get_cm = MagicMock()
        mock_get_cm.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_get_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_get_cm)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "services.workers.getblueprints.aiohttp.ClientSession",
            return_value=mock_session,
        ):
            with pytest.raises(Exception, match="HTTP 403 Forbidden"):
                await ensure_cache()

        # 验证请求 URL（不比较 timeout 对象，它是真实 aiohttp.ClientTimeout）
        mock_session.get.assert_called_once()
        args, _ = mock_session.get.call_args
        assert args[0] == SDE_ZIP_URL


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
    @patch("services.workers.getblueprints.aiosqlite.connect")
    @patch("services.workers.getblueprints.os.makedirs")
    @patch("services.workers.getblueprints.ensure_cache")
    @patch("services.workers.getblueprints.yaml.safe_load")
    @patch("services.workers.getblueprints.open", new_callable=mock_open)
    async def test_raises_value_error_when_yaml_is_not_dict(
        self, mock_file, mock_yaml, mock_ensure_cache, mock_makedirs, mock_connect
    ):
        """yaml.safe_load 返回非 dict 时抛出 ValueError，且异常消息包含实际类型名"""
        cms = self._make_db_mocks()
        mock_connect.side_effect = iter(cms)
        mock_ensure_cache.return_value = "/tmp/blueprints.yaml"
        mock_yaml.return_value = ["this", "is", "a", "list"]
        mock_file.return_value.__enter__.return_value.read.return_value = "bad"

        with pytest.raises(ValueError) as exc_info:
            await run_blueprint_update()

        assert "list" in str(exc_info.value)
        # 验证 yaml.safe_load 确实被调用（而非提前跳过）
        mock_yaml.assert_called_once()
        # 验证读取的是缓存文件
        mock_file.assert_called_once_with("/tmp/blueprints.yaml", encoding="utf-8")
