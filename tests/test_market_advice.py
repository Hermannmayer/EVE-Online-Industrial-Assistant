"""交易建议口径测试 — `services.market_advice_service.get_trade_advice`。

库全用 `conftest.db_manager`（临时 ref/mkt 空库，**不碰真实库**）：这里自己建
`market_prices` / `market_volume_snapshots` / `item` 三张表，`price_history` 走
`services.price_history.PRICE_HISTORY_DDL`（建表语句的单一来源）。
日期一律相对 `date.today()`，用例不会随时间腐烂。
"""

from datetime import date, timedelta

import pytest

from core.eve_formulas import BROKER_FEE_BASE, SALES_TAX_BASE
from services.market_advice_service import CALIBER, NO_DATA_ADVICE, get_trade_advice
from services.price_history import PRICE_HISTORY_DDL

REGION = 10000002
#: 默认费率（经纪人 1% × 两侧 + 销售税 2%）下的来回费用
DEFAULT_FEE = 2 * BROKER_FEE_BASE + SALES_TAX_BASE

_MKT_DDL = """
CREATE TABLE market_prices (
    type_id INTEGER, region_id INTEGER, buy_price REAL, sell_price REAL,
    adjusted_price REAL DEFAULT 0.0, buy_volume INTEGER DEFAULT 0, sell_volume INTEGER DEFAULT 0,
    fetch_time TEXT
);
CREATE TABLE market_volume_snapshots (
    type_id INTEGER NOT NULL, region_id INTEGER NOT NULL, date TEXT NOT NULL,
    buy_price REAL DEFAULT 0, sell_price REAL DEFAULT 0,
    buy_volume BIGINT DEFAULT 0, sell_volume BIGINT DEFAULT 0,
    PRIMARY KEY (type_id, region_id, date)
);
CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT);
"""


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


@pytest.fixture
def advice_db(db_manager):
    """空库 + 三张表（`price_history` 用生产的 `PRICE_HISTORY_DDL`）。"""
    with db_manager.connect("mkt", "ref") as conn:
        conn.executescript(_MKT_DDL)
        conn.execute(PRICE_HISTORY_DDL)
    return db_manager


def _seed(
    db,
    type_id: int,
    *,
    buy: float | None = 10.0,
    sell: float | None = 10.2,
    volumes: list[int] | None = None,
    snapshot: float | None = None,
    name: str = "",
) -> None:
    """一行挂单价 + 近 7 天成交量（`volumes[i]` 是「今天 - i」那天）+ 最新一天快照。

    `buy`/`sell` 传 `None` = 不写挂单行；`volumes` 传 `None` = 一条成交记录都不写；
    `snapshot` 传 `None` = 不写快照。
    """
    with db.connect("mkt", "ref") as conn:
        conn.execute("INSERT INTO item (type_id, zh_name) VALUES (?, ?)", (type_id, name or f"物品{type_id}"))
        if buy is not None or sell is not None:
            conn.execute(
                "INSERT INTO market_prices (type_id, region_id, buy_price, sell_price, fetch_time) "
                "VALUES (?, ?, ?, ?, ?)",
                (type_id, REGION, buy, sell, "2026-01-01 00:00:00"),
            )
        for offset, volume in enumerate(volumes or []):
            conn.execute(
                "INSERT INTO price_history (type_id, region_id, date, average, highest, lowest, volume, "
                "order_count, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (type_id, REGION, _day(offset), 10.0, 10.0, 10.0, volume, "2026-01-01T00:00:00+00:00"),
            )
        if snapshot is not None:
            conn.execute(
                "INSERT INTO market_volume_snapshots (type_id, region_id, date, sell_volume) VALUES (?, ?, ?, ?)",
                (type_id, REGION, _day(0), snapshot),
            )


