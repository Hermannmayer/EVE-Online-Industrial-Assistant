"""数据库管理器单元测试 — 验证 DatabaseManager 的连接和 ATTACH 逻辑"""

import sqlite3

import pytest


class TestConnectPrimary:
    """connect(primary) 主库连接"""

    def test_connect_ref_returns_connection(self, temp_db):
        """连接 ref 主库应返回有效 sqlite3 连接"""
        with temp_db.connect("ref") as conn:
            assert isinstance(conn, sqlite3.Connection)

    def test_connect_ref_can_query(self, temp_db):
        """连接 ref 库后应能查询 item 表"""
        with temp_db.connect("ref") as conn:
            row = conn.execute("SELECT COUNT(*) FROM item").fetchone()
            assert row[0] >= 4  # 至少有 4 条测试数据

    def test_connect_mkt_returns_connection(self, temp_db):
        """连接 mkt 主库应返回有效连接"""
        with temp_db.connect("mkt") as conn:
            assert isinstance(conn, sqlite3.Connection)
            row = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()
            assert row[0] >= 4


class TestConnectWithAttach:
    """connect(primary, *attach) 跨库 ATTACH"""

    def test_attach_bp_to_ref(self, temp_db):
        """ATTACH bp 到 ref 后应能跨库 JOIN"""
        with temp_db.connect("ref", "bp") as conn:
            # bp.blueprint_products 表应可访问
            row = conn.execute("SELECT COUNT(*) FROM bp.blueprint_products").fetchone()
            assert row[0] >= 2

    def test_attach_mkt_to_ref(self, temp_db):
        """ATTACH mkt 到 ref 后应能跨库查询"""
        with temp_db.connect("ref", "mkt") as conn:
            row = conn.execute("SELECT COUNT(*) FROM mkt.market_prices").fetchone()
            assert row[0] >= 4

    def test_attach_multiple_databases(self, temp_db):
        """同时 ATTACH ref + mkt + bp 三库"""
        with temp_db.connect("ref", "mkt", "bp") as conn:
            r1 = conn.execute("SELECT COUNT(*) FROM item").fetchone()
            r2 = conn.execute("SELECT COUNT(*) FROM mkt.market_prices").fetchone()
            r3 = conn.execute("SELECT COUNT(*) FROM bp.blueprint_products").fetchone()
            assert r1[0] >= 4
            assert r2[0] >= 4
            assert r3[0] >= 2

    def test_duplicate_attach_ignored(self, temp_db):
        """重复 ATTACH 同一库不应报错"""
        with temp_db.connect("ref", "ref") as conn:
            row = conn.execute("SELECT COUNT(*) FROM item").fetchone()
            assert row[0] >= 4

    def test_row_factory_is_row(self, temp_db):
        """连接应使用 sqlite3.Row 作为 row_factory"""
        with temp_db.connect("ref") as conn:
            assert conn.row_factory == sqlite3.Row
            row = conn.execute("SELECT * FROM item LIMIT 1").fetchone()
            assert row is not None
            # Row 对象支持按列名访问
            assert "type_id" in row.keys()


class TestDirectConnect:
    """direct_connect — 非缓存直连"""

    def test_direct_connect_ref(self, temp_db):
        """direct_connect 应返回有效的连接"""
        conn = temp_db.direct_connect("ref")
        try:
            assert isinstance(conn, sqlite3.Connection)
            row = conn.execute("SELECT COUNT(*) FROM item").fetchone()
            assert row[0] >= 4
        finally:
            conn.close()

    def test_direct_connect_mkt(self, temp_db):
        """direct_connect mkt 库"""
        conn = temp_db.direct_connect("mkt")
        try:
            row = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()
            assert row[0] >= 4
        finally:
            conn.close()

    def test_direct_connect_returns_separate_connections(self, temp_db):
        """两次 direct_connect 应返回不同的连接对象"""
        c1 = temp_db.direct_connect("ref")
        c2 = temp_db.direct_connect("ref")
        try:
            assert c1 is not c2
        finally:
            c1.close()
            c2.close()

    def test_direct_connect_row_factory(self, temp_db):
        """direct_connect 应设置 row_factory = sqlite3.Row"""
        conn = temp_db.direct_connect("ref")
        try:
            assert conn.row_factory == sqlite3.Row
        finally:
            conn.close()


