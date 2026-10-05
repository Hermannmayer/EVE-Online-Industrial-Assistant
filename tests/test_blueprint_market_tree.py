"""可制造物品分类树 —— 反应产物并入 + 产物 → 分类映射（WP2 回归）。"""

import pytest

from services.repositories.blueprint_repository import BlueprintRepository


def test_market_tree_includes_reaction_product_group(temp_db):
    """回归：反应产物所在分类必须出现在 `get_manufacturable_market_tree()` 里。

    缺陷背景：递归 CTE 只认 `activity='manufacturing'`，反应产物（真库 111 个）的
    分类一个都进不了树 —— 「类别 = 反应」下整棵树 988/988 个节点全空。真库实测
    988 → 994 行，新增的 6 个节点全在「制造和研究 → 材料 → 反应材料」下。

    夹具里制造树 = {100（渡鸦级）, 4, 9（无人机）}；`贸易货物`（19）只挂着矿物，
    没有任何制造蓝图产物，所以修复前 19 不在结果里 —— 往里塞一个反应产物后必须出现。
    """
    repo = BlueprintRepository(temp_db)
    before = {r["id"] for r in repo.get_manufacturable_market_tree()}
    assert 19 not in before, "夹具前提：贸易货物本不在制造树里"

    with temp_db.connect("bp") as conn:
        conn.execute("INSERT INTO blueprint_products VALUES (4001, 'reaction', 1001, 1)")

    rows = repo.get_manufacturable_market_tree()
    assert {r["id"] for r in rows} == before | {19}
    assert {"id", "p", "n"} == set(rows[0])
    node = next(r for r in rows if r["id"] == 19)
    assert (node["p"], node["n"]) == (None, "贸易货物")


def test_product_market_groups_skips_empty_unknown_and_null_group(temp_db):
    """产物 → 分类映射：空输入 `{}`；查不到 / `market_group_id` 为 NULL 的产物跳过。"""
    repo = BlueprintRepository(temp_db)
    assert repo.get_product_market_groups([]) == {}

    with temp_db.connect("ref") as conn:
        conn.execute("INSERT INTO item (type_id, zh_name, market_group_id) VALUES (9999, '无分类物品', NULL)")

    assert repo.get_product_market_groups([2001, 9999, 123456]) == {2001: 100}


@pytest.mark.parametrize(
    ("product_type_id", "expected"),
    [
        (2001, "渡鸦级蓝图"),  # 有制造蓝图 + 蓝图物品有名字
        (2002, None),  # 蓝图 3002 在 item 里没有名字行 → None
        (99999, None),  # 没有制造/反应蓝图 → None
    ],
)
def test_manufacturing_blueprint_name(temp_db, product_type_id, expected):
    """产物 → 制造蓝图中文名：无蓝图、蓝图物品无名都回退 `None`。"""
    with temp_db.connect("ref") as conn:
        conn.execute(
            "INSERT INTO item (type_id, zh_name, en_name, market_group_id)"
            " VALUES (3001, '渡鸦级蓝图', 'Raven Blueprint', NULL)"
        )

    assert BlueprintRepository(temp_db).get_manufacturing_blueprint_name(product_type_id) == expected
