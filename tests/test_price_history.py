"""价格历史测试 — ESI 抓取 / DB 缓存

需要 mock ESI 请求（aiohttp），验证缓存写入和过期逻辑。
"""

import shutil
import sqlite3
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import aiohttp
import pytest

from services.database_manager import DB_PATH_MAP, get_db
from services.price_history import (
    CACHE_TTL_SECONDS,
    _ensure_table,
    fetch_history,
    get_cached_history,
    get_history_summary,
    save_cache,
)

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


# ── get_history_summary：日订单量 / 日成交量的窗口口径 ──


class TestHistorySummary:
    """窗口是**日历天**，不是「最近 N 条记录」。

    回归（用户 2026-10-05 报）：`屹立白蚁 II`（47128）在游戏里两个多月没成交，
    窗口却显示 20+/天 —— 因为按「最近 7 条」取，那 7 条横跨 2026-05-14 ~ 07-17。
    """

    @staticmethod
    def _insert(rows: list[tuple[int, str, int, int]], fetched_at: str = "2026-10-05T00:00:00") -> None:
        _ensure_table()
        with get_db().connect("mkt") as conn:
            for tid, day, vol, oc in rows:
                conn.execute(
                    "INSERT INTO price_history "
                    "  (type_id, region_id, date, average, highest, lowest, volume, order_count, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (tid, 10000002, day, 1.0, 1.0, 1.0, vol, oc, fetched_at),
                )

    #: `屹立白蚁 II`（47128）真实的形状：最近 7 条横跨 5 个月，最新一条在 80 天前
    _STALE_TAIL = [
        (47128, "2026-07-17", 2, 1),
        (47128, "2026-07-11", 1, 1),
        (47128, "2026-06-20", 86, 6),
        (47128, "2026-06-05", 1, 1),
        (47128, "2026-05-27", 1, 1),
        (47128, "2026-05-25", 54, 14),
        (47128, "2026-05-14", 6, 1),
    ]

    def test_recently_pulled_history_says_zero_not_the_old_tail(self, temp_mkt_db):
        """今天拉过：窗口内没记录 = **真的没成交** → 0（回归：原来报 21.6/天）。"""
        self._insert(self._STALE_TAIL, fetched_at="2026-10-05T08:00:00")
        got = get_history_summary([47128], today=date(2026, 10, 5))[47128]

        assert got["stale"] is False
        assert got["vol"] == 0.0, "近 7 天没有成交就是 0，不能拿 5 个月前的 7 条算"
        assert got["oc"] == 0.0
        assert got["days"] == 0
        assert got["last"] == "2026-07-17", "要能说出「最后有记录是哪天」"

    def test_data_never_refreshed_reports_unknown(self, temp_mkt_db):
        """本地这份历史也是几个月前拉的 → `—`（不知道），不拿 0 冒充「没人买」。"""
        self._insert(self._STALE_TAIL, fetched_at="2026-07-18T00:00:00")
        got = get_history_summary([47128], today=date(2026, 10, 5))[47128]

        assert got["stale"] is True
        assert got["vol"] is None
        assert got["oc"] is None

    def test_active_item_divides_by_the_whole_window(self, temp_mkt_db):
        """窗口内没有记录的日子按 0 计入：分母恒为 7 天，而不是「有几条算几条」。"""
        self._insert(
            [
                (33681, "2026-10-03", 70, 30),
                (33681, "2026-10-01", 7, 3),
                (33681, "2026-09-29", 21, 9),
                (33681, "2026-09-20", 999, 99),  # 窗口外，不参与
            ]
        )
        got = get_history_summary([33681], today=date(2026, 10, 5))[33681]

        assert got["stale"] is False
        assert got["days"] == 3
        assert got["vol"] == pytest.approx((70 + 7 + 21) / 7)
        assert got["oc"] == pytest.approx((30 + 3 + 9) / 7)
        assert got["last"] == "2026-10-03"

    def test_no_history_at_all_is_absent_from_the_result(self, temp_mkt_db):
        """从来没拉过历史的 type 不出现在结果里（调用方 `.get` → `None` → 表格 `—`）。"""
        _ensure_table()
        assert get_history_summary([99999], today=date(2026, 10, 5)) == {}
        assert get_history_summary([], today=date(2026, 10, 5)) == {}
