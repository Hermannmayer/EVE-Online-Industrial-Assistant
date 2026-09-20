"""合同服务层测试 —— 三个子页入口的取数与拼装。

用**假容器 + 真实 sqlite 文件**，不用 mock 掉 SQL：这批代码里出错的地方基本都在 SQL
（星门那个反直觉的 join、`IN (?)` 的分块、ATTACH 后的跨库表名），mock 掉就什么都测不到。

覆盖的是**会静默给错结论的分支**：
  - 跳数四种状态（算出来 / 没选口径 / 起止点解析不出 / 所选口径下无路线）
  - 含蓝图合同走「蓝图市价 + 制造利润」而不是普通内容物市价
  - 本星域无市价时回落到 Jita（用户可手动输入任意星域，那些星域没有市场数据）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from services import contract_service as cs

pytestmark = pytest.mark.fast

# ── 星系：J（高安）— L（低安）— H（高安飞地，只能穿低安到达）──
_JITA, _LOWSEC, _ISLAND = 30000142, 30000200, 30000300
_ST_JITA, _ST_ISLAND, _ST_STRUCTURE = 60003760, 60003184, 1047596820557

#: `(stargate_id, solar_system_id, destination_system_id)` —— 注意第三列存的是**星门 id**，
#: 与被测代码的 join 口径一致（真实库就是这样）。
_GATES = [
    (50000001, _JITA, 50000002),
    (50000002, _LOWSEC, 50000001),
    (50000003, _LOWSEC, 50000004),
    (50000004, _ISLAND, 50000003),
]

_ITEMS = {
    # 3: 含蓝图 1000（产物 2000，1 个/次；材料 34 基础量 100），BPC 3 次作业
    3: [
        {
            "record_id": 1,
            "item_id": 901,
            "type_id": 1000,
            "quantity": 1,
            "is_blueprint_copy": True,
            "runs": 3,
            "material_efficiency": 0,
        }
    ],
}

_CONTRACTS = [
    # 1: 运输，起止点都能解析，高安可达
    (1, "courier", _ST_JITA, _ST_ISLAND, {"reward": 1_000_000.0, "volume": 100.0}),
    # 2: 运输，终点是玩家建筑 → 解析不出星系
    (2, "courier", _ST_JITA, _ST_STRUCTURE, {"reward": 2_000_000.0, "volume": 50.0}),
    # 3: 物品交换，含蓝图（有发布者 id —— 名字另存在 `contract_issuers`）
    (3, "item_exchange", None, None, {"price": 10_000.0, "issuer_id": 90000001}),
    # 4: 拍卖，含一口价（无物品 —— 还没拉过）
    (4, "auction", None, None, {"price": 100.0, "buyout": 500.0}),
]


class _FakeDb:
    """`DatabaseManager.connect` 的最小忠实替身：ATTACH 辅助库 + 设 row_factory。"""

    def __init__(self, paths: dict[str, Path]):
        self._paths = paths

    def connect(self, primary: str, *attach: str):
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            conn = sqlite3.connect(self._paths[primary])
            conn.row_factory = sqlite3.Row
            for alias in attach:
                conn.execute("ATTACH DATABASE ? AS ?", (str(self._paths[alias]), alias))
            try:
                yield conn
            finally:
                conn.close()

        return _cm()


class _FakeRepo:
    """真 `MarketRepository` 的薄替身 —— 只实现被测代码用到的那个方法。"""

    def __init__(self, paths: dict[str, Path]):
        from services.repositories.market_repository import MarketRepository

        class _OneAlias:
            def __init__(self, p):
                self._p = p

            def connect(self, *_):
                from contextlib import contextmanager

                @contextmanager
                def _cm():
                    conn = sqlite3.connect(self._p)
                    conn.row_factory = sqlite3.Row
                    try:
                        yield conn
                    finally:
                        conn.close()

                return _cm()

        self._real = MarketRepository(_OneAlias(paths["mkt"]))

    def get_prices_by_region(self, ids, region_id, price_type):
        return self._real.get_prices_by_region(list(ids), region_id, price_type)


class _FakeContainer:
    def __init__(self, paths):
        self.db = _FakeDb(paths)
        self.market_repo = _FakeRepo(paths)


@pytest.fixture
def service(tmp_path, monkeypatch):
    paths = {a: tmp_path / f"{a}.db" for a in ("ref", "mkt", "bp")}
    _seed(paths)
    monkeypatch.setattr(cs, "get_container", lambda: _FakeContainer(paths))

    # `compute_jumps` 走 `services.logistics` 自己的容器入口与**进程级星门图缓存** ——
    # 不接管的话它会拿真实 reference.db 的 13,776 条星门去算，假图完全被无视。
    import services.logistics as lg

    monkeypatch.setattr(lg, "_default_db", lambda: _FakeDb(paths))
    monkeypatch.setattr(lg, "_GATE_GRAPH", None)
    return cs


def _seed(paths: dict[str, Path]) -> None:
    ref = sqlite3.connect(paths["ref"])
    ref.executescript(
        """
        CREATE TABLE solar_system (solar_system_id INTEGER PRIMARY KEY, solar_system_name TEXT,
                                   region_id INTEGER, constellation_id INTEGER, security REAL);
        CREATE TABLE station (station_id INTEGER PRIMARY KEY, station_name TEXT, solar_system_id INTEGER,
                              operation_id INTEGER, station_type_id INTEGER, corporation_id INTEGER);
        CREATE TABLE stargate (stargate_id INTEGER PRIMARY KEY, solar_system_id INTEGER,
                               destination_system_id INTEGER);
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT,
                           en_group_name TEXT, zh_group_name TEXT, volume REAL DEFAULT 1.0);
        """
    )
    ref.executemany(
        "INSERT INTO solar_system VALUES (?, ?, 10000002, 1, ?)",
        [(_JITA, "Jita", 0.95), (_LOWSEC, "Ahbazon", 0.30), (_ISLAND, "Ossa", 0.53)],
    )
    ref.executemany(
        "INSERT INTO station VALUES (?, ?, ?, 14, 52678, 1000035)",
        [(_ST_JITA, "Jita IV - Moon 4", _JITA), (_ST_ISLAND, "Ossa IV - Station", _ISLAND)],
    )
    ref.executemany("INSERT INTO stargate VALUES (?, ?, ?)", _GATES)
    ref.executemany(
        "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?)",
        [
            (34, "三钛合金", "Tritanium", "Mineral", "矿物", 0.01),
            (2000, "渡鸦级", "Raven", "Battleship", "战列舰", 50000.0),
            (1000, "渡鸦级蓝图", "Raven Blueprint", "Battleship Blueprints", "战列舰蓝图", 0.01),
        ],
    )
    ref.commit()
    ref.close()

    mkt = sqlite3.connect(paths["mkt"])
    mkt.executescript(
        """
        CREATE TABLE public_contracts (
            contract_id INTEGER PRIMARY KEY, region_id INTEGER NOT NULL, type TEXT NOT NULL, title TEXT,
            price REAL DEFAULT 0, buyout REAL DEFAULT 0, reward REAL DEFAULT 0, collateral REAL DEFAULT 0,
            volume REAL DEFAULT 0, days_to_complete INTEGER DEFAULT 0, issuer_id INTEGER,
            issuer_corporation_id INTEGER, date_issued TEXT, date_expired TEXT,
            start_location_id INTEGER, end_location_id INTEGER, for_corporation INTEGER DEFAULT 0,
            fetch_time TEXT NOT NULL, items_fetched_at TEXT);
        CREATE TABLE contract_items (
            contract_id INTEGER, record_id INTEGER, item_id INTEGER, type_id INTEGER, quantity INTEGER,
            is_blueprint_copy INTEGER DEFAULT 0, is_included INTEGER DEFAULT 1,
            material_efficiency INTEGER DEFAULT 0, time_efficiency INTEGER DEFAULT 0, runs INTEGER DEFAULT 1,
            PRIMARY KEY (contract_id, record_id));
        CREATE TABLE market_prices (
            type_id INTEGER, region_id INTEGER, buy_price REAL, sell_price REAL,
            adjusted_price REAL DEFAULT 0.0, buy_volume INTEGER DEFAULT 0,
            sell_volume INTEGER DEFAULT 0, fetch_time TEXT);
        CREATE TABLE contract_issuers (
            issuer_id INTEGER PRIMARY KEY, name TEXT NOT NULL, fetched_at TEXT NOT NULL);
        """
    )
    for cid, ctype, start, end, extra in _CONTRACTS:
        mkt.execute(
            "INSERT INTO public_contracts (contract_id, region_id, type, price, buyout, reward, volume, "
            "issuer_id, date_expired, start_location_id, end_location_id, fetch_time, items_fetched_at) "
            "VALUES (?, 10000002, ?, ?, ?, ?, ?, ?, '2099-01-01T00:00:00Z', ?, ?, 'T1', ?)",
            (
                cid,
                ctype,
                extra.get("price", 0),
                extra.get("buyout", 0),
                extra.get("reward", 0),
                extra.get("volume", 0),
                extra.get("issuer_id"),
                start,
                end,
                "T1" if cid in _ITEMS else None,
            ),
        )
    mkt.execute("INSERT INTO contract_issuers (issuer_id, name, fetched_at) VALUES (90000001, '张三', 'T1')")
    for cid, items in _ITEMS.items():
        for it in items:
            mkt.execute(
                "INSERT INTO contract_items (contract_id, record_id, item_id, type_id, quantity, "
                "is_blueprint_copy, runs, material_efficiency) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    it["record_id"],
                    it["item_id"],
                    it["type_id"],
                    it["quantity"],
                    int(it.get("is_blueprint_copy", False)),
                    it.get("runs", 1),
                    it.get("material_efficiency", 0),
                ),
            )
    # 市价只在 Jita 登记：蓝图 1000 与产物 2000 各 1,000,000；材料 34 卖 1.0
    mkt.executemany(
        "INSERT INTO market_prices (type_id, region_id, buy_price, sell_price) VALUES (?, ?, ?, ?)",
        [
            (1000, 10000002, 900_000.0, 1_000_000.0),
            (2000, 10000002, 900_000.0, 1_000_000.0),
            (34, 10000002, 0.8, 1.0),
        ],
    )
    mkt.commit()
    mkt.close()

    bp = sqlite3.connect(paths["bp"])
    bp.executescript(
        """
        CREATE TABLE blueprint_products (blueprint_type_id INTEGER, activity TEXT, product_type_id INTEGER,
                                         quantity INTEGER DEFAULT 1, probability REAL DEFAULT 1.0,
                                         PRIMARY KEY (blueprint_type_id, activity, product_type_id));
        CREATE TABLE blueprint_materials (blueprint_type_id INTEGER, activity TEXT, material_type_id INTEGER,
                                          quantity INTEGER, PRIMARY KEY (blueprint_type_id, activity, material_type_id));
        """
    )
    bp.execute("INSERT INTO blueprint_products VALUES (1000, 'manufacturing', 2000, 1, 1.0)")
    bp.execute("INSERT INTO blueprint_materials VALUES (1000, 'manufacturing', 34, 100)")
    bp.commit()
    bp.close()


# ═══════════════════════════════════════════════════════
#  运输页：跳数四态
# ═══════════════════════════════════════════════════════


class TestCourierJumps:
    def test_not_computed_until_mode_chosen(self, service):
        """用户没选口径时一个都不算 —— 这是他明确要求的（选了才算）"""
        rows = {r["contract_id"]: r for r in service.load_courier_contracts(10000002, jump_mode="none")}
        assert all(r["jumps_status"] == cs.JUMP_NOT_COMPUTED for r in rows.values())
        assert all(r["jumps"] is None for r in rows.values())

    def test_shortest_computes_through_lowsec(self, service):
        rows = {r["contract_id"]: r for r in service.load_courier_contracts(10000002, jump_mode="shortest")}
        assert rows[1]["jumps_status"] == cs.JUMP_OK
        assert rows[1]["jumps"] == 2  # Jita - Ahbazon - Ossa

    def test_highsec_reports_unroutable_not_unknown(self, service):
        """高安飞地只能穿低安到达 —— 必须是「无路线」，不能和「解析不出」混为一谈。

        两者对跑货的人是相反的行动：前者是「这活要进低安，想清楚」，
        后者是「我们不知道这是哪，可能不该接」。
        """
        rows = {r["contract_id"]: r for r in service.load_courier_contracts(10000002, jump_mode="highsec")}
        assert rows[1]["jumps_status"] == cs.JUMP_UNROUTABLE
        assert rows[1]["jumps"] is None
        assert rows[1]["isk_per_jump"] is None  # 未算出就不能给 0 兜底

    def test_unknown_endpoint_for_player_structure(self, service):
        rows = {r["contract_id"]: r for r in service.load_courier_contracts(10000002, jump_mode="shortest")}
        assert rows[2]["jumps_status"] == cs.JUMP_UNKNOWN_ENDPOINT

    def test_station_names_attached(self, service):
        rows = {r["contract_id"]: r for r in service.load_courier_contracts(10000002, jump_mode="shortest")}
        assert rows[1]["start_station"] == "Jita IV - Moon 4"
        assert rows[1]["end_system"] == "Ossa"
        assert rows[1]["start_security"] == pytest.approx(0.95)
        assert rows[2]["end_station"] == ""  # 玩家建筑查不到站点名，如实留空


# ═══════════════════════════════════════════════════════
#  物品交换页：蓝图分支
# ═══════════════════════════════════════════════════════


class TestExchangeBlueprints:
    def test_blueprint_contract_uses_manufacturing_profit(self, service):
        row = next(r for r in service.load_exchange_contracts(10000002) if r["contract_id"] == 3)
        assert row["has_blueprint"] is True
        assert row["blueprint_value"] == 1_000_000.0  # 蓝图自身市价
        # 3 次作业：产物 3 × 1,000,000 − 材料 3 × 100 × 1.0
        assert row["manufacturing_profit"] == 3_000_000.0 - 300.0
        assert row["market_value"] == 1_000_000.0 + 3_000_000.0 - 300.0
        assert row["price_diff"] == row["market_value"] - 10_000.0

    def test_auction_entry_cost_prefers_buyout(self, service):
        row = next(r for r in service.load_auction_contracts(10000002) if r["contract_id"] == 4)
        assert row["entry_kind"] == "buyout"
        assert row["entry_cost"] == 500.0

    def test_items_only_when_fetched(self, service):
        """`items_fetched_at` 为空 = 还没拉，不是「没有物品」—— 状态码要能区分。"""
        row = next(r for r in service.load_exchange_contracts(10000002) if r["contract_id"] == 3)
        assert row["status"] == cs.ca.STATUS_OK
        fetched = {r["contract_id"]: r for r in service.load_auction_contracts(10000002)}
        assert fetched[4]["status"] == cs.ca.STATUS_NO_ITEMS

    def test_content_column_fields(self, service):
        """「物品」列的三个字段：主物品名 / 图标候选 / 件数 —— 图标覆盖不全，名字是保底。"""
        row = next(r for r in service.load_exchange_contracts(10000002) if r["contract_id"] == 3)
        assert row["top_item_name"] == "渡鸦级蓝图"
        assert row["icon_type_ids"] == [1000]
        assert row["item_count"] == 1

    def test_issuer_name_attached_and_blank_when_unknown(self, service):
        """发布者名字来自 `contract_issuers`；查不到给空串（不是 id，也不是异常）。"""
        exchange = {r["contract_id"]: r for r in service.load_exchange_contracts(10000002)}
        assert exchange[3]["issuer_name"] == "张三"
        auction = {r["contract_id"]: r for r in service.load_auction_contracts(10000002)}
        assert auction[4]["issuer_name"] == ""


class TestIssuerLookup:
    """按发布者名字反查他的合同（三个页签共用同一套筛选）。"""

    def test_filters_by_issuer_name(self, service):
        rows = service.load_exchange_contracts(10000002, filters={"issuer": "张三"})
        assert [r["contract_id"] for r in rows] == [3]

    def test_partial_and_case_insensitive_match(self, service):
        """用户往往只记得名字的一部分 —— 子串匹配，不要求打全名。"""
        assert len(service.load_exchange_contracts(10000002, filters={"issuer": "张"})) == 1
        assert service.load_exchange_contracts(10000002, filters={"issuer": "李四"}) == []

    def test_counts_follow_the_same_filter(self, service):
        assert service.count_tab(10000002, "item_exchange", {"issuer": "张三"}) == 1
        assert service.count_tab(10000002, "auction", {"issuer": "张三"}) == 0


# ═══════════════════════════════════════════════════════
#  取价
# ═══════════════════════════════════════════════════════


class TestPriceFallback:
    def test_falls_back_to_jita_for_region_without_prices(self, service):
        """用户可手动输入任意星域 —— 那些星域没有 market_prices，不回落到 Jita 就整页无价"""
        prices = service.price_map_for([2000], 10000043, "sell")  # 多美：库里没价
        assert prices == {2000: 1_000_000.0}

    def test_region_price_wins_over_fallback(self, service):
        prices = service.price_map_for([2000], 10000002, "sell")
        assert prices == {2000: 1_000_000.0}

    def test_empty_input(self, service):
        assert service.price_map_for([], 10000002, "sell") == {}
