"""大盘指数服务测试 —— 纯计算（加权中位数/截断/权重上限/链式累乘）+ 临时库集成。

只覆盖会坏的逻辑（CLAUDE.md 测试判定表）：数值公式、蓝图层级分支、逐日累乘的「成分变更日不跳变」、
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

    PLEX 走这张表：它的价格全服一致、没有区域划分，ESI 的区块历史对它恒返回空
    （见 `services/importers/getprices.GLOBAL_PRICE_DDL` 的说明）。
    """
    with db.connect("mkt") as conn:
        conn.execute(GLOBAL_PRICE_DDL)
        conn.executemany(
            "INSERT OR REPLACE INTO global_price_daily "
            "(type_id, date, average_price, adjusted_price, fetched_at) VALUES (?, ?, ?, ?, ?)",
            [(tid, day, average, average, "2026-01-01T00:00:00+00:00") for tid, day, average in rows],
        )


def _seed_market_groups(db, type_ids: set[int]) -> None:
    """给这些 type 在临时 `ref` 库里造出 `item.market_group_id`（= SDE 里已发布的市场物品）。

    指数分类的「有效配方」判据靠它：产出物 `market_group_id` 为空 = CCP 留在 SDE 里、
    游戏内造不出来的占位配方（`帕拉丁级血袭者版蓝图` 之类），其材料关系不算数。
    **没被列进 `type_ids` 的产出物就是占位物品**（用例故意不给）。
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
#  蓝图层级（PPPI / SPPI）
# ════════════════════════════════════════════════════════════════


def test_blueprint_classes_split_primary_and_secondary(db_manager):
    """生产投入品按「产物是否还是生产投入品」分 PPPI / SPPI；占位配方不算配方。

    口径（2026-10 按用户反馈改）：**只有「有效配方」的材料关系才算数** —— 有效配方 =
    产出物在 `ref.item.market_group_id` 上有值（SDE 里已发布的市场物品）。CCP 在 SDE 里留着
    游戏内造不出来的占位配方（变体版蓝图 `帕拉丁级血袭者版蓝图` 这类），它们会把成品舰船当材料，
    旧口径（「被任何蓝图当材料即投入品」）因此把 151 个带「级」的成分（52.4% 权重）塞进 SPPI。

    9001~9004 制造 2000 ← 1000/1100（产物 2000 有市场分类 → 有效配方）
    9005~9007 制造 4000 ← 2000/3000/1100/1200；9009/9010 反应 2000 ← 3000
    9008 反应 5000 ← 2000；9011 发明 6000 ← 9999（invention 必须过滤掉）
    **9012 制造 7000 ← 1300，但 7000 的 market_group_id 为 NULL（占位配方）→ 1300 不算投入品**
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
                (9002, "manufacturing", 2000),
                (9003, "manufacturing", 2000),
                (9004, "manufacturing", 2000),
                (9005, "manufacturing", 4000),
                (9006, "manufacturing", 4000),
                (9007, "manufacturing", 4000),
                (9008, "reaction", 5000),
                (9009, "reaction", 2000),
                (9010, "reaction", 2000),
                (9011, "invention", 6000),
                (9012, "manufacturing", 7000),  # 占位配方：7000 没有市场分类
            ],
        )
        conn.executemany(
            "INSERT INTO blueprint_materials VALUES (?, ?, ?, 10, 10)",
            [
                (9001, "manufacturing", 1000),
                (9001, "manufacturing", 1100),
                (9002, "manufacturing", 1000),
                (9002, "manufacturing", 1100),
                (9003, "manufacturing", 1000),
                (9003, "manufacturing", 1100),
                (9004, "manufacturing", 1000),
                (9004, "manufacturing", 1100),
                (9005, "manufacturing", 2000),
                (9005, "manufacturing", 3000),
                (9005, "manufacturing", 1100),
                (9005, "manufacturing", 1200),
                (9006, "manufacturing", 2000),
                (9006, "manufacturing", 3000),
                (9006, "manufacturing", 1100),
                (9006, "manufacturing", 1200),
                (9007, "manufacturing", 2000),
                (9007, "manufacturing", 3000),
                (9007, "manufacturing", 1200),
                (9008, "reaction", 2000),
                (9009, "reaction", 3000),
                (9010, "reaction", 3000),
                (9011, "invention", 9999),
                (9012, "manufacturing", 1300),
            ],
        )
    _seed_market_groups(db_manager, {1000, 1100, 1200, 1300, 2000, 3000, 4000, 5000})  # 7000 故意不给

    pppi, sppi = mis._blueprint_classes(db_manager)

    # 1000/1100 供入 2000（还是投入品）；3000 供入 4000 与反应产物 2000（后者是投入品）→ PPPI
    assert pppi == {1000, 1100, 3000}
    # 2000 的产物（4000 / 反应 5000）都不再是投入品 → SPPI
    assert sppi == {2000}
    # 1300 只被 1 张有效配方（9012）用 → 不够 MIN_VALID_RECIPES，不算投入品
    assert mis.MIN_VALID_RECIPES == 4
    assert 1300 not in pppi | sppi
    # 1200 只被 3 张有效配方用（9005/9006/9007）→ 同样不够门槛
    assert 1200 not in pppi | sppi
    # invention 的 9999 不算材料，不该出现在任何一边
    assert 9999 not in pppi | sppi


