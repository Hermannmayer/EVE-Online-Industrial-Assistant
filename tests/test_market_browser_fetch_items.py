"""`fetch_items` 的 `manufacturable_only` 下推 —— LIMIT 先截断再过滤的丢物品回归。

真库现象：「舰船装备」子树共 3203 个物品（含大量不可制造的弹药/晶体），
`LIMIT 2000` 先截断、再在客户端按类别过滤 → 真实 1265 个可制造物品只显示 792 个。
这里用一个小库 + 调小 `_LIMIT` 复现同一根因：截断发生在过滤**之前**。
"""

from __future__ import annotations

import pytest

from services import market_browser_service as mbs

JITA = 10000002
#: 「贸易货物」——夹具里 group 19 只挂矿物，正好当一棵纯物品分类树用
GROUP_ID = 19


@pytest.fixture
def svc(temp_db, monkeypatch):
    """把服务模块的 `get_container` 指向临时库管理器。"""
    stub = type("C", (), {"db": temp_db})()
    monkeypatch.setattr(mbs, "get_container", lambda: stub)
    return temp_db


def _seed(db) -> set[int]:
    """造 5 个不可制造 + 3 个可制造（制造 2 / 反应 1）物品，返回蓝图产物 id 集合。

    名字前缀决定 `ORDER BY i.zh_name` 的顺序：`a*` 全排在 `z*` 前面，
    所以调小 LIMIT 后先被切掉的正是那 5 个不可制造的。
    """
    items = [(8000 + i, f"a{i}", f"NonMfg{i}", 1.0, GROUP_ID) for i in range(1, 6)]
    items += [(9000 + i, f"z{i}", f"Mfg{i}", 1.0, GROUP_ID) for i in range(1, 4)]
    with db.connect("ref") as conn:
        conn.executemany(
            "INSERT INTO item (type_id, zh_name, en_name, volume, market_group_id) VALUES (?,?,?,?,?)",
            items,
        )
    with db.connect("bp") as conn:
        conn.execute("INSERT INTO blueprint_products VALUES (5001, 'manufacturing', 9001, 1)")
        conn.execute("INSERT INTO blueprint_products VALUES (5002, 'manufacturing', 9002, 1)")
        conn.execute("INSERT INTO blueprint_products VALUES (5003, 'reaction', 9003, 1)")
        return {r[0] for r in conn.execute("SELECT DISTINCT product_type_id FROM blueprint_products")}


def test_manufacturable_only_does_not_let_limit_drop_products(svc, monkeypatch):
    """`manufacturable_only=True` 时，行全有制造/反应产物，且不再被 LIMIT 截掉。

    用 `monkeypatch` 把 `_LIMIT` 调成 4（真库是 2000）：默认路径返回 a1..a4 —— 8 个物品里
    的 3 个可制造全在截断之外，客户端过滤后一行不剩（这就是丢 473 个的同一根因）；
    下推路径只取可制造行，3 个全在，且 3 < 4 说明没有触顶。
    """
    products = _seed(svc)
    monkeypatch.setattr(mbs, "_LIMIT", " ORDER BY i.zh_name LIMIT 4")

    truncated = mbs.fetch_items([GROUP_ID], JITA)
    assert [r["z"] for r in truncated] == ["a1", "a2", "a3", "a4"]
    assert {r["id"] for r in truncated} & products == set(), "截断后客户端过滤一个可制造物品都不剩"

    rows = mbs.fetch_items([GROUP_ID], JITA, True)
    assert [r["z"] for r in rows] == ["z1", "z2", "z3"]
    assert {r["id"] for r in rows} <= products
