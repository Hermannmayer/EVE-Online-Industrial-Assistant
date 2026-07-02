"""价格历史测试 — ESI 抓取 / DB 缓存

需要 mock ESI 请求（aiohttp），验证缓存写入和过期逻辑。
"""

import shutil
import sqlite3
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp
import pytest

from services.database_manager import DB_PATH_MAP, get_db
from services.price_history import CACHE_TTL_SECONDS, _ensure_table, fetch_history, get_cached_history, save_cache

MOCK_HISTORY_DATA = [
    {"date": "2026-06-01", "average": 5.0, "highest": 6.0, "lowest": 4.0, "volume": 100000, "order_count": 50},
    {"date": "2026-06-02", "average": 5.2, "highest": 6.2, "lowest": 4.2, "volume": 110000, "order_count": 55},
    {"date": "2026-06-03", "average": 5.1, "highest": 6.1, "lowest": 4.1, "volume": 105000, "order_count": 52},
]


@pytest.fixture
def temp_mkt_db():
    """创建临时 market.db，用于缓存测试"""
    tmpdir = tempfile.mkdtemp(prefix="eve_mkt_")
    mkt_path = Path(tmpdir) / "market.db"
    sqlite3.connect(str(mkt_path)).close()

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP["mkt"] = str(mkt_path)

    # 清空 get_db 缓存（线程局部）
    mgr = get_db()
    mgr.close_all()

    yield mkt_path

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    mgr.close_all()
    shutil.rmtree(tmpdir, ignore_errors=True)


# ── fetch_history （mock ESI） ──


@pytest.mark.asyncio
async def test_fetch_history_success():
    """mock ESI 返回 → 验证 JSON 数据正确解析"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.json.return_value = MOCK_HISTORY_DATA

    mock_session = AsyncMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_resp

    result = await fetch_history(type_id=1001, session=mock_session)
    assert result is not None
    assert len(result) == 3
    assert result[0]["date"] == "2026-06-01"
    assert result[0]["average"] == 5.0
    assert result[1]["volume"] == 110000


@pytest.mark.asyncio
async def test_fetch_history_404_returns_none():
    """ESI 404 → 返回 None"""
    mock_resp = AsyncMock()
    mock_resp.status = 404
    mock_resp.__aenter__.return_value = mock_resp

    mock_session = AsyncMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_resp

    result = await fetch_history(type_id=99999, session=mock_session)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_history_calls_correct_url():
    """验证请求 URL 包含正确的 type_id 和 region_id"""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.__aenter__.return_value = mock_resp
    mock_resp.json.return_value = []

    mock_session = AsyncMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value = mock_resp

    await fetch_history(type_id=1001, region_id=10000002, session=mock_session)

    mock_session.get.assert_called_once()
    args, kwargs = mock_session.get.call_args
    assert "markets/10000002/history/" in args[0]
    assert kwargs.get("params") == {"type_id": 1001}


# ── save_cache + get_cached_history ──


class TestCacheRoundtrip:
    """save_cache → get_cached_history 完整回路"""

    def test_save_and_read_back(self, temp_mkt_db):
        """保存缓存后应能读回相同数据"""
        _ensure_table()
        save_cache(1001, 10000002, MOCK_HISTORY_DATA)
        cached = get_cached_history(1001, 10000002)
        assert cached is not None
        assert len(cached) == 3
        assert cached[0]["date"] == "2026-06-01"
        assert cached[0]["average"] == 5.0

    def test_save_overwrites_old(self, temp_mkt_db):
        """重复保存同一 type_id 应覆盖旧数据"""
        _ensure_table()
        save_cache(1001, 10000002, MOCK_HISTORY_DATA[:1])
        save_cache(1001, 10000002, MOCK_HISTORY_DATA)
        cached = get_cached_history(1001, 10000002)
        assert cached is not None
        assert len(cached) == 3  # 被覆盖成完整 3 条

    def test_no_cache_returns_none(self, temp_mkt_db):
        """没有缓存时返回 None"""
        _ensure_table()
        result = get_cached_history(99999, 10000002)
        assert result is None

    def test_cached_read(self, temp_mkt_db):
        """已有缓存 → 直接返回不调 ESI"""
        _ensure_table()
        save_cache(1001, 10000002, MOCK_HISTORY_DATA)
        # 如果从缓存读取，不应触发 ESI 调用
        result = get_cached_history(1001, 10000002)
        assert result is not None
        assert len(result) == 3

    def test_expired_cache(self, temp_mkt_db):
        """缓存超过 TTL → 返回 None（由外层重新调 ESI）"""
        _ensure_table()

        # 直接写入过期缓存数据
        db = get_db()
        old_time = (datetime.now(UTC) - timedelta(seconds=CACHE_TTL_SECONDS + 3600)).isoformat()
        with db.connect("mkt") as conn:
            conn.execute(
                "INSERT INTO price_history "
                "  (type_id, region_id, date, average, highest, lowest, volume, order_count, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (1002, 10000002, "2026-06-01", 10.0, 11.0, 9.0, 5000, 25, old_time),
            )

        result = get_cached_history(1002, 10000002)
        assert result is None  # 超时视为无缓存

    def test_multiple_type_ids_independent(self, temp_mkt_db):
        """不同 type_id 的缓存互不影响"""
        _ensure_table()
        save_cache(1001, 10000002, MOCK_HISTORY_DATA)
        alt_data = [
            {
                "date": "2026-06-01",
                "average": 100.0,
                "highest": 110.0,
                "lowest": 90.0,
                "volume": 500,
                "order_count": 10,
            },
        ]
        save_cache(2001, 10000002, alt_data)
        c1 = get_cached_history(1001, 10000002)
        c2 = get_cached_history(2001, 10000002)
        assert len(c1) == 3
        assert len(c2) == 1
        assert c2[0]["average"] == 100.0
