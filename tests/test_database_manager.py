"""数据库管理器单元测试 — 验证 DatabaseManager 的连接和 ATTACH 逻辑"""

import sqlite3


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