def test_two_sided_math_and_advice_text(advice_db):
    """双向挂单：spread / roundTripFeePct / turnDays 三个数一起对，建议给两侧报价。"""
    _seed(advice_db, 1, buy=10.0, sell=12.0, volumes=[300] * 7, snapshot=2100, name="渡鸦级")
    out = get_trade_advice(1, _db=advice_db)
    assert (out["typeId"], out["name"]) == (1, "渡鸦级")
    # 百分比字段保留 4 位小数，所以容差给到 1e-3
    assert out["spreadPct"] == pytest.approx((12.0 - 10.0) / 12.0 * 100.0, abs=1e-3)
    assert out["roundTripFeePct"] == pytest.approx(DEFAULT_FEE)
    assert out["dayVolume"] == pytest.approx(300.0)  # 7 天合计 2100 ÷ 7
    assert out["orderVolume"] == pytest.approx(2100.0)
    assert out["turnDays"] == pytest.approx(7.0)  # 2100 ÷ 300
    assert out["caliber"] == CALIBER
    assert out["verdict"] == "two_sided"
    assert out["buyAdvice"] == "挂买单：买价 × 1.01 = 10.10 ISK（贴着现有最高买价往上 1 个点，别直接吃卖单）"
    assert out["sellAdvice"] == "挂卖单：卖价 × 0.99 = 11.88 ISK（压过现有最低卖价）"


@pytest.mark.parametrize(
    ("buy", "sell", "volumes", "kwargs", "expected"),
    [
        pytest.param(None, None, [300] * 7, {}, "no_data", id="no_data_missing_row"),
        pytest.param(0.0, 0.0, [300] * 7, {}, "no_data", id="no_data_zero_price"),
        pytest.param(10.0, 0.0, [300] * 7, {}, "no_data", id="no_data_buy_only"),
        pytest.param(10.0, 12.0, [2] * 7, {}, "avoid_thin", id="avoid_thin_low_volume"),
        pytest.param(10.0, 12.0, None, {}, "avoid_thin", id="avoid_thin_no_history"),
        pytest.param(10.0, 10.2, [300] * 7, {}, "take_orders", id="take_orders_narrow"),
        pytest.param(10.0, 12.0, [300] * 7, {}, "two_sided", id="two_sided"),
    ],
)
def test_verdict_matrix(advice_db, buy, sell, volumes, kwargs, expected):
    """四个 verdict 各至少一条；任何 verdict 的依据都在 3~5 条之间。"""
    _seed(advice_db, 1, buy=buy, sell=sell, volumes=volumes)
    out = get_trade_advice(1, _db=advice_db, **kwargs)
    assert out["verdict"] == expected
    assert 3 <= len(out["reasons"]) <= 5
    assert out["buyAdvice"] and out["sellAdvice"]


def test_spread_collision_falls_back_to_take_orders(advice_db):
    """边界：买价 × 1.01 ≥ 卖价 × 0.99 → 不算 two_sided，退回 take_orders。

    只有**低费率**下这条边界才可达：默认 4% 来回费用要求价差 > 8%，而 1 个点的两侧报价
    偏移最多只留约 2% 的价差 —— 所以这里显式传 0.25% / 0% 的费率。
    """
    _seed(advice_db, 1, buy=10.0, sell=10.15, volumes=[300] * 7)
    out = get_trade_advice(1, _db=advice_db, broker_pct=0.25, sales_tax_pct=0.0)
    assert out["roundTripFeePct"] == pytest.approx(0.5)  # 费率只走参数，不是硬编码常数
    assert out["spreadPct"] == pytest.approx((10.15 - 10.0) / 10.15 * 100.0, abs=1e-3)
    assert out["spreadPct"] > out["roundTripFeePct"] * 2  # 本来够得上 two_sided 的门槛
    assert out["verdict"] == "take_orders"
    assert "价差太窄，改用吃单" in out["buyAdvice"]
    assert "价差太窄，改用吃单" in out["sellAdvice"]
    assert any("≥ 卖价 × 0.99" in reason for reason in out["reasons"])


