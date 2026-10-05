"""关注列表管理器测试 — watchlist_items CRUD / 价格变化检测

需要临时 ref + mkt + user 三库，watchlist_manager 使用 get_db() 全局单例。
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.database_manager import DB_PATH_MAP, get_db

# ── 最小数据集 ──

REF_SCHEMA = """
CREATE TABLE item (
    type_id INTEGER PRIMARY KEY,
    zh_name TEXT,
    en_name TEXT,
    volume REAL DEFAULT 1.0
);
INSERT INTO item VALUES (1001, '三钛合金', 'Tritanium', 0.01);
INSERT INTO item VALUES (2001, '渡鸦级', 'Raven', 50000);
INSERT INTO item VALUES (2002, '无人机', 'Drone', 5);
INSERT INTO item VALUES (3001, '未知蓝图', 'Unknown BP', 0.01);
"""

MKT_SCHEMA = """
CREATE TABLE market_prices (
    type_id INTEGER,
    region_id INTEGER,
    buy_price REAL,
    sell_price REAL,
    buy_volume INTEGER DEFAULT 0,
    sell_volume INTEGER DEFAULT 0,
    fetch_time TEXT
);
INSERT INTO market_prices VALUES (1001, 10000002, 4.0, 5.0, 10000000, 8000000, '2026-06-30 12:00:00');
INSERT INTO market_prices VALUES (2001, 10000002, 50000000, 55000000, 1000000, 800000, '2026-06-30 12:00:00');
INSERT INTO market_prices VALUES (2002, 10000002, 100000, 120000, 500000, 400000, '2026-06-30 12:00:00');
-- 有记录但卖价为 0：`added_price` 必须留 NULL，不能把 0 当「加入时卖 0 ISK」
INSERT INTO market_prices VALUES (2003, 10000002, 0.0, 0.0, 10, 10, '2026-06-30 12:00:00');
"""


@pytest.fixture
def temp_watchlist_db():
    """创建临时 ref + mkt + user 三库，使 watchlist_manager 可用"""
    tmpdir = tempfile.mkdtemp(prefix="eve_wl_")

    ref_path = Path(tmpdir) / "reference.db"
    mkt_path = Path(tmpdir) / "market.db"
    user_path = Path(tmpdir) / "user.db"

    for p in (ref_path, mkt_path, user_path):
        sqlite3.connect(str(p)).close()

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP.update(
        {
            "ref": str(ref_path),
            "mkt": str(mkt_path),
            "user": str(user_path),
        }
    )

    # 清空连接缓存使下次 connect 使用新路径
    mgr = get_db()
    mgr.close_all()

    # 初始化 ref 和 mkt 数据
    conn = sqlite3.connect(str(ref_path))
    conn.executescript(REF_SCHEMA)
    conn.close()

    conn = sqlite3.connect(str(mkt_path))
    conn.executescript(MKT_SCHEMA)
    conn.close()

    yield tmpdir

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    mgr.close_all()
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestWatchlistCRUD:
    """关注列表基础 CRUD"""

    def test_add_to_watchlist(self, temp_watchlist_db):
        """添加物品到关注列表"""
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db

        init_db()
        item_id = add_to_watchlist(1001, note="常用材料", buy_threshold=3.5)
        assert item_id > 0

        items = get_watchlist()
        ids = [i["type_id"] for i in items]
        assert 1001 in ids

    def test_add_duplicate_returns_existing_id(self, temp_watchlist_db):
        """重复添加同一物品应返回已有 id 而不创建重复记录"""
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db

        init_db()
        id1 = add_to_watchlist(1001)
        id2 = add_to_watchlist(1001)
        assert id1 == id2

        items = get_watchlist()
        matches = [i for i in items if i["type_id"] == 1001]
        assert len(matches) == 1  # 不重复

    def test_remove_from_watchlist(self, temp_watchlist_db):
        """删除关注物品"""
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db, remove_from_watchlist

        init_db()
        item_id = add_to_watchlist(1001)
        removed = remove_from_watchlist(item_id)
        assert removed is True

        items = get_watchlist()
        assert not any(i["type_id"] == 1001 for i in items)

    def test_remove_nonexistent_returns_false(self, temp_watchlist_db):
        """删除不存在的 id 返回 False"""
        from services.watchlist_manager import init_db, remove_from_watchlist

        init_db()
        result = remove_from_watchlist(99999)
        assert result is False

    def test_get_watchlist_returns_items_with_names(self, temp_watchlist_db):
        """获取关注列表，应 JOIN item 表包含中文名和英文名"""
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db

        init_db()
        add_to_watchlist(1001, note="材料")
        add_to_watchlist(2001, note="船")

        items = get_watchlist()
        assert len(items) >= 2

        item_map = {i["type_id"]: i for i in items}
        assert item_map[1001]["zh_name"] == "三钛合金"
        assert item_map[1001]["en_name"] == "Tritanium"
        assert item_map[2001]["zh_name"] == "渡鸦级"

    def test_empty_watchlist(self, temp_watchlist_db):
        """空关注列表返回空列表"""
        from services.watchlist_manager import get_watchlist, init_db

        init_db()
        items = get_watchlist()
        assert items == []


class TestWatchlistAddedPrice:
    """`added_price`：加入关注时记下 Jita 卖价。

    取不到价格（没记录 / 卖价为 0）一律留 NULL —— 0 会被读端当成「那时卖 0 ISK」，
    涨跌算成无穷大。
    """

    @pytest.mark.parametrize(
        ("type_id", "expected"),
        [(1001, 5.0), (3001, None), (2003, None)],
        ids=["有Jita卖价", "无价格记录", "卖价为0"],
    )
    def test_add_records_jita_sell_price(self, temp_watchlist_db, type_id, expected):
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db

        init_db()
        add_to_watchlist(type_id)

        item = next(i for i in get_watchlist() if i["type_id"] == type_id)
        assert item["added_price"] == expected


class TestWatchlistUpdate:
    """更新备注和阈值"""

    def test_update_note(self, temp_watchlist_db):
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db, update_watchlist_item

        init_db()
        item_id = add_to_watchlist(1001, note="旧备注")
        update_watchlist_item(item_id, note="新备注")

        items = get_watchlist()
        item = next(i for i in items if i["type_id"] == 1001)
        assert item["note"] == "新备注"

    def test_update_thresholds(self, temp_watchlist_db):
        from services.watchlist_manager import add_to_watchlist, get_watchlist, init_db, update_watchlist_item

        init_db()
        item_id = add_to_watchlist(1001)
        update_watchlist_item(item_id, buy_threshold=4.5, sell_threshold=5.5)

        items = get_watchlist()
        item = next(i for i in items if i["type_id"] == 1001)
        assert item["buy_threshold"] == 4.5
        assert item["sell_threshold"] == 5.5

    def test_update_no_changes_returns_false(self, temp_watchlist_db):
        from services.watchlist_manager import init_db, update_watchlist_item

        init_db()
        result = update_watchlist_item(1)
        assert result is False


class TestPriceChanges:
    """价格变化检测"""

    def test_check_price_changes_seeds_last_prices(self, temp_watchlist_db):
        """首次调用时 last_buy_price/last_sell_price 从 market_prices 填充"""
        from services.watchlist_manager import add_to_watchlist, check_price_changes, init_db

        init_db()
        add_to_watchlist(1001, note="材料")

        # 首次调用：old_buy 为 NULL，检测不到变化，但会更新快照价格
        changes = check_price_changes()
        assert changes == []

        # 验证快照价格已写入
        db = get_db()
        with db.connect("user") as conn:
            row = conn.execute(
                "SELECT last_buy_price, last_sell_price FROM watchlist_items WHERE type_id=?",
                (1001,),
            ).fetchone()
        assert row["last_buy_price"] == 4.0
        assert row["last_sell_price"] == 5.0

    def test_check_price_changes_detects_change(self, temp_watchlist_db):
        """市场价格变动后应检测到变化"""
        from services.watchlist_manager import add_to_watchlist, check_price_changes, init_db

        init_db()
        add_to_watchlist(1001, note="材料")

        # 第一次调用：填充 last prices
        check_price_changes()

        # 模拟市场价格变化
        mkt_path = DB_PATH_MAP["mkt"]
        conn = sqlite3.connect(mkt_path)
        conn.execute("UPDATE market_prices SET buy_price=3.0, sell_price=4.0 WHERE type_id=1001")
        conn.commit()
        conn.close()

        # 第二次调用：应检测到变化
        changes = check_price_changes()
        assert len(changes) >= 1
        c = next(x for x in changes if x["type_id"] == 1001)
        assert c["old_buy"] == 4.0
        assert c["new_buy"] == 3.0
        assert c["old_sell"] == 5.0
        assert c["new_sell"] == 4.0

    def test_check_price_changes_no_change(self, temp_watchlist_db):
        """价格未变化时返回空列表"""
        from services.watchlist_manager import (
            add_to_watchlist,
            check_price_changes,
            init_db,
        )

        init_db()
        add_to_watchlist(1001, note="材料")

        # 第一次调用：填充 last prices
        check_price_changes()

        # 第二次调用：价格未变 → 空列表
        changes = check_price_changes()
        assert changes == []

    def test_check_price_changes_updates_last_price(self, temp_watchlist_db):
        """check_price_changes 应更新 last_buy_price / last_sell_price"""
        from services.watchlist_manager import (
            add_to_watchlist,
            check_price_changes,
            init_db,
        )

        init_db()
        add_to_watchlist(1001, note="材料")

        check_price_changes()

        db = get_db()
        with db.connect("user") as conn:
            row = conn.execute(
                "SELECT last_buy_price, last_sell_price FROM watchlist_items WHERE type_id = ?",
                (1001,),
            ).fetchone()
        assert row is not None
        assert row["last_buy_price"] == 4.0
        assert row["last_sell_price"] == 5.0


class TestWatchlistUpdateNotePreservesOtherFields:
    """更新备注不改变其他字段"""

    def test_update_note_preserves_thresholds(self, temp_watchlist_db):
        """只更新备注，buy_threshold / sell_threshold 应保持不变"""
        from services.watchlist_manager import (
            add_to_watchlist,
            get_watchlist,
            init_db,
            update_watchlist_item,
        )

        init_db()
        item_id = add_to_watchlist(1001, note="原始备注", buy_threshold=3.0, sell_threshold=6.0)

        # 只更新备注
        update_watchlist_item(item_id, note="新备注")

        items = get_watchlist()
        item = next(i for i in items if i["type_id"] == 1001)
        assert item["note"] == "新备注"
        assert item["buy_threshold"] == 3.0  # 未改变
        assert item["sell_threshold"] == 6.0  # 未改变

    def test_update_note_preserves_type_id_and_region(self, temp_watchlist_db):
        """只更新备注，type_id / region_id 应保持不变"""
        from services.watchlist_manager import (
            add_to_watchlist,
            get_watchlist,
            init_db,
            update_watchlist_item,
        )

        init_db()
        item_id = add_to_watchlist(2001, note="船", buy_threshold=4e7)

        update_watchlist_item(item_id, note="主力战列舰")

        items = get_watchlist()
        item = next(i for i in items if i["type_id"] == 2001)
        assert item["note"] == "主力战列舰"
        assert item["type_id"] == 2001  # 未改变
        assert item["region_id"] == 10000002  # 未改变
        assert item["zh_name"] == "渡鸦级"  # 未改变

    def test_update_note_without_prior_thresholds(self, temp_watchlist_db):
        """未设阈值时更新备注，其他字段应保持 NULL"""
        from services.watchlist_manager import (
            add_to_watchlist,
            get_watchlist,
            init_db,
            update_watchlist_item,
        )

        init_db()
        item_id = add_to_watchlist(3001, note="蓝图")

        update_watchlist_item(item_id, note="未知蓝图 - 已关注")

        items = get_watchlist()
        item = next(i for i in items if i["type_id"] == 3001)
        assert item["note"] == "未知蓝图 - 已关注"
        assert item["buy_threshold"] is None  # 未改变
        assert item["sell_threshold"] is None  # 未改变

    def test_consecutive_note_updates(self, temp_watchlist_db):
        """连续两次更新备注，阈值始终不变"""
        from services.watchlist_manager import (
            add_to_watchlist,
            get_watchlist,
            init_db,
            update_watchlist_item,
        )

        init_db()
        item_id = add_to_watchlist(1001, note="v1", buy_threshold=3.5)

        update_watchlist_item(item_id, note="v2")
        update_watchlist_item(item_id, note="v3")

        items = get_watchlist()
        item = next(i for i in items if i["type_id"] == 1001)
        assert item["note"] == "v3"
        assert item["buy_threshold"] == 3.5  # 始终不变


# ── schema 迁移回归：旧 user.db → added_price ──


def _create_user_v21_watchlist(db_path):
    """构造 v21 的 `watchlist_items`（还没有 `added_price` 列），并放一行老关注。"""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE watchlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_id INTEGER NOT NULL,
            region_id INTEGER NOT NULL DEFAULT 10000002,
            note TEXT,
            price_threshold_buy REAL,
            price_threshold_sell REAL,
            last_buy_price REAL,
            last_sell_price REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        INSERT INTO watchlist_items (type_id, region_id, note) VALUES (1001, 10000002, '老关注');
    """)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist_items)")}
    assert "added_price" not in cols, "夹具应模拟还没有该列的老库"
    conn.execute("PRAGMA user_version = 21")
    conn.commit()
    conn.close()


