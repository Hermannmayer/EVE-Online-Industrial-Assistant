"""`services.price_refresh_service` 测试（05-7）：TTL 判定 + 价格落库分支；用 tmp_path 临时 market.db。"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from services import price_refresh_service as prs

_REGION = 10000002


def _make_db(tmp_path, monkeypatch) -> str:
    path = tmp_path / "market.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE market_prices (type_id INTEGER, region_id INTEGER, buy_price REAL, sell_price REAL, "
        "adjusted_price REAL DEFAULT 0, buy_volume INTEGER, sell_volume INTEGER, fetch_time TEXT)"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(prs, "MKT_DB", str(path))  # 模块级常量是 import 时求值
    return str(path)


def _write(path: str, rows: list[tuple]) -> None:
    conn = sqlite3.connect(path)
    conn.executemany("INSERT INTO market_prices VALUES (?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _read(path: str) -> dict[int, tuple]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT type_id, buy_price, sell_price, adjusted_price, buy_volume, sell_volume, fetch_time "
            "FROM market_prices"
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: r for r in rows}


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


@pytest.mark.asyncio
async def test_check_stale_judges_missing_fresh_expired_and_malformed(tmp_path, monkeypatch):
    path = _make_db(tmp_path, monkeypatch)
    now = datetime.now(UTC)
    _write(
        path,
        [
            (1, _REGION, 1.0, 2.0, 0.0, 1, 1, _fmt(now)),  # fresh
            (2, _REGION, 1.0, 2.0, 0.0, 1, 1, _fmt(now - timedelta(seconds=prs.CACHE_TTL_SECONDS + 60))),  # expired
            (3, 10000043, 1.0, 2.0, 0.0, 1, 1, _fmt(now)),  # 其他区域 → 本区域无行
            (4, _REGION, 1.0, 2.0, 0.0, 1, 1, "not-a-date"),  # 坏时间
        ],
    )
    assert await prs.check_stale_type_ids(set()) == set()
    assert await prs.check_stale_type_ids({1, 2, 3, 4, 5}) == {2, 3, 4, 5}


@pytest.mark.asyncio
async def test_save_inserts_missing_and_updates_existing_keeping_adjusted(tmp_path, monkeypatch):
    path = _make_db(tmp_path, monkeypatch)
    _write(path, [(7, _REGION, 1.0, 2.0, 3.5, 1, 1, "2026-01-01 00:00:00")])
    written = await prs.save_refreshed_prices(
        {
            6: {"buy_price": 1.0, "sell_price": 2.0, "buy_volume": 3, "sell_volume": 4},  # 无行 → INSERT
            7: {"buy_price": 10.0, "sell_price": 20.0, "buy_volume": 5, "sell_volume": 6},  # 有行 → UPDATE
        }
    )
    assert written == 2
    rows = _read(path)
    assert rows[6][1:3] == (1.0, 2.0) and rows[6][3] == 0.0 and rows[6][4:6] == (3, 4) and rows[6][6]
    assert rows[7][1:3] == (10.0, 20.0) and rows[7][4:6] == (5, 6)
    assert rows[7][3] == 3.5, "adjusted_price 不在刷新范围，必须保留原值"
    assert rows[7][6] != "2026-01-01 00:00:00"
