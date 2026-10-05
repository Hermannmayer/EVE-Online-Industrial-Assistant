"""传导链测试 — `services.market_chain_service.get_transmission_chain`。

蓝图结构（900 是产物，其余是材料）：

    900 ← [100×2, 200×1, 700×1]
    100 ← [300×4, 400×1]
    200 ← [300×3]          # 300 出现在两条支路 → DAG
    700 ← [800×1]
    300/400/800 无蓝图

价格：900/100/200/400/700 走 `price_history`（成交均价），300 只有
`market_volume_snapshots`（挂单价 → source="snapshot"），800 两边都没有 → None。
"""

from datetime import date, timedelta

import pytest

from services.market_chain_service import get_transmission_chain
from services.price_history import PRICE_HISTORY_DDL

REGION = 10000002
ROOT = 900

#: 蓝图 → (产物, [(材料, 用量)])
_BLUEPRINTS = {
    9010: (900, [(100, 2), (200, 1), (700, 1)]),
    9011: (100, [(300, 4), (400, 1)]),
    9012: (200, [(300, 3)]),
    9013: (700, [(800, 1)]),
}

#: type_id → (近 30 天成交均价, 前 30 天成交均价) —— 涨跌幅一目了然
_HISTORY = {900: (110.0, 100.0), 100: (60.0, 50.0), 200: (25.0, 20.0), 400: (5.0, 4.0), 700: (50.0, 40.0)}

#: 只有挂单价的材料 → (近 30 天挂单卖价, 前 30 天挂单卖价)
_SNAPSHOT = {300: (11.0, 10.0)}


class _NoPricing:
    """`expand_bom` 会调定价服务；本服务自己取价，这里给个不返回价格的替身。"""

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None:
        return None


def _day(offset: int) -> str:
    return (date.today() - timedelta(days=offset)).isoformat()


@pytest.fixture
def chain_db(temp_db, monkeypatch):
    """BOM 展开走 `expand_bom`（它自己从容器取库），所以这里同时 patch 它的两个默认依赖。"""
    monkeypatch.setattr("services.bom_expander._default_db", lambda: temp_db)
    monkeypatch.setattr("services.bom_expander._default_pricing", lambda: _NoPricing())

    with temp_db.connect("mkt", "ref", "bp") as conn:
        for type_id in (900, 100, 200, 300, 400, 700, 800):
            conn.execute(
                "INSERT INTO item (type_id, zh_name, en_name) VALUES (?, ?, ?)",
                (type_id, f"物品{type_id}", f"Item{type_id}"),
            )
        for blueprint_id, (product_id, materials) in _BLUEPRINTS.items():
            conn.execute("INSERT INTO blueprint_activities VALUES (?, 'manufacturing', 60)", (blueprint_id,))
            conn.execute("INSERT INTO blueprint_products VALUES (?, 'manufacturing', ?, 1)", (blueprint_id, product_id))
            for material_id, quantity in materials:
                conn.execute(
                    "INSERT INTO blueprint_materials VALUES (?, 'manufacturing', ?, ?, 10)",
                    (blueprint_id, material_id, quantity),
                )
        conn.execute(PRICE_HISTORY_DDL)
        for type_id, (recent, previous) in _HISTORY.items():
            for offset in range(60):
                average = recent if offset < 30 else previous
                conn.execute(
                    "INSERT INTO price_history (type_id, region_id, date, average, highest, lowest, "
                    "volume, order_count, fetched_at) VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?)",
                    (type_id, REGION, _day(offset), average, average, average, "2026-01-01T00:00:00+00:00"),
                )
        for type_id, (recent, previous) in _SNAPSHOT.items():
            for offset in range(60):
                sell = recent if offset < 30 else previous
                conn.execute(
                    "INSERT INTO market_volume_snapshots (type_id, region_id, date, buy_price, sell_price, "
                    "buy_volume, sell_volume) VALUES (?, ?, ?, 0, ?, 0, 100)",
                    (type_id, REGION, _day(offset), sell),
                )
    return temp_db


