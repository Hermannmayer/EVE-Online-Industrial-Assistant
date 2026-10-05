"""异动榜口径测试 — `services.market_movers_service.get_movers`。

数据全用 `conftest.temp_db`（临时 ref/mkt/bp 三库，已建好表）+ 相对 `date.today()` 的日期，
所以用例不会随时间腐烂。窗口：近 3 天 = [今天-2, 今天]，前窗口 = [今天-5, 今天-3]。
"""

from datetime import date, timedelta

import pytest

from services.market_movers_service import get_movers
from services.price_history import PRICE_HISTORY_DDL

REGION = 10000002


def _span(offsets: tuple[int, ...], average: float, volume: int) -> list[tuple[int, float, int]]:
    """(距今天数, 成交均价, 成交量) 三元组列表 —— 窗口内每一天一条记录。"""
    return [(offset, average, volume) for offset in offsets]


#: type_id → 行情记录；窗口 = 近 3 天 [0, 2]、前窗口 [3, 5]
_QUOTES = {
    # 前窗口 10×100、近窗口 12×300 → chg=+20%，近 3 天日均 300，放量倍数 7.5，覆盖 6 天
    2001: _span((0, 1, 2), 12.0, 300) + _span((3, 4, 5), 10.0, 100),
    # 只有 4 天记录 → 覆盖天数不足，不准入；涨幅 +100%
    2002: _span((0, 1), 20.0, 10) + _span((3, 4), 10.0, 10),
    # 成交量全 0 → 30 天成交额 0，不准入；均价退回算术平均，放量倍数给 None
    2003: _span((0, 1, 2), 20.0, 0) + _span((3, 4, 5), 10.0, 0),
    # 只有近窗口 → 算不出涨幅 → 不进榜
    2004: _span((0, 1, 2), 5.0, 50),
    # 大跌，用来验 |涨幅| 排序
    2005: _span((0, 1), 10.0, 10) + _span((3, 4), 100.0, 10),
    # MPI 矿物：被 4 张有效配方当材料，产物 1001 本身也是投入品 → PPPI
    34: _span((0, 1, 2), 4.0, 1000) + _span((3, 4, 5), 3.5, 1000),
    # 被 4 张有效配方当材料，产物 2001/2002 不再被当材料 → SPPI
    1001: _span((0, 1, 2), 12.0, 100) + _span((3, 4, 5), 10.0, 100),
    # PLEX
    44992: _span((0, 1), 5_000_000.0, 10) + _span((3, 4), 4_000_000.0, 10),
}


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


@pytest.fixture
def movers_db(temp_db):
    """价格历史 + 蓝图；材料口径与**指数篮子**一致：被 ≥4 张**有效配方**当材料才算投入品。

    - 34 被 4 张蓝图（9001/9003/9004/9005）当材料，产物 1001 在 `ref.item` 里有市场分类
      → 有效配方；且 1001 本身也是投入品 → 34 是 **PPPI**。
    - 1001 被 4 张蓝图（3001/3002/9006/9007）当材料 → **SPPI**（产物 2001/2002 不再是投入品）。
    - 2001 只被 3 张蓝图（9008/9009/9010）当材料 → **不够门槛，不算投入品**（回归用）。
    - 9002 制造 2005 ← 1001：2005 在 `ref.item` 里没有市场分类（占位配方）→ 该材料关系不算数。
    """
    with temp_db.connect("mkt", "ref", "bp") as conn:
        conn.execute(PRICE_HISTORY_DDL)
        for type_id, quotes in _QUOTES.items():
            for offset, average, volume in quotes:
                conn.execute(
                    "INSERT INTO price_history (type_id, region_id, date, average, highest, lowest, "
                    "volume, order_count, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                    (type_id, REGION, _day(offset), average, average, average, volume, "2026-01-01T00:00:00+00:00"),
                )
        conn.executemany(
            "INSERT INTO blueprint_products VALUES (?, 'manufacturing', ?, 1)",
            [
                (9001, 1001),
                (9003, 1001),
                (9004, 1001),
                (9005, 1001),  # 34 × 4 张有效配方
                (9006, 2002),
                (9007, 2002),  # 1001 × 4（另两张是 conftest 的 3001/3002）
                (9008, 2002),
                (9009, 2002),
                (9010, 2002),  # 2001 × 3（不够门槛）
                (9002, 2005),  # 占位配方：2005 没有市场分类
            ],
        )
        conn.executemany(
            "INSERT INTO blueprint_materials VALUES (?, 'manufacturing', ?, 10, 10)",
            [
                (9001, 34),
                (9003, 34),
                (9004, 34),
                (9005, 34),
                (9006, 1001),
                (9007, 1001),
                (9008, 2001),
                (9009, 2001),
                (9010, 2001),
                (9002, 1001),
            ],
        )
    return temp_db


