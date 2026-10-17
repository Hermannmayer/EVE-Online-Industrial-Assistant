"""`services.repositories.item_repository` 测试（05-7）：名称 / 搜索 / 市场分类 SQL；用临时 ref 库。"""

from __future__ import annotations

import pytest

from services.repositories.item_repository import ItemRepository

pytestmark = pytest.mark.fast


@pytest.fixture
def repo(db_manager) -> ItemRepository:
    with db_manager.connect("ref") as conn:
        conn.executescript(
            """
            CREATE TABLE item (type_id INTEGER PRIMARY KEY, zh_name TEXT, en_name TEXT, volume REAL,
                               group_id INTEGER, market_group_id INTEGER);
            CREATE TABLE market_tree (market_group_id INTEGER PRIMARY KEY, parent_group_id INTEGER,
                                      zh_name TEXT, en_name TEXT);
            INSERT INTO item VALUES
                (101,'渡鸦级','Raven',1.0,25,9001), (102,'渡鸦级海军型','Raven Navy Issue',2.5,25,9003),
                (103,'乌鸦级','Caldari Raven',1.0,25,9004), (104,NULL,'Basilisk',1.0,25,9002),
                (105,'行星指挥中心','Planetary Command Center',1.0,46,9101);
            INSERT INTO market_tree VALUES
                (9001,NULL,'舰船','Ships'), (9002,NULL,'装备','Modules'), (9003,9001,'战列舰','Battleships'),
                (9004,9003,'海军型','Navy Issue'), (9100,NULL,'行星开发','Planetary Industry'),
                (9101,9100,'指挥中心','Command Centers');
            """
        )
    return ItemRepository(db_manager)


def test_names_search_and_volume(repo):
    assert repo.get_by_id(101)["zh_name"] == "渡鸦级"
    assert repo.get_by_name("Raven")["type_id"] == 101
    assert repo.get_name(104) == "Basilisk"  # zh_name 为 NULL → 英文
    assert repo.get_name(999999) == "999999"  # 查不到 → 字符串 id
    assert repo.get_volume(102) == 2.5 and repo.get_volume(999999) == 1.0  # 缺省 1.0
    # 'Raven' 前缀命中 101/102（按 en_name 长度排序），包含命中 103 排最后
    assert [r["type_id"] for r in repo.search_by_name("Raven")] == [101, 102, 103]
    assert [r["type_id"] for r in repo.search_by_name("Raven", limit=2)] == [101, 102]


def test_market_tree_queries(repo):
    got = repo.get_root_market_categories()
    assert set(got) == {(9001, "舰船"), (9002, "装备"), (9100, "行星开发")}
    assert [name for _gid, name in got] == sorted(name for _gid, name in got)
    assert repo.get_market_descendants(9001) == {101, 102, 103}  # 递归 9001→9003→9004
    assert repo.get_market_descendants(999999) == set()
    assert repo.get_planetary_product_ids() == {105}
    assert repo.count() == 5