@pytest.mark.parametrize(
    ("volumes", "snapshot", "expected_day", "expected_turn"),
    [
        pytest.param([2] * 7, 100, 2.0, 50.0, id="queue_50_days"),
        pytest.param([300] * 7, 2100, 300.0, 7.0, id="queue_7_days"),
        pytest.param([0] * 7, 50, 0.0, None, id="zero_volume_turn_none"),
        pytest.param([300] * 7, None, 300.0, None, id="no_snapshot_order_none"),
    ],
)
def test_turn_days_and_queue_reason(advice_db, volumes, snapshot, expected_day, expected_turn):
    """turnDays = 挂单量 ÷ 日均；日均 0 或没快照 → None（不除零、不用 0 冒充）。

    队列 > 14 天量时追加一条「排队」依据，否则一句都不加。
    """
    _seed(advice_db, 1, buy=10.0, sell=12.0, volumes=volumes, snapshot=snapshot)
    out = get_trade_advice(1, _db=advice_db)
    assert out["dayVolume"] == pytest.approx(expected_day)
    assert out["turnDays"] == (None if expected_turn is None else pytest.approx(expected_turn))
    queue = [r for r in out["reasons"] if "卖单队列约" in r]
    assert bool(queue) == (expected_turn is not None and expected_turn > 14)


@pytest.mark.parametrize(
    ("trend", "phrase"),
    [
        pytest.param(-5.0, "大盘近 30 天 -5.0%：趋势向下，别挂高价等，尽快出手", id="down"),
        pytest.param(5.0, "大盘近 30 天 +5.0%：可以挂高一点慢慢卖", id="up"),
        pytest.param(1.0, None, id="flat_adds_nothing"),
    ],
)
def test_trend_correction(advice_db, trend, phrase):
    """大盘修正：≤ -3% / ≥ +3% 各追加一条依据并接到两条建议后面；中间区间不加。"""
    _seed(advice_db, 1, buy=10.0, sell=12.0, volumes=[300] * 7)
    out = get_trade_advice(1, _db=advice_db, trend_30d=trend)
    if phrase is None:
        assert not any("大盘近 30 天" in r for r in out["reasons"])
        assert "大盘" not in out["buyAdvice"] and "大盘" not in out["sellAdvice"]
    else:
        assert phrase in out["reasons"]
        assert out["buyAdvice"].endswith(phrase)
        assert out["sellAdvice"].endswith(phrase)


def test_sub_isk_prices_keep_precision_in_advice(advice_db):
    """0.01 级的小额报价在建议文案里不能被四舍五入成一个不能用的挂单价。"""
    _seed(advice_db, 1, buy=0.02, sell=0.03, volumes=[300] * 7)
    out = get_trade_advice(1, _db=advice_db)
    assert out["verdict"] == "two_sided"  # 价差 33.3% > 8%
    assert "= 0.0202 ISK" in out["buyAdvice"]  # 0.02 × 1.01
    assert "= 0.0297 ISK" in out["sellAdvice"]  # 0.03 × 0.99


def test_missing_data_is_none_never_zero(advice_db):
    """缺数据一律 None：没挂单行 / 没成交记录 / 没快照都不拿 0 冒充。"""
    out = get_trade_advice(999, _db=advice_db)
    for key in ("buyPrice", "sellPrice", "spreadPct", "dayVolume", "orderVolume", "turnDays"):
        assert out[key] is None, key
    assert out["verdict"] == "no_data"
    assert out["name"] == "999"  # ref.item 里没有它 → 退回 type_id
    assert out["buyAdvice"] == out["sellAdvice"] == NO_DATA_ADVICE


def test_missing_tables_do_not_raise(db_manager):
    """market.db 还只有空文件（三张表都没建）→ 照给 no_data，不抛 OperationalError。"""
    out = get_trade_advice(34, _db=db_manager)
    assert out["verdict"] == "no_data"
    # 连 ref.item 都没有 → 名字走 terminology.json 的矿物覆盖（34 是基础矿物，不在 item 表）
    assert out["name"] == "三钛合金"
    assert (out["dayVolume"], out["orderVolume"]) == (None, None)