def test_placeholder_recipe_makes_ship_a_consumer_good(db_manager):
    """回归：被**占位配方**（变体版蓝图）当材料的成品舰船 → 算消费品，不进 SPPI。

    用户报的 bug：「消费品和次级投入品是怎么算的？我看有很多舰船在里面」，并补充
    「帕拉丁级血袭者版这类在游戏里根本造不出来，虽然它有蓝图」。真实库实测：`先知级血袭者版`
    (33875)、`地狱天使级塔什蒙贡版`(33623) 的 `market_group_id` 为 NULL（未发布占位物品），
    而 `帕拉丁级`(28659)=1081 等真实市场物品有值 —— 占位配方的材料关系不算数。

    造数：舰船 5001 被制造蓝图 7001 当材料，但 7001 的产物 5002 **没有市场分类**（占位配方）；
    真投入品 4001 被 7002~7005 当材料，产物 4200 有市场分类。两者都有 30 天窗口内的成交。
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
            "INSERT INTO blueprint_products VALUES (?, 'manufacturing', ?, 1)",
            [(7001, 5002), (7002, 4200), (7003, 4200), (7004, 4200), (7005, 4200)],
        )
        conn.executemany(
            "INSERT INTO blueprint_materials VALUES (?, 'manufacturing', ?, 10, 10)",
            [(7001, 5001), (7002, 4001), (7003, 4001), (7004, 4001), (7005, 4001)],
        )
    _seed_market_groups(db_manager, {4001, 4200, 5001})  # 5002（占位产物的产物）故意不给

    _insert_prices(
        db_manager,
        [(5001, _day(i), 100.0, 10) for i in range(5)] + [(4001, _day(i), 100.0, 10) for i in range(5)],
    )
    anchor = _BASE_DAY + timedelta(days=4)

    sets, materials = mis._member_sets(db_manager, _RID, ["pppi", "sppi", "cpi"], anchor)

    assert 4001 in materials and 4001 in sets["sppi"] and 4001 not in sets["cpi"]  # 真投入品：SPPI
    assert 5001 not in sets["sppi"]  # 占位配方里的成品舰船不算次级投入品
    assert 5001 not in sets["pppi"]
    assert 5001 in sets["cpi"]  # 回到消费品篮子（有成交额 + 覆盖天数足够）


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
    """PLEX 的序列来自**全服统一价**（`global_price_daily`）—— 区块历史对它恒为空。

    用户口径：PLEX 价格全服统一、没有本地市场划分；ESI 的区块历史端点在 Jita/Amarr
    都返回空列表（实测），所以它的时间序列只能靠 `/markets/prices/` 的每日快照攒。
    """
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 100.0 if i < 5 else 110.0) for i in range(6)])

    plex = {card["key"]: card for card in mis.get_index_cards(_db=db_manager)}["plex"]

    # 基期 = 第 4 天（覆盖满 5 天）=100，第 5 天 +10% → 110
    assert plex["value"] == pytest.approx(110.0)
    assert plex["days"] == 2


def test_region_history_wins_over_global_fallback(db_manager):
    """全服价是**退路，不是覆盖**：区块成交序列存在时以它为准。

    回归用例：曾经无条件覆盖，而当时 8 种矿物也在全服快照表里 → 矿物的 398 天成交序列
    被换成「1 行当日价」，MPI 整条指数变空。
    """
    # 区块序列：+100%（±20% 截断后 +20% → 120）
    _insert_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 1000.0 if i < 5 else 2000.0, 10) for i in range(6)])
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

    # ② 有数据：34/35（MPI 矿物；同时进 CPI 候选）、2001（被 4 张有效配方当材料 → SPPI）、PLEX（全服价）
    _insert_prices(
        db_manager,
        [(34, _day(i), 100.0 + i, 10) for i in range(12)]
        + [(35, _day(i), 200.0 + i, 5) for i in range(12)]
        + [(2001, _day(i), 50.0 + i, 3) for i in range(12)],
    )
    _insert_global_prices(db_manager, [(mis.PLEX_TYPE_ID, _day(i), 1000.0 + i) for i in range(12)])
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
            "INSERT INTO blueprint_products VALUES (?, 'manufacturing', 3001, 1)",
            [(9001,), (9002,), (9003,), (9004,)],
        )
        conn.executemany(
            "INSERT INTO blueprint_materials VALUES (?, 'manufacturing', 2001, 10, 10)",
            [(9001,), (9002,), (9003,), (9004,)],
        )
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