def test_price_change_and_volume_windows(movers_db):
    """涨幅 = 近 3 天均价 vs 前 3 天均价；日均按**日历天**（缺记录的天按 0 成交）算。"""
    row = next(r for r in get_movers(days=3, limit=100, _db=movers_db) if r["typeId"] == 2001)
    assert row == {
        "typeId": 2001,
        "name": "渡鸦级",
        "price": pytest.approx(12.0),
        "chg": pytest.approx(20.0),
        "volume": pytest.approx(300.0),
        "volume_ratio": pytest.approx(7.5),
        "qualified": True,
        "index_keys": ["cpi"],
    }


def test_qualified_needs_turnover_and_coverage(movers_db):
    """准入 = 近 30 天成交额 > 0 且覆盖天数 ≥ 5；`qualified_only` 只留准入通过的。"""
    flags = {r["typeId"]: r["qualified"] for r in get_movers(days=3, limit=100, _db=movers_db)}
    assert (flags[2001], flags[2002], flags[2003]) == (True, False, False)
    assert [r["typeId"] for r in get_movers(days=3, limit=100, qualified_only=True, _db=movers_db)] == [
        1001,
        2001,
        34,
    ]


def test_missing_data_is_none_or_absent_never_zero(movers_db):
    """缺数据给 None / 不进榜：不用 0 冒充，也不拿 0 顶替「没记录」。"""
    by_id = {r["typeId"]: r for r in get_movers(days=3, limit=100, _db=movers_db)}
    assert by_id[2003]["volume_ratio"] is None  # 近 30 天成交量为 0
    assert by_id[2003]["volume"] == 0.0  # 这是真的「一笔没成交」，不是缺数据
    assert by_id[2003]["chg"] == pytest.approx(100.0)  # 成交量全 0 → 均价退回算术平均
    assert 2004 not in by_id  # 只有近窗口 → 算不出前窗口涨幅
    assert 9999 not in by_id  # 完全没有历史


def test_sorted_by_abs_change_then_limit(movers_db):
    """按 |涨幅| 降序（同值按 typeId），`limit` 截断。"""
    assert [r["typeId"] for r in get_movers(days=3, limit=100, _db=movers_db)] == [
        2002,
        2003,
        2005,
        44992,
        1001,
        2001,
        34,
    ]
    assert [r["typeId"] for r in get_movers(days=3, limit=1, _db=movers_db)] == [2002]


def test_index_keys_cover_all_five_lines(movers_db):
    """index_keys 命中 MPI / PPPI / SPPI / CPI / PLEX（口径与指数篮子同一处实现）。"""
    by_id = {r["typeId"]: r for r in get_movers(days=3, limit=100, _db=movers_db)}
    assert by_id[34]["index_keys"] == ["mpi", "pppi"]  # 矿物，且产物 1001 还是投入品
    assert by_id[1001]["index_keys"] == ["sppi"]  # 被 4 张有效配方当材料，产物 2001/2002 不是
    assert by_id[2001]["index_keys"] == ["cpi"]  # 有成交、不被当材料
    assert by_id[44992]["index_keys"] == ["cpi", "plex"]


def test_index_keys_follow_the_index_basket_recipe_cutoff(movers_db):
    """回归：口径与指数篮子对齐 —— 被 **< 4 张有效配方**当材料的成品不算投入品。

    2001 只被 9008/9009/9010 三张有效配方当材料（`< market_index_service.MIN_VALID_RECIPES`）：
    旧口径（「被任何一张制造/反应蓝图当材料」）会把它标成 `sppi`，而 SPPI 篮子里根本没有它 ——
    同一件东西在两个页面上自相矛盾。真投入品 1001（被 4 张有效配方用）仍该命中 `sppi`。
    """
    by_id = {r["typeId"]: r for r in get_movers(days=3, limit=100, _db=movers_db)}
    assert by_id[2001]["index_keys"] == ["cpi"]  # 3 张有效配方 < 4 → 只是消费品
    assert by_id[1001]["index_keys"] == ["sppi"]  # 4 张有效配方 → 真投入品


def test_no_price_history_table_returns_empty(db_manager):
    """从没拉过历史的库（表都不存在）→ 空榜，不抛异常。"""
    assert get_movers(days=3, _db=db_manager) == []
