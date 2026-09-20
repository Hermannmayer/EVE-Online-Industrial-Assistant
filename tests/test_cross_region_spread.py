"""跨区域价差排行的数据层契约（`services/market_browser_service` 的两个新查询）。

数据边界是 bug 源，所以这里只用**真实临时库**跑真实 SQL，不 mock：
单侧缺价、体积为 0、分类子树、快照天数不足，四条都是会静默出错的路径。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services import market_browser_service as mbs

JITA = 10000002
AMARR = 10000043


@pytest.fixture
def svc(temp_db, monkeypatch):
    """把服务模块的 `get_container` 指向临时库管理器。"""
    stub = type("C", (), {"db": temp_db})()
    monkeypatch.setattr(mbs, "get_container", lambda: stub)
    return temp_db


def _add_region_prices(db, rows: list[tuple]) -> None:
    with db.connect("mkt") as conn:
        conn.executemany(
            "INSERT INTO market_prices (type_id, region_id, buy_price, sell_price, "
            "adjusted_price, buy_volume, sell_volume, fetch_time) VALUES (?,?,?,?,0,0,0,?)",
            rows,
        )


# ── 跨区域 JOIN ─────────────────────────────────────────────


def test_only_items_priced_in_both_regions_are_candidates(svc):
    """单侧缺价的物品不进排行 —— 只有 Jita 有价的 2001 不该出现。"""
    _add_region_prices(svc, [(1001, AMARR, 9.0, 12.0, "2026-01-01 00:00:00")])

    rows = mbs.fetch_cross_region_spread(JITA, AMARR)

    assert [r["id"] for r in rows] == [1001]


def test_zero_and_null_prices_are_filtered_out(svc):
    """价格列为 0/NULL 的行要被 `COALESCE(...) > 0` 滤掉，而不是当成「免费」。"""
    _add_region_prices(
        svc,
        [
            (1001, AMARR, 9.0, 12.0, "2026-01-01 00:00:00"),
            (1002, AMARR, None, 0.0, "2026-01-01 00:00:00"),
        ],
    )

    ids = [r["id"] for r in mbs.fetch_cross_region_spread(JITA, AMARR)]

    assert ids == [1001]


def test_spread_is_b_minus_a_and_price_side_is_selectable(svc):
    """默认「A 卖单买入、B 买单卖出」；换成 A 买单则取另一个价。"""
    _add_region_prices(svc, [(1001, AMARR, 9.0, 12.0, "2026-01-01 00:00:00")])

    sell_then_buy = mbs.fetch_cross_region_spread(JITA, AMARR, side_a="sell", side_b="buy")[0]
    assert sell_then_buy["pa"] == 5.0  # Jita 卖价
    assert sell_then_buy["pb"] == 9.0  # Amarr 买价
    assert sell_then_buy["spread"] == 4.0

    buy_then_buy = mbs.fetch_cross_region_spread(JITA, AMARR, side_a="buy", side_b="buy")[0]
    assert buy_then_buy["pa"] == 4.0
    assert buy_then_buy["spread"] == 5.0


def test_profit_per_m3_is_none_when_volume_is_zero(svc):
    """体积 0 的物品**不做除零**：`pm3` 为 None，交给界面显示占位。"""
    with svc.connect("ref", "mkt") as conn:
        conn.execute(
            "INSERT INTO item (type_id, zh_name, en_name, volume, market_group_id) "
            "VALUES (3001, '体积为零的玩意', 'Zero Volume', 0, 19)"
        )
    _add_region_prices(
        svc,
        [
            (3001, JITA, 5.0, 5.0, "x"),
            (1001, AMARR, 9.0, 12.0, "x"),
            (3001, AMARR, 9.0, 12.0, "x"),
        ],
    )

    by_id = {r["id"]: r for r in mbs.fetch_cross_region_spread(JITA, AMARR)}

    assert by_id[1001]["pm3"] is not None
    assert by_id[3001]["pm3"] is None
    assert by_id[3001]["spread"] == 4.0  # 价差照算，只是每方利润无值


def test_empty_group_ids_means_all_categories(svc):
    _add_region_prices(svc, [(1001, AMARR, 9.0, 12.0, "x")])
    assert mbs.fetch_cross_region_spread(JITA, AMARR, group_ids=[]) == mbs.fetch_cross_region_spread(JITA, AMARR)


def test_category_filter_includes_child_groups(svc):
    """按顶层分类筛要连**子树**一起收：2001 挂在 100（护卫舰）下、100 挂在 4（舰船）下。"""
    _add_region_prices(
        svc,
        [
            (1001, AMARR, 9.0, 12.0, "x"),  # 19 贸易货物
            (2001, AMARR, 60000000.0, 70000000.0, "x"),  # 100 → 4 舰船
        ],
    )

    assert [r["id"] for r in mbs.fetch_cross_region_spread(JITA, AMARR, group_ids=[4])] == [2001]
    assert sorted(r["id"] for r in mbs.fetch_cross_region_spread(JITA, AMARR, group_ids=[19])) == [1001]


# ── 挂单变化 ────────────────────────────────────────────────


def _snap(db, type_id: int, day: str, sell_volume: int, region_id: int = AMARR) -> None:
    with db.connect("mkt") as conn:
        conn.execute(
            "INSERT INTO market_volume_snapshots (type_id, region_id, date, sell_volume) VALUES (?,?,?,?)",
            (type_id, region_id, day, sell_volume),
        )


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).strftime("%Y-%m-%d")


def test_single_snapshot_has_no_change_value(svc):
    """只有一天快照 → 算不出变化，不能拿它当「0/天」。"""
    _snap(svc, 1001, _days_ago(1), 5000)

    assert mbs.fetch_hub_order_change(AMARR)[1001]["per_day"] is None


def test_missing_item_is_absent_from_the_map(svc):
    assert mbs.fetch_hub_order_change(AMARR) == {}


def test_falling_order_book_is_a_positive_change(svc):
    """挂单在减少（有人在吃单）→ 正数；堆积 → 负数。"""
    _snap(svc, 1001, _days_ago(4), 1000)
    _snap(svc, 1001, _days_ago(1), 400)
    _snap(svc, 1002, _days_ago(4), 100)
    _snap(svc, 1002, _days_ago(1), 400)

    change = mbs.fetch_hub_order_change(AMARR)

    assert change[1001]["per_day"] == pytest.approx(200.0)  # (1000-400)/3
    assert change[1001]["days"] == 2
    assert change[1002]["per_day"] == pytest.approx(-100.0)
    # sort 侧要能直接拿来比较：正值排前面（更值得买）
    assert change[1001]["per_day"] > change[1002]["per_day"]


def test_snapshots_outside_the_window_are_ignored(svc):
    _snap(svc, 1001, _days_ago(30), 1000)
    _snap(svc, 1001, _days_ago(29), 400)

    assert mbs.fetch_hub_order_change(AMARR, days=7) == {}


def test_only_the_b_side_region_is_read(svc):
    """挂单变化只算目的中心 —— 起点中心那侧的快照不该被读进来。"""
    _snap(svc, 1001, _days_ago(4), 1000, region_id=JITA)
    _snap(svc, 1001, _days_ago(1), 400, region_id=JITA)
    _snap(svc, 1001, _days_ago(4), 9000, region_id=AMARR)
    _snap(svc, 1001, _days_ago(1), 1000, region_id=AMARR)

    change = mbs.fetch_hub_order_change(AMARR)

    assert change[1001]["per_day"] == pytest.approx(8000 / 3)  # 用的是 Amarr 的数


# ── 纯计算 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("first", "last", "days", "expected"),
    [
        (1000, 400, 3, 200.0),
        (400, 1000, 3, -200.0),
        (500, 500, 3, 0.0),
        (1000, 400, 0, None),  # 同一天两份快照：间隔为 0，算不出日均
    ],
)
def test_order_change_per_day_formula(first, last, days, expected):
    end = date(2026, 9, 20)
    start = end - timedelta(days=days)
    got = mbs.order_change_per_day(first, last, start.isoformat(), end.isoformat(), 2)

    assert got == (pytest.approx(expected) if expected is not None else None)


@pytest.mark.parametrize(("first", "last", "snapshots"), [(None, 400, 2), (1000, None, 2), (1000, 400, 1)])
def test_order_change_per_day_returns_none_on_insufficient_data(first, last, snapshots):
    assert mbs.order_change_per_day(first, last, "2026-09-17", "2026-09-20", snapshots) is None


# ── 价格时效 ────────────────────────────────────────────────


def test_fetch_hub_fetch_time_reports_each_region(svc):
    assert mbs.fetch_hub_fetch_time([JITA, AMARR]) == {JITA: "2026-01-01 00:00:00"}
    assert mbs.fetch_hub_fetch_time([]) == {}


# ── 对手盘挂单量 ────────────────────────────────────────────


def test_rows_carry_the_counterparty_volume_of_the_chosen_side(svc):
    """`va`/`vb` 必须是**所选价位那一侧**的挂单量：取卖单价就看卖单量。"""
    _add_region_prices(svc, [(1001, AMARR, 9.0, 12.0, "x")])
    with svc.connect("mkt") as conn:
        conn.execute("UPDATE market_prices SET buy_volume=111, sell_volume=222")

    both_sell = mbs.fetch_cross_region_spread(JITA, AMARR, side_a="sell", side_b="sell")[0]
    assert (both_sell["va"], both_sell["vb"]) == (222, 222)

    buy_then_sell = mbs.fetch_cross_region_spread(JITA, AMARR, side_a="buy", side_b="sell")[0]
    assert (buy_then_sell["va"], buy_then_sell["vb"]) == (111, 222)


def test_zero_counterparty_volume_is_reported_not_dropped(svc):
    """对手盘为 0 的行**照样返回**（价格是真的）—— 由界面上的筛选项决定要不要看。"""
    _add_region_prices(svc, [(1001, AMARR, 9.0, 12.0, "x")])

    row = mbs.fetch_cross_region_spread(JITA, AMARR, side_a="sell", side_b="buy")[0]

    assert row["vb"] == 0
    assert row["pb"] == 9.0