def test_levels_qty_and_cost_share(chain_db):
    """逐级展开：level 从 1 起、qty 取蓝图原始用量、cost_share = qty×价 ÷ 父项材料成本。"""
    rows = get_transmission_chain(ROOT, depth=2, _db=chain_db)
    assert [r["level"] for r in rows] == sorted(r["level"] for r in rows)
    assert [r["typeId"] for r in rows] == [100, 200, 700, 300, 400, 800]
    by_id = {r["typeId"]: r for r in rows}
    # 父项成本 = 2×60 + 1×25 + 1×50 = 195（同级 cost_share 之和为 1）
    assert (by_id[100]["parent_type_id"], by_id[100]["qty"], by_id[100]["price"]) == (900, 2.0, 60.0)
    assert by_id[100]["cost_share"] == pytest.approx(120 / 195, abs=1e-4)
    assert by_id[200]["cost_share"] == pytest.approx(25 / 195, abs=1e-4)
    assert by_id[700]["cost_share"] == pytest.approx(50 / 195, abs=1e-4)
    # level 2：父项 100 的成本 = 4×11 + 1×5 = 49
    assert (by_id[400]["parent_type_id"], by_id[400]["qty"]) == (100, 1.0)
    assert by_id[400]["cost_share"] == pytest.approx(5 / 49, abs=1e-4)
    assert sum(by_id[t]["cost_share"] for t in (100, 200, 700)) == pytest.approx(1.0)
    assert [r["name"] for r in rows] == [f"物品{t}" for t in (100, 200, 700, 300, 400, 800)]


def test_dag_merge_keeps_one_row_and_counts_occurrences(chain_db):
    """300 出现在 100 / 200 两条支路 → 只出一行，`occurs=2`，展示最浅最靠前的那次出现。"""
    rows = get_transmission_chain(ROOT, depth=2, _db=chain_db)
    assert sum(1 for r in rows if r["typeId"] == 300) == 1
    row = next(r for r in rows if r["typeId"] == 300)
    assert (row["level"], row["parent_type_id"], row["qty"], row["occurs"]) == (2, 100, 4.0, 2)
    assert row["source"] == "snapshot"  # 没有成交历史 → 明确标成挂单价口径
    assert (row["price"], row["chg30"]) == (11.0, pytest.approx(10.0))
    assert row["chg180"] is None  # 挂单快照只有 60 天
    assert row["not_caught_up"] == pytest.approx(20 - (4 * 11 * 10 + 5 * 25) / 49, abs=1e-2)


def test_not_caught_up_and_none_when_price_missing(chain_db):
    """未跟涨度 = 父涨幅 − Σ(cost_share×子涨幅)；缺价 → cost_share/not_caught_up 都给 None。"""
    by_id = {r["typeId"]: r for r in get_transmission_chain(ROOT, depth=2, _db=chain_db)}
    expected = 10.0 - (120 / 195 * 20.0 + 25 / 195 * 25.0 + 50 / 195 * 25.0)
    assert by_id[100]["not_caught_up"] == pytest.approx(expected, abs=1e-2)
    assert by_id[200]["not_caught_up"] == pytest.approx(expected, abs=1e-2)
    assert by_id[700]["not_caught_up"] == pytest.approx(expected, abs=1e-2)
    assert by_id[400]["source"] == "history"
    assert by_id[400]["chg90"] is None  # 只有 60 天成交历史
    assert (by_id[800]["price"], by_id[800]["source"]) == (None, None)
    assert by_id[800]["cost_share"] is None
    assert by_id[800]["not_caught_up"] is None
    assert by_id[800]["chg30"] is None


def test_depth_limits_levels_and_unknown_root_is_empty(chain_db):
    """`depth` 控制层数（默认 2）；没有蓝图的 type 展开成空链。"""
    rows = get_transmission_chain(ROOT, depth=1, _db=chain_db)
    assert [r["typeId"] for r in rows] == [100, 200, 700]
    assert all(r["level"] == 1 for r in rows)
    assert get_transmission_chain(9999, depth=2, _db=chain_db) == []
