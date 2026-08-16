"""工业系统成本指数拉取单元测试 — services/workers/getindustry.py"""

from unittest.mock import AsyncMock, patch

import pytest

from services.workers.getindustry import (
    KEY_MANUFACTURING_SKILLS,
    create_tables,
    industry_data_is_fresh,
    run_industry_update,
)


class TestCreateTables:
    @pytest.mark.asyncio
    async def test_creates_tables_in_both_databases(self):
        mock_ref_db = AsyncMock()
        mock_usr_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(0,))
        mock_usr_db.execute = AsyncMock(return_value=mock_cursor)

        call_count = [0]

        def connect_side_effect(path, *a, **kw):
            call_count[0] += 1
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=mock_ref_db if call_count[0] == 1 else mock_usr_db)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with patch("services.workers.getindustry.aiosqlite.connect", side_effect=connect_side_effect):
            await create_tables()

        ref_sql = mock_ref_db.executescript.call_args[0][0]
        assert "industry_system_costs" in ref_sql
        usr_sql = mock_usr_db.executescript.call_args[0][0]
        assert "user_skills" in usr_sql

    @pytest.mark.asyncio
    async def test_skips_default_skills_when_data_exists(self):
        mock_usr_db = AsyncMock()
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(10,))
        mock_usr_db.execute = AsyncMock(return_value=mock_cursor)

        def connect_side_effect(path, *a, **kw):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock() if "reference" in str(path) else mock_usr_db)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with patch("services.workers.getindustry.aiosqlite.connect", side_effect=connect_side_effect):
            await create_tables()

        for call_args in mock_usr_db.execute.call_args_list:
            assert "INSERT INTO user_skills" not in call_args[0][0]


class TestRunIndustryUpdate:
    @pytest.mark.asyncio
    @patch("services.workers.getindustry.create_tables")
    @patch("services.workers.getindustry.APIClient")
    async def test_fetches_system_cost_indices(self, mock_api_client, mock_create_tables):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_api_client.return_value = mock_client

        systems_data = [
            {
                "solar_system_id": 30000142,
                "cost_indices": [
                    {"activity": "manufacturing", "cost_index": 0.053},
                    {"activity": "researching_time_efficiency", "cost_index": 0.021},
                ],
            },
            {
                "solar_system_id": 30000144,
                "cost_indices": [{"activity": "manufacturing", "cost_index": 0.047}],
            },
        ]
        facilities_data = []

        mock_client.fetch_required = AsyncMock()
        mock_client.fetch_required.side_effect = [systems_data, facilities_data]

        mock_db = AsyncMock()

        def connect_side_effect(path, *a, **kw):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=mock_db)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with patch("os.makedirs"):
            with patch("services.workers.getindustry.aiosqlite.connect", side_effect=connect_side_effect):
                await run_industry_update()

        insert_calls = [
            c for c in mock_db.executemany.call_args_list if "INSERT OR REPLACE INTO industry_system_costs" in c[0][0]
        ]
        assert len(insert_calls) >= 1, "系统成本指数应通过 executemany 批量写入"
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    @patch("services.workers.getindustry.create_tables")
    @patch("services.workers.getindustry.APIClient")
    async def test_fetches_facilities(self, mock_api_client, mock_create_tables):
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = False
        mock_api_client.return_value = mock_client

        systems_data = []
        facilities_data = [
            {
                "facility_id": 60015000,
                "solar_system_id": 30000142,
                "type_id": 2500,
                "owner_id": 1000001,
                "region_id": 10000002,
                "tax": 0.05,
            },
            {
                "facility_id": 60016000,
                "solar_system_id": 30000144,
                "type_id": 2501,
                "owner_id": None,
                "region_id": None,
                "tax": 0.0,
            },
        ]

        mock_client.fetch_required = AsyncMock()
        mock_client.fetch_required.side_effect = [systems_data, facilities_data]

        mock_db = AsyncMock()

        def connect_side_effect(path, *a, **kw):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=mock_db)
            cm.__aexit__ = AsyncMock(return_value=False)
            return cm

        with patch("os.makedirs"):
            with patch("services.workers.getindustry.aiosqlite.connect", side_effect=connect_side_effect):
                await run_industry_update()

        fac_calls = [
            c for c in mock_db.executemany.call_args_list if "INSERT OR REPLACE INTO industry_facilities" in c[0][0]
        ]
        assert len(fac_calls) >= 1, "工业设施应通过 executemany 批量写入"

    @pytest.mark.asyncio
    async def test_key_skills_constant(self):
        skill_ids = [s[0] for s in KEY_MANUFACTURING_SKILLS]
        assert 3380 in skill_ids
        assert 3388 in skill_ids
        assert 24268 in skill_ids
        assert 3387 in skill_ids
        assert 3402 in skill_ids
        assert len(skill_ids) == 11


class TestIndustryDataFresh:
    """industry_data_is_fresh — 工业数据新鲜度判定（临时 SQLite）"""

    @staticmethod
    def _make_db(tmp_path, fetch_time, *, create_table=True) -> str:
        import sqlite3

        db_path = str(tmp_path / "ref.db")
        conn = sqlite3.connect(db_path)
        try:
            if create_table:
                conn.execute(
                    "CREATE TABLE industry_system_costs ("
                    "solar_system_id INTEGER, activity TEXT, cost_index REAL, fetch_time TIMESTAMP, "
                    "PRIMARY KEY (solar_system_id, activity))"
                )
                if fetch_time is not None:
                    conn.execute(
                        "INSERT INTO industry_system_costs VALUES (1, 'manufacturing', 0.03, ?)",
                        (fetch_time,),
                    )
            conn.commit()
        finally:
            conn.close()
        return db_path

    def test_missing_db_is_not_fresh(self, tmp_path):
        assert industry_data_is_fresh(str(tmp_path / "none.db")) is False

    def test_no_table_is_not_fresh(self, tmp_path):
        db = self._make_db(tmp_path, None, create_table=False)
        assert industry_data_is_fresh(db) is False

    def test_empty_table_is_not_fresh(self, tmp_path):
        db = self._make_db(tmp_path, None)
        assert industry_data_is_fresh(db) is False

    def test_recent_fetch_is_fresh(self, tmp_path):
        from datetime import UTC, datetime

        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        db = self._make_db(tmp_path, now)
        assert industry_data_is_fresh(db, max_age_days=1) is True

    def test_stale_fetch_is_not_fresh(self, tmp_path):
        from datetime import UTC, datetime, timedelta

        old = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        db = self._make_db(tmp_path, old)
        assert industry_data_is_fresh(db, max_age_days=1) is False
