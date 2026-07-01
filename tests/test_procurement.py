"""代采购管理测试 — procurement_items CRUD

直接在临时 user.db 上测试 INSERT / UPDATE / DELETE 逻辑。
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.database_manager import DB_PATH_MAP, DatabaseManager

PROCUREMENT_SCHEMA = """CREATE TABLE IF NOT EXISTS procurement_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_id INTEGER NOT NULL,
    item_name TEXT,
    quantity INTEGER DEFAULT 1,
    hub TEXT DEFAULT 'Jita',
    priority TEXT DEFAULT 'normal',
    status TEXT DEFAULT 'pending',
    notes TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    ordered_at TEXT,
    received_at TEXT
);
"""


@pytest.fixture
def temp_user_db():
    """创建临时 user.db 含 procurement_items 表"""
    tmpdir = tempfile.mkdtemp(prefix="eve_proc_")
    user_path = Path(tmpdir) / "user.db"

    conn = sqlite3.connect(str(user_path))
    conn.executescript(PROCUREMENT_SCHEMA)
    conn.commit()
    conn.close()

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP["user"] = str(user_path)

    db = DatabaseManager()
    yield db

    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    shutil.rmtree(tmpdir, ignore_errors=True)


class TestProcurementCrud:
    """代采购条目 CRUD 测试"""

    def test_insert_item(self, temp_user_db):
        """INSERT 一条记录，然后回读验证字段"""
        with temp_user_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name, quantity, hub, priority, status, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (2001, "渡鸦级", 2, "Jita", "urgent", "pending", "造船订单"),
            )
        # 回读
        with temp_user_db.connect("user") as conn:
            row = conn.execute("SELECT * FROM procurement_items WHERE type_id = ?", (2001,)).fetchone()
        assert row is not None
        assert row["type_id"] == 2001
        assert row["item_name"] == "渡鸦级"
        assert row["quantity"] == 2
        assert row["hub"] == "Jita"
        assert row["priority"] == "urgent"
        assert row["status"] == "pending"
        assert row["notes"] == "造船订单"

    def test_insert_multiple_items(self, temp_user_db):
        """插入多条记录应全部存在"""
        items = [
            (2001, "渡鸦级", 1, "Jita", "normal", "pending", ""),
            (1001, "三钛合金", 50000, "Jita", "high", "ordered", "补货"),
            (2002, "无人机", 50, "Amarr", "low", "received", "已到货"),
        ]
        with temp_user_db.connect("user") as conn:
            for item in items:
                conn.execute(
                    "INSERT INTO procurement_items (type_id, item_name, quantity, hub, priority, status, notes) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    item,
                )
        with temp_user_db.connect("user") as conn:
            rows = conn.execute("SELECT * FROM procurement_items ORDER BY id").fetchall()
        assert len(rows) == 3
        assert rows[1]["item_name"] == "三钛合金"
        assert rows[1]["status"] == "ordered"

    def test_update_status(self, temp_user_db):
        """更新状态后读取验证"""
        with temp_user_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name, quantity, status) VALUES (?, ?, ?, ?)",
                (2001, "渡鸦级", 1, "pending"),
            )
            row = conn.execute("SELECT id FROM procurement_items WHERE type_id=2001").fetchone()
            item_id = row["id"]
            conn.execute("UPDATE procurement_items SET status = ? WHERE id = ?", ("ordered", item_id))
        with temp_user_db.connect("user") as conn:
            row = conn.execute("SELECT status FROM procurement_items WHERE id = ?", (item_id,)).fetchone()
        assert row["status"] == "ordered"

    def test_update_status_chain(self, temp_user_db):
        """状态链: pending → ordered → received"""
        with temp_user_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name, status) VALUES (?, ?, ?)",
                (2001, "渡鸦级", "pending"),
            )
            item_id = conn.execute("SELECT id FROM procurement_items WHERE type_id=2001").fetchone()["id"]
            conn.execute("UPDATE procurement_items SET status = ? WHERE id = ?", ("ordered", item_id))
            conn.execute("UPDATE procurement_items SET status = ? WHERE id = ?", ("received", item_id))
        with temp_user_db.connect("user") as conn:
            row = conn.execute("SELECT status FROM procurement_items WHERE id = ?", (item_id,)).fetchone()
        assert row["status"] == "received"

    def test_delete_item(self, temp_user_db):
        """删除后记录数归零"""
        with temp_user_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name) VALUES (?, ?)",
                (2001, "渡鸦级"),
            )
            item_id = conn.execute("SELECT id FROM procurement_items WHERE type_id=2001").fetchone()["id"]
            conn.execute("DELETE FROM procurement_items WHERE id = ?", (item_id,))
        with temp_user_db.connect("user") as conn:
            count = conn.execute("SELECT COUNT(*) FROM procurement_items").fetchone()[0]
        assert count == 0

    def test_delete_one_keeps_others(self, temp_user_db):
        """删除其中一条，其他记录不受影响"""
        with temp_user_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name) VALUES (?, ?)",
                (2001, "渡鸦级"),
            )
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name) VALUES (?, ?)",
                (2002, "无人机"),
            )
            item_id = conn.execute("SELECT id FROM procurement_items WHERE type_id=2001").fetchone()["id"]
            conn.execute("DELETE FROM procurement_items WHERE id = ?", (item_id,))
        with temp_user_db.connect("user") as conn:
            rows = conn.execute("SELECT * FROM procurement_items").fetchall()
        assert len(rows) == 1
        assert rows[0]["item_name"] == "无人机"

    def test_insert_with_defaults(self, temp_user_db):
        """验证 DEFAULT 值"""
        with temp_user_db.connect("user") as conn:
            conn.execute(
                "INSERT INTO procurement_items (type_id, item_name) VALUES (?, ?)",
                (2001, "渡鸦级"),
            )
        with temp_user_db.connect("user") as conn:
            row = conn.execute("SELECT * FROM procurement_items WHERE type_id=2001").fetchone()
        assert row["hub"] == "Jita"
        assert row["priority"] == "normal"
        assert row["status"] == "pending"
        assert row["notes"] == ""
        assert row["quantity"] == 1

    def test_query_by_status(self, temp_user_db):
        """按状态筛选查询"""
        stmt = "INSERT INTO procurement_items (type_id, item_name, status) VALUES (?, ?, ?)"
        with temp_user_db.connect("user") as conn:
            conn.execute(stmt, (2001, "渡鸦级", "pending"))
            conn.execute(stmt, (2002, "无人机", "ordered"))
            conn.execute(stmt, (1001, "三钛合金", "received"))

        with temp_user_db.connect("user") as conn:
            pending = conn.execute("SELECT COUNT(*) FROM procurement_items WHERE status='pending'").fetchone()[0]
            ordered = conn.execute("SELECT COUNT(*) FROM procurement_items WHERE status='ordered'").fetchone()[0]
            received = conn.execute("SELECT COUNT(*) FROM procurement_items WHERE status='received'").fetchone()[0]
        assert pending == 1
        assert ordered == 1
        assert received == 1


class TestProcurementBatchAndFilter:
    """批量插入与按优先级筛选"""

    BATCH_ITEMS = [
        (2010, "巨鸟级", 1, "Jita", "urgent", "pending", "急造旗舰"),
        (2011, "探索者级", 3, "Amarr", "low", "pending", "探险用"),
        (2012, "狂怒者级", 2, "Hek", "high", "ordered", "PVP舰队"),
        (2013, "弯刀级", 1, "Jita", "normal", "received", "已到货"),
        (2014, "猎豹级", 2, "Rens", "urgent", "pending", "急需"),
        (2015, "净化级", 5, "Dodixie", "high", "ordered", "舰队配置"),
    ]

    stmt = (
        "INSERT INTO procurement_items "
        "(type_id, item_name, quantity, hub, priority, status, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )

    def test_batch_insert_all(self, temp_user_db):
        """批量插入 6 条记录，验证全部写入"""
        with temp_user_db.connect("user") as conn:
            for item in self.BATCH_ITEMS:
                conn.execute(self.stmt, item)
        with temp_user_db.connect("user") as conn:
            rows = conn.execute(
                "SELECT type_id, item_name, quantity, hub, priority, status, notes "
                "FROM procurement_items ORDER BY type_id"
            ).fetchall()
        assert len(rows) == 6
        # 验证第一条
        assert rows[0]["type_id"] == 2010
        assert rows[0]["item_name"] == "巨鸟级"
        assert rows[0]["priority"] == "urgent"
        # 验证最后一条
        assert rows[-1]["type_id"] == 2015
        assert rows[-1]["item_name"] == "净化级"

    def test_batch_insert_id_sequence(self, temp_user_db):
        """批量插入后 id 应连续自增"""
        with temp_user_db.connect("user") as conn:
            for item in self.BATCH_ITEMS:
                conn.execute(self.stmt, item)
        with temp_user_db.connect("user") as conn:
            ids = [r["id"] for r in conn.execute("SELECT id FROM procurement_items ORDER BY id").fetchall()]
        assert ids == list(range(ids[0], ids[0] + 6))

    def test_filter_by_priority_urgent(self, temp_user_db):
        """按 urgent 筛出 2 条（巨鸟级、猎豹级）"""
        with temp_user_db.connect("user") as conn:
            for item in self.BATCH_ITEMS:
                conn.execute(self.stmt, item)
        with temp_user_db.connect("user") as conn:
            rows = conn.execute(
                "SELECT item_name FROM procurement_items WHERE priority = 'urgent' ORDER BY type_id"
            ).fetchall()
        assert len(rows) == 2
        names = [r["item_name"] for r in rows]
        assert "巨鸟级" in names
        assert "猎豹级" in names

    def test_filter_by_priority_high(self, temp_user_db):
        """按 high 筛出 2 条（狂怒者级、净化级）"""
        with temp_user_db.connect("user") as conn:
            for item in self.BATCH_ITEMS:
                conn.execute(self.stmt, item)
        with temp_user_db.connect("user") as conn:
            rows = conn.execute(
                "SELECT item_name FROM procurement_items WHERE priority = 'high' ORDER BY type_id"
            ).fetchall()
        assert len(rows) == 2

    def test_filter_by_priority_low(self, temp_user_db):
        """按 low 筛出 1 条（探索者级）"""
        with temp_user_db.connect("user") as conn:
            for item in self.BATCH_ITEMS:
                conn.execute(self.stmt, item)
        with temp_user_db.connect("user") as conn:
            rows = conn.execute(
                "SELECT item_name FROM procurement_items WHERE priority = 'low' ORDER BY type_id"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["item_name"] == "探索者级"

    def test_filter_by_priority_none_match(self, temp_user_db):
        """不存在的优先级返回空列表"""
        with temp_user_db.connect("user") as conn:
            conn.execute(self.stmt, (2099, "测试", 1, "Jita", "normal", "pending", ""))
        with temp_user_db.connect("user") as conn:
            rows = conn.execute("SELECT * FROM procurement_items WHERE priority = 'critical'").fetchall()
        assert rows == []
