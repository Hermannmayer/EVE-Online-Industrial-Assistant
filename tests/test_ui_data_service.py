"""`services/ui_data_service.py` 查询页搜索的口径测试。

只覆盖**查询页搜索的两条入口**（`query_search_items` / `query_search_items_basic`）。
这里的重点是**匹配口径**：只做 Type ID 全等或名字前缀，不做子串、不做整类别展开。
"""

from __future__ import annotations

import pytest

from services.ui_data_service import query_search_items, query_search_items_basic, query_suggest_items

pytestmark = pytest.mark.fast


def _build(db_manager) -> None:
    """在临时库里造最小的 item / market_prices，只够跑通两条 SQL。"""
    with db_manager.connect("ref", "mkt") as conn:
        conn.execute(
            "CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT,"
            " en_group_name TEXT, zh_group_name TEXT, volume REAL, group_id INTEGER, category_id INTEGER)"
        )
        conn.execute(
            "CREATE TABLE mkt.market_prices (type_id INTEGER, region_id INTEGER, buy_price REAL,"
            " sell_price REAL, buy_volume INTEGER, sell_volume INTEGER, fetch_time TEXT)"
        )
        # ① 名字以 gila 开头 → 应当命中
        # ② 蓝图，同样以 Gila 开头（大小写不同）→ 应当命中
        # ③ 与 ① 同类别的另一艘船：名字里**没有** gila，但**类别名里有**。
        #    旧实现的「查询串命中类别名 → 返回整个类别」会把它带出来，正是用户投诉的那条。
        # ④ 名字中段含 Gila → 前缀匹配下不该命中（旧的子串匹配会命中）
        # ⑤ 无用类别（category_id=11）里的同名条目 → 必须被排除。
        #    真实库里这一类有 6857 条、0 条有价、0 条有蓝图，还是「候选里两条一模一样的
        #    `♦ 毒蜥级`」的来源（同一艘船重复发布）。
        conn.executemany(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (17715, "毒蜥级", "Gila", "Gila 级舰船", "毒蜥级舰船", 101000.0, 10, 6),
                (17716, "毒蜥级蓝图", "Gila Blueprint", "蓝图", "蓝图", 0.01, 20, 9),
                (17922, "警惕级", "Vigilant", "Gila 级舰船", "毒蜥级舰船", 118000.0, 10, 6),
                (17923, "某某的毒蜥级", "Someone's Gila", "Gila 级舰船", "毒蜥级舰船", 1.0, 11, 6),
                (43624, "♦ 毒蜥级", "♦ Gila", "♦ 巡洋舰", "♦ 巡洋舰", 101000.0, 1813, 11),
                (46056, "♦ 毒蜥级", "♦ Gila", "♦ 巡洋舰", "♦ 巡洋舰", 101000.0, 1813, 11),
            ],
        )


def _names(rows: list) -> set[str]:
    """行 → 英文名集合（第 3 列；中文名留空时也认英文）。"""
    return {str(r[2] or r[1]) for r in rows}


def test_search_matches_name_prefix_only(db_manager):
    """`gila` 只出名字以它开头的物品：不出同类别里的 Vigilant，也不出名字中段含它的。"""
    _build(db_manager)
    assert _names(query_search_items("gila", db=db_manager)) == {"Gila", "Gila Blueprint"}


def test_search_does_not_expand_to_the_whole_group(db_manager):
    """守住「命中类别名 → 返回整个类别」的删除。

    上面的样例里 `Vigilant` 与 `Gila` 同组、组的名字（`Gila 级舰船`）含查询串；
    旧实现会因此把这艘无名的船一起返回。
    """
    _build(db_manager)
    assert "Vigilant" not in _names(query_search_items("gila", db=db_manager))


def test_search_by_type_id_is_exact(db_manager):
    """纯数字按 Type ID 精确匹配（前缀分支不该把别的 ID 带出来）。"""
    _build(db_manager)
    assert _names(query_search_items("17715", db=db_manager)) == {"Gila"}


def test_chinese_query_matches_chinese_name_prefix(db_manager):
    """中文同样按前缀：`毒蜥级` 命中「毒蜥级」「毒蜥级蓝图」，不命中「某某的毒蜥级」。"""
    _build(db_manager)
    rows = query_search_items("毒蜥级", db=db_manager)
    assert _names(rows) == {"Gila", "Gila Blueprint"}


def test_basic_fallback_uses_the_same_prefix_rule(db_manager):
    """降级路径（只查 reference.item）口径必须与主路径一致，否则主路径一失败就换了行为。"""
    _build(db_manager)
    assert _names(query_search_items_basic("gila", db=db_manager)) == {"Gila", "Gila Blueprint"}
    assert "Vigilant" not in _names(query_search_items_basic("gila", db=db_manager))


def test_junk_category_is_excluded_from_search_and_suggest(db_manager):
    """无用类别（`category_id=11`）不出现在搜索结果与候选里。

    回归背景：用户看到候选里冒出**两条一模一样的「♦ 毒蜥级」** —— 同一艘船在 SDE 里以
    这个遗留类别重复发布（真实库里 6857 条、0 条有市场价、0 条有蓝图）。
    """
    _build(db_manager)

    assert _names(query_search_items("♦", db=db_manager)) == set()
    assert [r for r in query_suggest_items("毒蜥级", db=db_manager) if "♦" in str(r[1] or "")] == []
    # 降级路径同样要排
    assert [r for r in query_search_items_basic("♦", db=db_manager) if "♦" in str(r[1] or "")] == []
    # 正常条目不受影响
    assert "Gila" in _names(query_search_items("毒蜥级", db=db_manager))


def test_suggest_is_not_truncated(db_manager):
    """候选不再被 `LIMIT 10` 截断 —— 候选列表是用户唯一的匹配清单，截断就是「有却选不到」。"""
    _build(db_manager)
    with db_manager.connect("ref") as conn:
        conn.executemany(
            "INSERT INTO item VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(90000 + i, f"测试物{i}", f"TestItem{i}", "组", "组", 1.0, 99, 7) for i in range(25)],
        )
    assert len(query_suggest_items("测试物", db=db_manager)) == 25, "25 条前缀匹配必须全部返回（原先截成 10）"
