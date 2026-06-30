"""库存管理 —— 3 个基础 CRUD 测试，使用临时 SQLite 数据库"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from services.inventory_manager import SCHEMA, create_hangar, delete_hangar, get_hangars


@pytest.fixture
def inv_db():
    """创建临时 user.db，注入到 inventory_manager 模块"""
    import services.inventory_manager as im
    from services.database_manager import DB_PATH_MAP, DatabaseManager

    tmpdir = Path(tempfile.mkdtemp(prefix="inv_test_"))
    user_db = tmpdir / "user.db"

    conn = sqlite3.connect(str(user_db))
    conn.executescript(SCHEMA)
    conn.close()

    saved = dict(DB_PATH_MAP)
    DB_PATH_MAP["user"] = str(user_db)

    db = DatabaseManager()
    orig = im.db
    im.db = db

    yield tmpdir

    im.db = orig
    DB_PATH_MAP.clear()
    DB_PATH_MAP.update(saved)
    import shutil

    shutil.rmtree(str(tmpdir), ignore_errors=True)


class TestHangarBasicCRUD:
    """机库基础 CRUD —— 使用真实 SQLite 临时数据库"""

    def test_create_hangar(self, inv_db):
        """创建机库应插入记录并返回正整数 id"""
        hid = create_hangar("主仓库")
        assert isinstance(hid, int) and hid > 0

        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute("SELECT name FROM hangars WHERE id = ?", (hid,)).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "主仓库"

    def test_get_hangars(self, inv_db):
        """查询机库列表应返回所有已有记录"""
        create_hangar("矿仓")
        create_hangar("组件仓")

        hangars = get_hangars()
        assert len(hangars) == 2
        names = [h["name"] for h in hangars]
        assert "矿仓" in names
        assert "组件仓" in names
        for h in hangars:
            assert "id" in h
            assert "name" in h
            assert "notes" in h

    def test_delete_hangar(self, inv_db):
        """删除机库应移除记录并返回 True"""
        hid = create_hangar("待删机库")
        assert delete_hangar(hid) is True

        conn = sqlite3.connect(str(inv_db / "user.db"))
        row = conn.execute("SELECT COUNT(*) FROM hangars WHERE id = ?", (hid,)).fetchone()
        conn.close()
        assert row[0] == 0
