"""SDE 扩展数据加载器测试 — services/workers/sde_loader.py

测试覆盖:
  - initialize_database 建表
  - write_meta_groups 写入 meta_group 表
  - write_meta_groups 更新 item.meta_group_id
  - write_meta_groups 幂等性
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import aiosqlite
import pytest

from tools.downloaders.sde_loader import (
    initialize_database,
    write_meta_groups,
)

# ─── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def temp_db_path():
    """创建临时 reference.db，返回路径字符串"""
    tmpdir = tempfile.mkdtemp(prefix="eve_test_sde_loader_")
    db_path = Path(tmpdir) / "reference.db"
    sqlite3.connect(str(db_path)).close()
    yield str(db_path)
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Helpers ─────────────────────────────────────────────


async def _ensure_item_table(db_path: str):
    """在测试数据库中创建 item 表（write_meta_groups 依赖它）"""
    async with aiosqlite.connect(db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS item (
                type_id INTEGER PRIMARY KEY,
                en_name TEXT, zh_name TEXT,
                group_id INTEGER,
                en_group_name TEXT, zh_group_name TEXT,
                market_group_id INTEGER,
                en_market_group_name TEXT, zh_market_group_name TEXT,
                volume REAL, iconID INTEGER,
                meta_group_id INTEGER, category_id INTEGER
            )
        """)
        await db.commit()


# ─── Test: initialize_database ─────────────────────────────


class TestInitializeDatabase:
    """initialize_database — SDE 扩展建表"""

    @pytest.mark.asyncio
    async def test_creates_meta_group_table(self, temp_db_path):
        """调用后 meta_group 表存在"""
        with patch("services.workers.sde_loader.DATABASE_PATH", temp_db_path):
            await initialize_database()

        conn = sqlite3.connect(temp_db_path)
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "meta_group" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, temp_db_path):
        """重复调用不报错"""
        with patch("services.workers.sde_loader.DATABASE_PATH", temp_db_path):
            await initialize_database()
            await initialize_database()


# ─── Test: write_meta_groups ───────────────────────────────


class TestWriteMetaGroups:
    """write_meta_groups — meta_group 表写入与 item.meta_group_id 更新"""

    @pytest.mark.asyncio
    async def test_creates_records(self, temp_db_path):
        """写入 meta_group 表并正确填充字段"""
        await _ensure_item_table(temp_db_path)  # write_meta_groups 需要 item 表存在

        mock_data = {
            "1": {"nameID": {"en": "Tech I", "zh": "科技 I"}},
            "2": {"nameID": {"en": "Tech II", "zh": "科技 II"}},
        }

        with patch("services.workers.sde_loader.DATABASE_PATH", temp_db_path), \
             patch("services.workers.sde_loader.load_yaml", return_value=mock_data):
            await initialize_database()
            await write_meta_groups()

        conn = sqlite3.connect(temp_db_path)
        rows = conn.execute("SELECT * FROM meta_group ORDER BY meta_group_id").fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0] == (1, "Tech I", "科技 I")
        assert rows[1] == (2, "Tech II", "科技 II")

    @pytest.mark.asyncio
    async def test_skips_when_data_exists(self, temp_db_path):
        """meta_group 表已有数据时跳过"""
        await _ensure_item_table(temp_db_path)  # write_meta_groups 需要 item 表存在

        mock_data = {"1": {"nameID": {"en": "Tech I"}}}

        with patch("services.workers.sde_loader.DATABASE_PATH", temp_db_path), \
             patch("services.workers.sde_loader.load_yaml", return_value=mock_data):
            await initialize_database()
            await write_meta_groups()  # 首次调用写入
            await write_meta_groups()  # 第二次应当跳过

        conn = sqlite3.connect(temp_db_path)
        count = conn.execute("SELECT COUNT(*) FROM meta_group").fetchone()[0]
        conn.close()
        assert count == 1

    @pytest.mark.asyncio
    async def test_updates_item_meta_group_id(self, temp_db_path):
        """同时更新 item.meta_group_id"""
        # 先创建 item 表并插入测试数据
        async with aiosqlite.connect(temp_db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS item (
                    type_id INTEGER PRIMARY KEY,
                    en_name TEXT, zh_name TEXT,
                    group_id INTEGER,
                    en_group_name TEXT, zh_group_name TEXT,
                    market_group_id INTEGER,
                    en_market_group_name TEXT, zh_market_group_name TEXT,
                    volume REAL, iconID INTEGER,
                    meta_group_id INTEGER, category_id INTEGER
                )
            """)
            for tid in (12345, 12346, 12347):
                await db.execute(
                    "INSERT INTO item (type_id, en_name) VALUES (?, ?)", (tid, f"Item_{tid}")
                )
            await db.commit()

        mock_meta = {
            "1": {"nameID": {"en": "Tech I", "zh": "科技 I"}},
            "2": {"nameID": {"en": "Tech II", "zh": "科技 II"}},
        }
        mock_type_ids = {
            "12345": {"name": {"en": "Item A"}, "groupID": 1, "metaGroupID": 1, "volume": 1.0},
            "12346": {"name": {"en": "Item B"}, "groupID": 1, "metaGroupID": 2, "volume": 1.0},
            "12347": {"name": {"en": "Item C"}, "groupID": 1, "volume": 1.0},
        }

        def _load_yaml_side_effect(name):
            return {"metaGroups.yaml": mock_meta, "typeIDs.yaml": mock_type_ids}[name]

        with patch("services.workers.sde_loader.DATABASE_PATH", temp_db_path), \
             patch("services.workers.sde_loader.load_yaml") as mock_load:
            mock_load.side_effect = _load_yaml_side_effect
            await initialize_database()
            await write_meta_groups()

        conn = sqlite3.connect(temp_db_path)
        rows = conn.execute(
            "SELECT type_id, meta_group_id FROM item ORDER BY type_id"
        ).fetchall()
        conn.close()

        assert rows == [
            (12345, 1),
            (12346, 2),
            (12347, None),
        ]
