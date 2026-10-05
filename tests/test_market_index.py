"""大盘指数服务测试 —— 纯计算（加权中位数/截断/权重上限/链式累乘）+ 临时库集成。

只覆盖会坏的逻辑（CLAUDE.md 测试判定表）：数值公式、蓝图层级分支、逐日累乘的「成分变更日不跳变」、
数据不足给 `None`、物化表与广度统计的 SQL。造数全用 `tests/conftest.py` 的 `db_manager` fixture
（临时 ref/mkt/bp/user 四库），不碰真实库、不发网络请求。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services import market_index_service as mis
from services.price_history import PRICE_HISTORY_DDL

_RID = mis.JITA_RID

#: 固定基准日 —— 与真实时钟无关，保证用例可复现
_BASE_DAY = date(2026, 1, 1)


def _day(offset: int) -> str:
    """基准日 + `offset` 天的日期串。"""
    return (_BASE_DAY + timedelta(days=offset)).isoformat()


def _rows(spec: dict[int, list[tuple[int, float]]], volume: int = 10) -> dict[int, list[tuple[str, float, int]]]:
    """`{type_id: [(day_offset, average), ...]}` → `_build_index` 的 obs 载荷（按日期升序）。"""
    return {tid: [(_day(offset), price, volume) for offset, price in items] for tid, items in spec.items()}


def _insert_prices(db, rows: list[tuple[int, str, float, int]], region_id: int = _RID) -> None:
    """写入 `price_history`（`rows` = `[(type_id, date, average, volume), ...]`）。"""
    with db.connect("mkt") as conn:
        conn.execute(PRICE_HISTORY_DDL)
        conn.executemany(
            "INSERT OR REPLACE INTO price_history "
            "(type_id, region_id, date, average, highest, lowest, volume, order_count, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (tid, region_id, day, average, average, average, volume, 0, "2026-01-01T00:00:00+00:00")
                for tid, day, average, volume in rows
            ],
        )


# ════════════════════════════════════════════════════════════════
#  纯计算
# ════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("values", "weights", "expected"),
    [
        ([1.0, 2.0, 3.0], [1.0, 1.0, 1.0], 2.0),  # 奇数等权 → 中间值
        ([1.0, 2.0, 3.0, 4.0], [1.0, 1.0, 1.0, 1.0], 2.5),  # 偶数等权 → 中间两个的平均（标准中位数）
        ([0.01, 0.02, 0.03, 5.0], [1.0, 1.0, 1.0, 1.0], 0.025),  # 极端值不改变中间两个
        ([0.01, -0.02, 0.03], [1.0, 5.0, 1.0], -0.02),  # 权重大的样本把中位数拉过去
        ([0.1], [0.5], 0.1),  # 单样本
        ([0.1, 0.2], [0.0, 0.0], None),  # 无正权重 → None（不用 0 冒充）
        ([], [], None),
    ],
)
def test_weighted_median(values, weights, expected):
    result = mis.weighted_median(values, weights)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0.5, 0.2), (-0.5, -0.2), (0.2, 0.2), (-0.2, -0.2), (0.05, 0.05), (None, None)],
)
def test_clamp_return_bounds_to_20_percent(raw, expected):
    assert mis.clamp_return(raw) == expected


def test_cap_weights_limits_single_member_then_renormalizes():
    capped = mis.cap_weights({"a": 90.0, "b": 5.0, "c": 5.0})
    # 上限 = 25% × 原始合计(100) = 25 → a 夹到 25，三者按夹后的合计 35 归一化
    assert capped["a"] == (pytest.approx(25 / 35), True)
    assert capped["b"] == (pytest.approx(5 / 35), False)
    assert capped["c"] == (pytest.approx(5 / 35), False)
    assert sum(weight for weight, _capped in capped.values()) == pytest.approx(1.0)

    # 4 个等额成员：没有任何一个超过 25%（1/4 = 上限）→ 不触顶，权重就是原始占比
    plain = mis.cap_weights({"a": 1.0, "b": 1.0, "c": 1.0, "d": 1.0})
    assert plain == {key: (pytest.approx(0.25), False) for key in "abcd"}
    assert mis.cap_weights({"a": 0.0}) == {}
    assert mis.cap_weights({}) == {}


def test_index_does_not_jump_on_membership_change():
    """成分换入换出只改「当日参与集合与权重」，不重设基期 —— 成分变更日指数连续。

    编排：A/B 成交第 0~9 天，C/D 成交第 5~11 天；C/D 在第 10 天从 100 → 110（+10%），
    于是第 10 天的指数只能由 C/D 推出，而第 9 天还在用 A/B —— 换成分那天的指数必须等于
    「上一日 × (1 + 新成分收益)」，不能回到基期 100，也不能断裂。
    """
    obs = _rows(
        {
            101: [(i, 100.0) for i in range(10)],
            102: [(i, 100.0) for i in range(10)],
            201: [(i, 100.0) for i in range(5, 10)] + [(10, 110.0), (11, 110.0)],
            202: [(i, 100.0) for i in range(5, 10)] + [(10, 110.0), (11, 110.0)],
        }
    )
    built = mis._build_index(obs, {101, 102, 201, 202})
    levels = {point["date"]: point["value"] for point in built.points}

    assert list(levels) == [_day(i) for i in range(4, 12)]  # 第 4 天覆盖满 5 天 → 首个可算日
    assert levels[_day(4)] == mis.BASE_VALUE  # 基期 = 首个可算日 = 100
    assert levels[_day(9)] == pytest.approx(mis.BASE_VALUE)  # 第 4~9 天横盘
    assert levels[_day(10)] == pytest.approx(levels[_day(9)] * 1.10)  # 换成分日：连续，无跳变
    assert levels[_day(11)] == pytest.approx(levels[_day(10)])  # 第 11 天持平

    # A/B 第 9 天之后不再成交 → 最后一天的参与成分只剩 C/D
    assert set(built.weights) == {201, 202}


def test_index_clamps_single_member_daily_return():
    """单个成员一天翻两倍 → 日收益按 ±20% 截断 → 指数只涨 20%。"""
    obs = _rows({777: [(i, 100.0) for i in range(5)] + [(5, 300.0)]})
    built = mis._build_index(obs, {777})

    assert [point["date"] for point in built.points] == [_day(4), _day(5)]
    assert built.points[0]["value"] == mis.BASE_VALUE
    assert built.points[0]["volume"] == 1000  # 当日成交额 = 100 × 10
    assert built.points[1]["value"] == pytest.approx(mis.BASE_VALUE * 1.2)
    assert built.weights[777][0] == pytest.approx(1.0)


# ════════════════════════════════════════════════════════════════
#  蓝图层级（PPPI / SPPI）
# ════════════════════════════════════════════════════════════════


def test_blueprint_classes_split_primary_and_secondary(db_manager):
    """材料供入的产物**本身还是材料** → PPPI；否则 → SPPI；invention 不参与判定。

    9001 制造 2000 ← 1000/1100；9002 制造 4000 ← 2000/3000/1100；9003 反应 5000 ← 2000；
    9005 反应 2000 ← 3000；9004 发明 6000 ← 9999（invention 必须被过滤掉）。
    """
    with db_manager.connect("bp") as conn:
        conn.execute(
            "CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, "
            "material_type_id INTEGER, quantity INTEGER, wastefactor INTEGER DEFAULT 10)"
        )
        conn.execute(
            "CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, "
            "product_type_id INTEGER, quantity INTEGER)"
        )
        conn.executemany(
            "INSERT INTO blueprint_products VALUES (?, ?, ?, 1)",
            [
                (9001, "manufacturing", 2000),
                (9002, "manufacturing", 4000),
                (9003, "reaction", 5000),
                (9005, "reaction", 2000),
                (9004, "invention", 6000),
            ],
        )
        conn.executemany(
            "INSERT INTO blueprint_materials VALUES (?, ?, ?, 10, 10)",
            [
                (9001, "manufacturing", 1000),
                (9001, "manufacturing", 1100),
                (9002, "manufacturing", 2000),
                (9002, "manufacturing", 3000),
                (9002, "manufacturing", 1100),
                (9003, "reaction", 2000),
                (9005, "reaction", 3000),
                (9004, "invention", 9999),
            ],
        )

    pppi, sppi = mis._blueprint_classes(db_manager)

    # 1000/1100 供入 2000（还是材料）；3000 供入 4000 与反应产物 2000（后者是材料）→ PPPI
    assert pppi == {1000, 1100, 3000}
    # 2000 的产物（4000 / 反应 5000）都不再是材料 → SPPI
    assert sppi == {2000}
    # invention 的 9999 不算材料，不该出现在任何一边
    assert 9999 not in pppi | sppi


# ════════════════════════════════════════════════════════════════
#  临时库集成（公开接口）
# ════════════════════════════════════════════════════════════════


def test_cards_short_window_gives_none(db_manager):
    """只有 6 天数据：能出基期与 chg1，7/30/90/180 天窗口一律 None（不用 0 冒充）。"""
    _insert_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 if i < 5 else 110.0, 10) for i in range(6)])

    cards = {card["key"]: card for card in mis.get_index_cards(_db=db_manager)}
    plex = cards["plex"]

    assert [card["key"] for card in mis.get_index_cards(_db=db_manager)] == list(mis.INDEX_KEYS)
    assert plex["value"] == pytest.approx(110.0)
    assert plex["base_date"] == _day(4)  # 第 4 天覆盖满 5 天 → 基期
    assert plex["days"] == 2
    assert plex["chg1"] == pytest.approx(10.0)
    for field in ("chg7", "chg30", "chg90", "chg180"):
        assert plex[field] is None


def test_cards_and_series_without_data(db_manager):
    """没有任何历史：涨跌/现值全 None；固定篮子仍列出成员、权重 0；广度全 None。"""
    cards = mis.get_index_cards(_db=db_manager)
    assert [card["key"] for card in cards] == list(mis.INDEX_KEYS)
    for card in cards:
        assert card["label"] == mis.INDEX_LABELS[card["key"]]
        assert (card["value"], card["days"], card["base_date"]) == (None, 0, None)
        assert all(card[field] is None for field in ("chg1", "chg7", "chg30", "chg90", "chg180"))

    mpi = mis.get_index_series(["mpi"], _db=db_manager)[0]
    assert mpi["points"] == []
    assert [member["typeId"] for member in mpi["members"]] == sorted(mis.MPI_TYPES)
    assert all(member["weight"] == 0.0 and member["capped"] is False for member in mpi["members"])
    assert all(member["price"] is None and member["chg30"] is None for member in mpi["members"])
    assert {member["source"] for member in mpi["members"]} == {"fixed"}

    assert mis.get_breadth(_db=db_manager) == {
        "date": None,
        "advancers": None,
        "decliners": None,
        "unchanged": None,
        "turnover": None,
    }


def test_series_members_carry_weight_price_and_source(db_manager):
    """篮子成员表：权重归一化、现价 = 锚定日（含）之前最近一次成交均价、chg30 口径。"""
    # 40 天前 80 → 最近 5 天 100（成员自身 30 天涨幅 +25%；指数那边会被 ±20% 截断）
    _insert_prices(
        db_manager,
        [(mis.PLEX_TYPE_ID, _day(i), 80.0, 10) for i in range(-40, -30)]
        + [(mis.PLEX_TYPE_ID, _day(i), 100.0, 10) for i in range(-5, 0)],
    )
    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT)")
        conn.execute("INSERT INTO item VALUES (?, ?, ?)", (mis.PLEX_TYPE_ID, "伊甸币", "PLEX"))

    series = mis.get_index_series(["plex"], _db=db_manager)[0]
    member = series["members"][0]

    assert [point["date"] for point in series["points"]] == [_day(i) for i in range(-36, -30)] + [
        _day(i) for i in range(-5, 0)
    ]
    assert member["typeId"] == mis.PLEX_TYPE_ID
    assert member["name"] == "伊甸币"
    assert member["weight"] == pytest.approx(1.0)
    assert member["price"] == pytest.approx(100.0)
    assert member["chg30"] == pytest.approx(25.0)
    assert member["source"] == "fixed"


def test_refresh_index_daily_materializes_and_cards_use_cache(db_manager):
    """物化表：返回行数 = 表内行数、可重复重建；重建后的卡片与实时计算逐字一致。"""
    _insert_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 + i, 10) for i in range(8)])

    live = mis.get_index_cards(_db=db_manager)  # 物化表还不存在 → 实时计算
    rows = mis.refresh_index_daily()

    with db_manager.connect("mkt") as conn:
        stored = conn.execute("SELECT COUNT(*) FROM market_index_daily WHERE region_id = ?", (_RID,)).fetchone()[0]
        plex_rows = conn.execute(
            "SELECT date, price FROM market_index_daily WHERE type_id = ? ORDER BY date",
            (mis.INDEX_TYPE_IDS["plex"],),
        ).fetchall()

    assert rows == stored == 8  # plex 4 天 + cpi（同一个 type 也算消费品代理）4 天
    assert [row[0] for row in plex_rows] == [_day(i) for i in range(4, 8)]
    assert [row[1] for row in plex_rows] == pytest.approx(
        [100.0, 100.0 * 105 / 104, 100.0 * 106 / 104, 100.0 * 107 / 104]
    )
    assert mis.get_index_cards(_db=db_manager) == live  # 缓存路径与实时路径同值
    assert mis.refresh_index_daily() == rows  # 重建幂等（先 DELETE 再插）


def test_breadth_counts_advancers_decliners_and_turnover(db_manager):
    """广度：当日有成交且此前有成交的 type 才计数；当日成交额只算最新交易日。"""
    _insert_prices(
        db_manager,
        [
            (11, _day(10), 100.0, 1),
            (11, _day(11), 110.0, 2),  # 涨
            (12, _day(10), 100.0, 3),
            (12, _day(11), 90.0, 4),  # 跌
            (13, _day(10), 100.0, 5),
            (13, _day(11), 100.0, 6),  # 平
            (14, _day(10), 100.0, 7),  # 当日没成交 → 不计入涨跌家数
        ],
    )

    breadth = mis.get_breadth(_db=db_manager)

    assert breadth["date"] == _day(11)
    assert (breadth["advancers"], breadth["decliners"], breadth["unchanged"]) == (1, 1, 1)
    assert breadth["turnover"] == pytest.approx(110.0 * 2 + 90.0 * 4 + 100.0 * 6)