class TestBoundaryInvalidAlias:
    """边界测试 1 — 无效数据库别名 → ValueError"""

    def test_invalid_primary_raises_valueerror(self, temp_db):
        """无效主库别名应抛出 ValueError"""
        with pytest.raises(ValueError, match="Unknown database alias"):
            with temp_db.connect("invalid"):
                pass

    def test_invalid_attach_raises_valueerror(self, temp_db):
        """无效 ATTACH 别名应抛出 ValueError"""
        with pytest.raises(ValueError, match="Unknown database alias"):
            with temp_db.connect("ref", "invalid_attach"):
                pass

    def test_empty_string_primary_raises_valueerror(self, temp_db):
        """空字符串主库别名应抛出 ValueError"""
        with pytest.raises(ValueError, match="Unknown database alias"):
            with temp_db.connect(""):
                pass

    def test_multiple_attach_all_valid(self, temp_db):
        """全部有效的 ATTACH 别名不应报错"""
        with temp_db.connect("ref", "mkt", "bp") as conn:
            assert conn is not None
            row = conn.execute("SELECT COUNT(*) FROM mkt.market_prices").fetchone()
            assert row[0] >= 4


class TestBoundaryConnectionReuse:
    """边界测试 2 — 连接复用验证（同一 key 返回同一 conn）"""

    def test_same_key_returns_same_connection(self, temp_db):
        """同一 (primary,) key 应返回同一连接对象"""
        with temp_db.connect("ref") as conn1:
            conn1.execute("SELECT 1")
        with temp_db.connect("ref") as conn2:
            assert conn1 is conn2, "同一配置应复用连接"

    def test_same_key_with_attach_returns_same_connection(self, temp_db):
        """含 ATTACH 的同一 key 应返回同一连接对象"""
        with temp_db.connect("ref", "mkt") as conn1:
            conn1.execute("SELECT 1")
        with temp_db.connect("ref", "mkt") as conn2:
            assert conn1 is conn2, "含 ATTACH 的同一配置应复用连接"

    def test_different_primary_returns_different_connection(self, temp_db):
        """不同主库应返回不同连接对象"""
        with temp_db.connect("ref") as conn_ref:
            pass
        with temp_db.connect("mkt") as conn_mkt:
            assert conn_ref is not conn_mkt, "不同主库不应复用连接"

    def test_different_attach_returns_different_connection(self, temp_db):
        """不同 ATTACH 配置应返回不同连接对象"""
        with temp_db.connect("ref") as conn_plain:
            pass
        with temp_db.connect("ref", "mkt") as conn_attached:
            assert conn_plain is not conn_attached, "不同 ATTACH 配置不应复用连接"

    def test_connection_stays_open_after_context(self, temp_db):
        """连接在 with 块结束后应保持打开（留给后续复用）"""
        with temp_db.connect("ref") as conn:
            pass
        # 连接应仍可查询
        with temp_db.connect("ref") as conn2:
            assert conn2 is conn  # 复用
            row = conn2.execute("SELECT COUNT(*) FROM item").fetchone()
            assert row[0] >= 4


class TestBoundaryCrossDbQuery:
    """边界测试 3 — ATTACH 后跨库查询"""

    def test_cross_db_join_ref_mkt(self, temp_db):
        """跨库 JOIN ref.item + mkt.market_prices 应返回正确数据"""
        with temp_db.connect("ref", "mkt") as conn:
            row = conn.execute(
                "SELECT i.en_name, mp.sell_price "
                "FROM item i "
                "JOIN mkt.market_prices mp ON i.type_id = mp.type_id "
                "WHERE i.type_id = ?",
                (1001,),
            ).fetchone()
            assert row is not None, "跨库 JOIN 应返回结果"
            assert row["en_name"] == "Tritanium"
            assert row["sell_price"] == 5.0

    def test_cross_db_join_ref_bp(self, temp_db):
        """跨库 JOIN ref.item + bp.blueprint_products 应返回正确数据"""
        with temp_db.connect("ref", "bp") as conn:
            row = conn.execute(
                "SELECT i.en_name, bp.quantity "
                "FROM item i "
                "JOIN bp.blueprint_products bp ON i.type_id = bp.product_type_id "
                "WHERE i.type_id = ?",
                (2001,),
            ).fetchone()
            assert row is not None, "跨库 JOIN ref + bp 应返回结果"
            assert row["en_name"] == "Raven"
            assert row["quantity"] == 1

    def test_cross_db_three_way_join(self, temp_db):
        """三库跨库 JOIN ref + mkt + bp 应返回完整数据"""
        with temp_db.connect("ref", "mkt", "bp") as conn:
            row = conn.execute(
                "SELECT i.en_name, mp.sell_price, bp.quantity AS bp_qty "
                "FROM item i "
                "JOIN mkt.market_prices mp ON i.type_id = mp.type_id "
                "JOIN bp.blueprint_products bp ON i.type_id = bp.product_type_id "
                "WHERE i.type_id = ?",
                (2001,),
            ).fetchone()
            assert row is not None, "三库跨库 JOIN 应返回结果"
            assert row["en_name"] == "Raven"
            assert row["sell_price"] == 55000000
            assert row["bp_qty"] == 1
