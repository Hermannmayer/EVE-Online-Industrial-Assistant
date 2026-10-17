"""大盘指数服务测试 —— 纯计算（加权中位数/截断/权重上限/链式累乘）+ 临时库集成。

只覆盖会坏的逻辑（CLAUDE.md 测试判定表）：数值公式、官方篮子分类、逐日累乘的「成分变更日不跳变」、
数据不足给 `None`、物化表与广度统计的 SQL。造数全用 `tests/conftest.py` 的 `db_manager` fixture
（临时 ref/mkt/bp/user 四库），不碰真实库、不发网络请求。
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from services import market_index_service as mis
from services.importers.getprices import GLOBAL_PRICE_DDL
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


def _insert_global_prices(db, rows: list[tuple[int, str, float]]) -> None:
    """写入 `global_price_daily`（**全服统一价**，`rows` = `[(type_id, date, average_price), ...]`）。

    PLEX 的权威序列在**全域市场 region**（`mis.PLEX_REGION_ID`）的 `price_history` 里
    （BL-012）；这张表只剩「那个 region 还没拉过」时的兜底。写入时 `volume` 恒 0 ——
    它只有价、没有成交（见 `services/importers/getprices.GLOBAL_PRICE_DDL` 的说明）。
    """
    with db.connect("mkt") as conn:
        conn.execute(GLOBAL_PRICE_DDL)
        conn.executemany(
            "INSERT OR REPLACE INTO global_price_daily "
            "(type_id, date, average_price, adjusted_price, fetched_at) VALUES (?, ?, ?, ?, ?)",
            [(tid, day, average, average, "2026-01-01T00:00:00+00:00") for tid, day, average in rows],
        )


def _seed_market_groups(db, type_ids: set[int]) -> None:
    """给这些 type 在临时 `ref` 库里造出 `item.market_group_id`（指数篮子映射读这一列）。

    注意：指数篮子成员按**官方 MER 清单**判定（`market_index_service`），这里的合成
    `market_group_id` 只用于构造「有/无市场分类」的边界——合成值不会命中官方区间，
    所以这些 type 不会进任何官方篮子（用例要真实成员时用 `_seed_official_items`）。
    """
    with db.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS item (type_id INTEGER PRIMARY KEY, zh_name TEXT, market_group_id INTEGER)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO item (type_id, zh_name, market_group_id) VALUES (?, ?, ?)",
            [(int(t), f"#{int(t)}", 1000 + int(t)) for t in sorted(type_ids)],
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
#  官方 MER 篮子（MPI / PPPI / SPPI / CPI）
# ════════════════════════════════════════════════════════════════

#: `(type_id, market_group_id, 官方指数)`；官方真值取自 CCP MER 2026-09 的
#: `data/index_baskets.csv`，`market_group_id` 取自本地 SDE（`reference.db.item`）。
#: 覆盖：普通 market_group 映射 / 多指数共用市场分组的 type 例外 / 显式排除 /
#: 无市场分类 / PLEX（独立锚，不在 MER 四指数里）。
_OFFICIAL_BASKET_CASES = [
    (34, 1857, "mpi"),  # Tritanium：官方 MPI（市场分组 1857 也含 PPPI/SPPI → type 例外）
    (18, 516, "pppi"),  # Plagioclase：官方 PPPI·Ore
    (691, 264, "sppi"),  # Rifter Blueprint：官方 SPPI·Blueprints
    (587, 64, "cpi"),  # Rifter：官方 CPI·Tech I ships（回归：成品舰船不进 SPPI）
    (178, 113, "cpi"),  # Carbonized Lead S：官方 CPI·Ammo
    (28840, 1661, "cpi"),  # Magic Crystal Ball：特殊版物品（多指数共用市场分组 → type 例外）
    (4005, 1620, None),  # 官方清单里没有的本地 type → 显式排除
    (44992, 1923, None),  # PLEX：不在 MER 四指数里（独立锚）
    (9999, None, None),  # 没有市场分类 → 不属于任何篮子
]


@pytest.mark.parametrize(("type_id", "market_group_id", "expected"), _OFFICIAL_BASKET_CASES)
def test_classify_official_basket(type_id, market_group_id, expected):
    """官方篮子分类：market_group 区间 + type 例外 + 显式排除（纯函数，不依赖库）。"""
    assert mis.classify_official_basket(type_id, market_group_id) == expected


def _seed_official_items(db) -> None:
    """在临时 `ref` 库造出官方篮子相关 type 的 `item.market_group_id`（映射用）。"""
    with db.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS item "
            "(type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT, market_group_id INTEGER)"
        )
        conn.executemany(
            "INSERT OR REPLACE INTO item (type_id, zh_name, en_name, market_group_id) VALUES (?, ?, ?, ?)",
            [(t, f"#{t}", f"#{t}", mg) for t, mg, _expected in _OFFICIAL_BASKET_CASES if t != 9999],
        )


def test_official_index_members_reads_ref_item(db_manager):
    """官方篮子成员集成：`ref.item.market_group_id` → 四个 type 集合；排除项不进任何篮子。"""
    _seed_official_items(db_manager)

    sets = mis.official_index_members(db_manager)

    assert sets["mpi"] == set(mis.MPI_TYPES)  # 固定 8 矿恒在
    assert sets["pppi"] == {18}
    assert sets["sppi"] == {691}
    assert sets["cpi"] == {178, 587, 28840}
    assert 4005 not in sets["cpi"] | sets["pppi"] | sets["sppi"]
    assert mis.PLEX_TYPE_ID not in sets["cpi"]


def test_official_index_members_without_item_table_keeps_fixed_baskets(db_manager):
    """没有 `item` 表 / 缺 `market_group_id` 列（全新库、数据没导好）：不炸，固定篮子仍在。"""
    sets = mis.official_index_members(db_manager)
    assert sets["mpi"] == set(mis.MPI_TYPES)
    assert (sets["pppi"], sets["sppi"], sets["cpi"]) == (set(), set(), set())

    with db_manager.connect("ref") as conn:
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT)")
    assert mis.official_index_members(db_manager)["mpi"] == set(mis.MPI_TYPES)


# ════════════════════════════════════════════════════════════════
#  临时库集成（公开接口）
# ════════════════════════════════════════════════════════════════


def test_cards_short_window_gives_none(db_manager):
    """只有 6 天数据：能出基期与 chg1，7/30/90/180 天窗口一律 None（不用 0 冒充）。"""
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 if i < 5 else 110.0) for i in range(6)])

    cards = {card["key"]: card for card in mis.get_index_cards(_db=db_manager)}
    plex = cards["plex"]

    assert [card["key"] for card in mis.get_index_cards(_db=db_manager)] == list(mis.INDEX_KEYS)
    assert plex["value"] == pytest.approx(110.0)
    assert plex["base_date"] == _day(4)  # 第 4 天覆盖满 5 天 → 基期
    assert plex["days"] == 2
    assert plex["chg1"] == pytest.approx(10.0)
    for field in ("chg7", "chg30", "chg90", "chg180"):
        assert plex[field] is None


def test_plex_uses_global_price_when_no_region_history(db_manager):
    """PLEX 的**兜底**序列来自全服统一价（`global_price_daily`）。

    用户口径：PLEX 价格全服统一、没有本地市场划分；工具中心的区块历史对它返回空
    （实测），所以全域 region（19000001）的成交历史还没拉过时，序列退回
    `/markets/prices/` 的每日快照（它只有价、没有成交量）。
    """
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 if i < 5 else 110.0) for i in range(6)])

    plex = {card["key"]: card for card in mis.get_index_cards(_db=db_manager)}["plex"]

    # 基期 = 第 4 天（覆盖满 5 天）=100，第 5 天 +10% → 110
    assert plex["value"] == pytest.approx(110.0)
    assert plex["days"] == 2


def test_region_history_wins_over_global_fallback(db_manager):
    """全域成交历史是**主源，全服价是兜底**：两者都在时以成交序列为准（BL-012）。

    回归用例：曾经无条件覆盖，而当时 8 种矿物也在全服快照表里 → 矿物的 398 天成交序列
    被换成「1 行当日价」，MPI 整条指数变空。
    PLEX 的成交序列现在写在官方 Global PLEX Market region（`19000001`）里，而指数区域
    是 Jita —— 读端口径必须认这个 region，否则 PLEX 又只剩全服价那一个点。
    """
    # 全域成交序列：+100%（±20% 截断后 +20% → 120）
    _insert_prices(
        db_manager,
        [(mis.PLEX_TYPE_ID, _day(i), 1000.0 if i < 5 else 2000.0, 10) for i in range(6)],
        region_id=mis.PLEX_REGION_ID,
    )
    # 全服序列：+10%（若被误用会得 110）
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 if i < 5 else 110.0) for i in range(6)])

    plex = {card["key"]: card for card in mis.get_index_cards(_db=db_manager)}["plex"]

    assert plex["value"] == pytest.approx(120.0)


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
    # PLEX 的成交历史在全域 market region（19000001）里（BL-012）
    _insert_prices(
        db_manager,
        [(mis.PLEX_TYPE_ID, _day(i), 80.0, 10) for i in range(-40, -30)]
        + [(mis.PLEX_TYPE_ID, _day(i), 100.0, 10) for i in range(-5, 0)],
        region_id=mis.PLEX_REGION_ID,
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
    """物化表：返回行数 = 表内行数、可重复重建；重建后的卡片与实时计算逐字一致。

    PLEX 走全域 market region（`PLEX_REGION_ID`）后**不再进 Jita 的 CPI 候选**
    （它的 Jita 行不存在），所以这张临时库里只有 plex 一条线有数据。
    """
    _insert_prices(
        db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 + i, 10) for i in range(8)], region_id=mis.PLEX_REGION_ID
    )

    live = mis.get_index_cards(_db=db_manager)  # 物化表还不存在 → 实时计算
    rows = mis.refresh_index_daily()

    with db_manager.connect("mkt") as conn:
        stored = conn.execute("SELECT COUNT(*) FROM market_index_daily WHERE region_id = ?", (_RID,)).fetchone()[0]
        plex_rows = conn.execute(
            "SELECT date, price, volume FROM market_index_daily WHERE type_id = ? ORDER BY date",
            (mis.INDEX_TYPE_IDS["plex"],),
        ).fetchall()

    assert rows == stored == 4  # 只有 plex 一条线：4 天（锚定日只看已补齐的成交/全服价数据日）
    assert [row[0] for row in plex_rows] == [_day(i) for i in range(4, 8)]
    assert [row[1] for row in plex_rows] == pytest.approx(
        [100.0, 100.0 * 105 / 104, 100.0 * 106 / 104, 100.0 * 107 / 104]
    )
    # 日成交量/日订单量也来自这条通道：从全域 region 的历史**透传真实值**，
    # 不再像全服价兜底那样恒为 0（= 每行 average × volume）
    assert [row[2] for row in plex_rows] == [(100.0 + i) * 10 for i in range(4, 8)]
    assert mis.get_index_cards(_db=db_manager) == live  # 缓存路径与实时路径同值
    assert mis.refresh_index_daily() == rows  # 重建幂等（先 DELETE 再插）


def test_dashboard_equals_separate_card_and_series_calls(db_manager):
    """`get_dashboard()` 与「`get_index_cards()` + `get_index_series()`」逐字段相等。

    这是「一次算完」的核心契约：成分集 / 观测装载 / 逐日累乘内部只跑一遍（省一半耗时），
    但两个返回值的形状与值必须与旧的两个公开入口一字不差（键序、点数、成员权重、价格、来源）。
    """
    # ① 空库（无历史、无蓝图）：全 None 的卡片 + 固定篮子成员，两条路径同样等价
    assert mis.get_dashboard(_db=db_manager) == {
        "cards": mis.get_index_cards(_db=db_manager),
        "series": mis.get_index_series(_db=db_manager),
    }

    # ② 有数据：34/35（官方 MPI 矿物）、PLEX（全服价）；蓝图表不再参与篮子判定
    _insert_prices(
        db_manager,
        [(34, _day(i), 100.0 + i, 10) for i in range(12)]
        + [(35, _day(i), 200.0 + i, 5) for i in range(12)]
        + [(2001, _day(i), 50.0 + i, 3) for i in range(12)],
    )
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 1000.0 + i) for i in range(12)])
    with db_manager.connect("ref") as conn:
        conn.execute(
            "CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT, market_group_id INTEGER)"
        )
        conn.execute("INSERT INTO item VALUES (?, ?, ?, ?)", (mis.PLEX_TYPE_ID, "伊甸币", "PLEX", 19))
    _seed_market_groups(db_manager, {2001, 3001, 34, 35})  # 3001 有市场分类 → 那 4 张是有效配方

    dashboard = mis.get_dashboard(_db=db_manager)

    # 非空校验：两条路都得真算出东西，「相等」才不是「都空转」
    assert any(card["value"] is not None for card in dashboard["cards"])
    assert any(series["members"] for series in dashboard["series"])

    assert dashboard == {
        "cards": mis.get_index_cards(_db=db_manager),
        "series": mis.get_index_series(_db=db_manager),
    }


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


# ════════════════════════════════════════════════════════════════
#  冷启动取数优化：等价性回归
# ════════════════════════════════════════════════════════════════


def test_active_member_filter_is_output_equivalent(db_manager, monkeypatch):
    """冷启动优化回归：只装载「有历史行」的成员**不改变任何输出**（序列/篮子成员/权重/涨跌）。

    优化点（`_load_observations`）：官方 CPI 本地有 14,218 个成员，但 Jita 的历史里只有
    ~4,700 个 type 有行；优化前对全部 18,411 个成员逐个探测（21 个 SQL 分块），优化后先取
    「有数据的成员」交集再批量查（6 块）。篮子定义、指数算法均不变。

    这里造出：官方成员（34/18/691/178）+ 非官方 type（9999，也有历史但不在任何篮子）+ PLEX；
    先跑正常路径，再把「活跃成员过滤」替换成「返回全部历史 type」（= 优化前的全量探测），
    断言两张 dashboard 逐字段完全相同（含 points 浮点值、members 权重/价格）。
    """
    _seed_official_items(db_manager)
    price_rows = []
    for tid in (34, 18, 178, 691, 9999):
        price_rows += [(tid, _day(i), 100.0 + i, 10 + i) for i in range(12)]
    _insert_prices(db_manager, price_rows)
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 1000.0 + i) for i in range(12)])

    filtered = mis.get_dashboard(_db=db_manager)
    # 非空校验：「相等」不能是「都空转」
    assert any(card["value"] is not None for card in filtered["cards"])
    assert any(series["members"] for series in filtered["series"])

    def all_history_ids(conn, region_id):
        return {int(r[0]) for r in conn.execute("SELECT DISTINCT type_id FROM price_history")}

    monkeypatch.setattr(mis, "_active_history_ids", all_history_ids)
    unfiltered = mis.get_dashboard(_db=db_manager)

    assert filtered == unfiltered


def test_dashboard_memory_cache_hits_and_refresh_invalidates(db_manager, monkeypatch):
    """进程内 TTL 缓存：第二次命中返回等值（深拷贝防污染）；refresh 成功后缓存失效重算。"""
    _seed_official_items(db_manager)
    _insert_prices(db_manager, [(34, _day(i), 100.0 + i, 10 + i) for i in range(12)])
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 1000.0 + i) for i in range(12)])

    loads = {"count": 0}
    real_load = mis._load_observations

    def counting_load(*args, **kwargs):
        loads["count"] += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(mis, "_load_observations", counting_load)
    # 缓存走 `_db is None` 的生产路径，`get_db()` 指向临时库；refresh 内部也走它。
    monkeypatch.setattr(mis, "get_db", lambda: db_manager)
    mis.clear_index_memory_cache()
    try:
        first = mis.get_dashboard()
        assert loads["count"] == 1, "首次未命中应装载一次观测"
        first["cards"][0]["value"] = -999.0  # 原地改返回值不得污染缓存
        first["series"][0]["members"].clear()

        second = mis.get_dashboard()
        assert loads["count"] == 1, "第二次应命中缓存，不再装载观测"
        assert second["cards"][0]["value"] != -999.0
        assert second["series"][0]["members"], "缓存命中必须是原值的深拷贝"

        mis.refresh_index_daily()
        assert loads["count"] == 2, "refresh 应重建一次（写物化表）"
        third = mis.get_dashboard()
        assert loads["count"] == 3, "refresh 成功后缓存失效，应重新装载观测"
        assert third == second
    finally:
        mis.clear_index_memory_cache()


def test_incremental_points_only_append_missing_days(db_manager, monkeypatch):
    """历史点位**一律不重算**：物化表已有 0/1/N 天缺口时只增量续算缺失日期。

    正确性底线（与全量重算逐点一致）在副本真实库上做过等价验证；这里用替身计数锁死
    「读路径不得再调用 `_build_index` 重算历史」，并验 0/1/N 天缺口只补缺失点。
    """
    _seed_official_items(db_manager)
    with db_manager.connect("mkt") as conn:
        conn.execute(mis.MARKET_INDEX_DDL)
        conn.executemany(
            "INSERT INTO market_index_daily (type_id, region_id, date, price, volume) VALUES (?, ?, ?, ?, ?)",
            [(mis.INDEX_TYPE_IDS[key], _RID, _day(i), 100.0, 0) for key in mis.INDEX_KEYS for i in range(12)],
        )
    _insert_prices(db_manager, [(34, _day(i), 100.0, 10) for i in range(12)])
    monkeypatch.setattr(
        mis, "_build_index", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("历史被重算！"))
    )

    # ① 缺 0 天（anchor = 物化表最后一天）：只读点位，不触发任何计算
    series = {item["key"]: item for item in mis.get_index_series(_db=db_manager)}
    assert len(series["mpi"]["points"]) == 12
    assert series["mpi"]["points"][-1]["date"] == _day(11)
    assert [p["value"] for p in series["mpi"]["points"]] == [100.0] * 12

    # ② 缺 1 天：day12 成员均价 +10% → 只 append 1 个点，历史前缀逐点不变
    _insert_prices(db_manager, [(34, _day(12), 110.0, 10)])
    mis.clear_index_memory_cache()  # 锚定日/结果有 10 分钟进程缓存，新交易日要让它重新取
    mpi = {item["key"]: item for item in mis.get_index_series(_db=db_manager)}["mpi"]
    assert len(mpi["points"]) == 13 and mpi["points"][-1]["date"] == _day(12)
    assert mpi["points"][-1]["value"] == pytest.approx(110.0)
    assert [p["value"] for p in mpi["points"][:12]] == [100.0] * 12
    with db_manager.connect("mkt") as conn:
        stored = conn.execute(
            "SELECT COUNT(*) FROM market_index_daily WHERE type_id = ?", (mis.INDEX_TYPE_IDS["mpi"],)
        ).fetchone()[0]
    assert stored == 13, "增量补的点必须落库（否则下次打开又重算）"

    # ③ 缺 N=3 天（物化表仍停在 day11）：只补 day12~14，历史不动
    _insert_prices(db_manager, [(34, _day(13), 121.0, 10), (34, _day(14), 133.1, 10)])
    mis.clear_index_memory_cache()
    series = {item["key"]: item for item in mis.get_index_series(_db=db_manager)}
    mpi = series["mpi"]
    assert len(mpi["points"]) == 15
    assert [p["date"] for p in mpi["points"][-3:]] == [_day(12), _day(13), _day(14)]
    assert [p["value"] for p in mpi["points"][-3:]] == pytest.approx([110.0, 121.0, 133.1])
    assert len(series["cpi"]["points"]) == 12, "无新数据的指数必须保持原样"

    # ④ 同日重复打开：物化点位已补齐到锚定日 → 不再新增任何点（增量函数只做空跑）
    appended_counts: list[int] = []
    real_append = mis._append_missing_days

    def counting_append(points, obs, members, anchor):
        result = real_append(points, obs, members, anchor)
        appended_counts.append(len(result) - len(points))
        return result

    monkeypatch.setattr(mis, "_append_missing_days", counting_append)
    again = {item["key"]: item for item in mis.get_index_series(_db=db_manager)}["mpi"]
    assert sum(appended_counts) == 0, "同日重复打开不得新增任何点位"
    assert again["points"] == mpi["points"]