def test_user_v21_to_v22_adds_added_price_keeping_rows_null(tmp_path, monkeypatch):
    """user v21→v22：`watchlist_items` 加 `added_price`，**已有行留 NULL**。

    老行加入时的价格过去没记过、编不出来；给 0 会让读端以为「那时卖 0 ISK」。
    迁移跑一半会毁用户数据，所以盯：列真加上、老行原样在、版本号推到最新、可重入。
    """
    from services import schema_migrations as sm

    db_path = tmp_path / "user.db"
    monkeypatch.setitem(sm._DB_PATH_MAP, "user", str(db_path))
    _create_user_v21_watchlist(db_path)

    result = sm.ensure_schema("user")

    assert result["after"] == sm.DB_SCHEMA_VERSIONS["user"]
    assert any("added_price" in s for s in result["applied"]), "应执行 v21→v22 加列迁移"
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(watchlist_items)")}
        rows = conn.execute("SELECT type_id, note, added_price FROM watchlist_items").fetchall()
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
    assert "added_price" in cols
    assert rows == [(1001, "老关注", None)], "老行必须原样保留，added_price 为 NULL（不是 0）"
    assert version == sm.DB_SCHEMA_VERSIONS["user"]

    # 幂等：已到最新版的库不再有任何动作
    assert sm.ensure_schema("user")["applied"] == []
