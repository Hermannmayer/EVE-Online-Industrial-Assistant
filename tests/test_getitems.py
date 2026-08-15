"""物品数据拉取流程测试 — tools/downloaders/getitems.py

覆盖 5 个场景:
  - initialize_database 建表 & 幂等性
  - write_items 批量写入 item 表
  - write_market_tree 批量写入 market_tree 表
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from tools.downloaders.getitems import (
    initialize_database,
    write_items,
    write_market_tree,
)

# ─── Fixtures ─────────────────────────────────────────────


@pytest.fixture
def temp_db_path():
    """创建临时 reference.db，返回路径字符串"""
    tmpdir = tempfile.mkdtemp(prefix="eve_test_getitems_")
    db_path = Path(tmpdir) / "reference.db"
    sqlite3.connect(str(db_path)).close()
    yield str(db_path)
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


# ─── Helpers ─────────────────────────────────────────────


def _update_imported_database_path(temp_db_path):
    """Patch getitems.DATABASE_PATH to point at temp_db_path"""
    return patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path)


# ─── Test: initialize_database ───────────────────────────


class TestInitializeDatabase:
    """initialize_database — 建表 & 幂等性"""

    @pytest.mark.asyncio
    async def test_creates_tables(self, temp_db_path):
        """调用后 item 和 market_tree 两张表存在"""
        with patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()

        conn = sqlite3.connect(temp_db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "item" in tables
        assert "market_tree" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, temp_db_path):
        """重复调用不报错"""
        with patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()
            await initialize_database()  # 第二次不应抛异常

    @pytest.mark.asyncio
    async def test_item_table_columns(self, temp_db_path):
        """item 表包含预期的全部 11 列"""
        with patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()

        conn = sqlite3.connect(temp_db_path)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(item)").fetchall()]
        conn.close()

        assert cols == [
            "type_id",
            "en_name",
            "zh_name",
            "group_id",
            "en_group_name",
            "zh_group_name",
            "market_group_id",
            "en_market_group_name",
            "zh_market_group_name",
            "volume",
            "iconID",
        ]


# ─── Test: write_items ───────────────────────────────────


class TestWriteItems:
    """write_items — 从 SDE YAML 批量写入 item 表"""

    @pytest.mark.asyncio
    async def test_write_items_creates_records(self, temp_db_path):
        """write_items 写入 item 表并正确填充字段"""
        mock_type_ids = {
            "12345": {
                "name": {"en": "Tritanium", "zh": "三钛合金"},
                "groupID": 100,
                "volume": 0.5,
                "marketGroupID": 200,
                "iconID": 42,
            },
        }
        mock_groups = {
            "100": {"name": {"en": "Mineral", "zh": "矿物"}},
        }
        mock_market_groups = {
            "200": {"name": {"en": "Raw Materials", "zh": "原材料"}},
        }

        with (
            patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path),
            patch("tools.downloaders.getitems.load_yaml_async") as mock_load_yaml,
        ):

            async def fake_load(name):
                return {
                    "typeIDs.yaml": mock_type_ids,
                    "groupIDs.yaml": mock_groups,
                    "marketGroups.yaml": mock_market_groups,
                }[name]

            mock_load_yaml.side_effect = fake_load

            await initialize_database()
            await write_items()

        conn = sqlite3.connect(temp_db_path)
        row = conn.execute("SELECT * FROM item WHERE type_id=?", (12345,)).fetchone()
        conn.close()

        assert row is not None
        (type_id, en_name, zh_name, group_id, en_group, zh_group, mkt_grp_id, en_mkt, zh_mkt, volume, icon) = row

        assert type_id == 12345
        assert en_name == "Tritanium"
        assert zh_name == "三钛合金"
        assert group_id == 100
        assert en_group == "Mineral"
        assert zh_group == "矿物"
        assert mkt_grp_id == 200
        assert en_mkt == "Raw Materials"
        assert zh_mkt == "原材料"
        assert volume == 0.5
        assert icon == 42

    @pytest.mark.asyncio
    async def test_skips_below_start_type_id(self, temp_db_path):
        """type_id < START_TYPE_ID=17 时跳过"""
        mock_type_ids = {
            "16": {
                "name": {"en": "Old Item"},
                "groupID": 10,
                "volume": 1.0,
            },
            "12345": {
                "name": {"en": "Normal Item"},
                "groupID": 10,
                "volume": 1.0,
            },
        }
        mock_groups = {"10": {"name": {"en": "Group"}}}
        mock_market_groups = {}

        with (
            patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path),
            patch("tools.downloaders.getitems.load_yaml_async") as mock_load_yaml,
        ):

            async def fake_load(name):
                return {
                    "typeIDs.yaml": mock_type_ids,
                    "groupIDs.yaml": mock_groups,
                    "marketGroups.yaml": mock_market_groups,
                }[name]

            mock_load_yaml.side_effect = fake_load

            await initialize_database()
            await write_items()

        conn = sqlite3.connect(temp_db_path)
        rows = conn.execute("SELECT type_id FROM item").fetchall()
        conn.close()
        type_ids = {r[0] for r in rows}
        assert 16 not in type_ids  # below START_TYPE_ID
        assert 12345 in type_ids


# ─── Test: write_market_tree ─────────────────────────────


class TestWriteMarketTree:
    """write_market_tree — 从 marketGroups.yaml 批量写入 market_tree 表"""

    @pytest.mark.asyncio
    async def test_write_market_tree_creates_records(self, temp_db_path):
        """write_market_tree 写入 market_tree 表并正确填充字段"""
        mock_data = {
            "100": {
                "nameID": {"en": "Raw Materials", "zh": "原材料"},
                "parentGroupID": None,
                "iconID": 10,
            },
            "200": {
                "nameID": {"en": "Minerals", "zh": "矿物"},
                "parentGroupID": 100,
                "iconID": 11,
            },
        }

        with (
            patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path),
            patch("tools.downloaders.getitems.load_yaml_async", AsyncMock(return_value=mock_data)),
        ):
            await initialize_database()
            await write_market_tree()

        conn = sqlite3.connect(temp_db_path)
        rows = conn.execute("SELECT * FROM market_tree ORDER BY market_group_id").fetchall()
        conn.close()

        assert len(rows) == 2
        assert rows[0] == (100, None, "Raw Materials", "原材料", 10)
        assert rows[1] == (200, 100, "Minerals", "矿物", 11)

    @pytest.mark.asyncio
    async def test_handles_empty_yaml(self, temp_db_path):
        """YAML 数据为空时跳过，不报错"""
        with (
            patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path),
            patch("tools.downloaders.getitems.load_yaml_async", AsyncMock(return_value=None)),
        ):
            await initialize_database()
            await write_market_tree()

        conn = sqlite3.connect(temp_db_path)
        count = conn.execute("SELECT COUNT(*) FROM market_tree").fetchone()[0]
        conn.close()
        assert count == 0


# ─── Test: main 的 SDE 下载进度透传 ─────────────────────


class TestMainSdeDownloadProgress:
    """main() 下载 SDE 阶段透传 progress_cb，映射到步骤 10-39 区间"""

    @pytest.mark.asyncio
    async def test_forwards_sde_download_progress(self, temp_db_path):
        """空库走下载路径，ensure_sde_cache 收到包装回调且映射正确"""
        from tools.downloaders.getitems import main

        calls: list[tuple[int, str]] = []
        captured: dict = {}

        async def fake_ensure_sde_cache(cb):
            captured["cb"] = cb
            assert cb is not None, "下载阶段应透传 progress_cb"
            for pct in (0, 50, 99):
                cb(pct, f"SDE 包下载 {pct} MB")
            return None

        async def fake_write_items(cb=None):
            pass

        async def fake_market_tree():
            pass

        async def fake_fill(cb=None):
            if cb:
                cb(100, "完成")

        with (
            patch("tools.downloaders.getitems.DATABASE_PATH", temp_db_path),
            patch("tools.downloaders.getitems.ensure_sde_cache", fake_ensure_sde_cache),
            patch("tools.downloaders.getitems.write_items", fake_write_items),
            patch("tools.downloaders.getitems.write_market_tree", fake_market_tree),
            patch("tools.downloaders.getitems.fill_missing_item_names_from_esi", fake_fill),
        ):
            await initialize_database()
            await main(progress_cb=lambda p, m: calls.append((p, m)))

        dl = [c for c in calls if "SDE 包下载" in c[1]]
        assert len(dl) == 3, "下载进度回调应透传到 UI"
        # 0/50/99 → 10/25/39（映射到步骤 10-39，避免进度条跳变）
        assert [p for p, _ in dl] == [10, 25, 39]
        assert captured["cb"] is not None
