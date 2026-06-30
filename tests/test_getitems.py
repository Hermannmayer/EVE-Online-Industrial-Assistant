"""物品数据拉取流程测试 — services/workers/getitems.py

覆盖 5 个场景：
  - process_type 完整数据映射
  - process_type 返回 None（API 404）
  - get_group_info 缓存生效
  - initialize_database 建表 & 幂等性
  - DatabaseWriter 批量更新 & 自动提交
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services.workers.getitems import (
    BATCH_SIZE,
    DatabaseWriter,
    get_group_info,
    get_market_group_info,
    group_cache,
    initialize_database,
    market_group_cache,
    process_type,
)

# ─── Fixtures ─────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_caches():
    """每个测试前清空模块级缓存"""
    group_cache.clear()
    market_group_cache.clear()


@pytest.fixture
def temp_db_path():
    """创建临时 reference.db，返回路径字符串"""
    tmpdir = tempfile.mkdtemp(prefix="eve_test_getitems_")
    db_path = Path(tmpdir) / "reference.db"
    sqlite3.connect(str(db_path)).close()
    yield str(db_path)
    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def mock_client():
    """返回 AsyncMock 客户端，默认 fetch 返回 None"""
    return AsyncMock(fetch=AsyncMock(return_value=None))


# ─── Helpers ─────────────────────────────────────────────


def _preinsert_item_rows(db_path: str, type_ids: list[int]):
    """在 item 表中插入若干空行（模拟 initialize_type_ids 的效果）"""
    conn = sqlite3.connect(db_path)
    for tid in type_ids:
        conn.execute("INSERT OR IGNORE INTO item (type_id) VALUES (?)", (tid,))
    conn.commit()
    conn.close()


# ─── Test: process_type — 数据映射 ───────────────────────


class TestProcessType:
    """process_type — API 响应 → 11 字段元组映射"""

    @pytest.mark.asyncio
    async def test_full_data_mapping(self, mock_client):
        """API 返回完整 JSON 时正确映射全部 11 个字段"""
        mock_client.fetch = AsyncMock(
            side_effect=[
                # 调用 1: /universe/types/<id>
                {
                    "type_id": 12345,
                    "groupID": 100,
                    "marketGroupID": 200,
                    "volume": 0.5,
                    "iconID": 42,
                    "name": {"en": "Tritanium", "zh": "三钛合金"},
                },
                # 调用 2: /universe/groups/100
                {
                    "groupID": 100,
                    "name": {"en": "Mineral", "zh": "矿物"},
                    "iconID": 10,
                },
                # 调用 3: /markets/groups/200
                {
                    "marketGroupID": 200,
                    "nameID": {"en": "Raw Materials", "zh": "原材料"},
                    "iconID": 20,
                },
            ]
        )

        result = await process_type(mock_client, 12345)

        assert result is not None
        (en_name, zh_name, group_id, en_group, zh_group, mkt_grp_id, en_mkt, zh_mkt, volume, icon, tid) = result

        assert en_name == "Tritanium"
        assert zh_name == "三钛合金"
        assert group_id == 100
        assert en_group == "Mineral"
        assert zh_group == "矿物"
        assert mkt_grp_id == 200
        assert en_mkt == "Raw Materials"
        assert zh_mkt == "原材料"
        assert volume == 0.5
        assert icon == 42  # 优先使用 type 自身的 iconID
        assert tid == 12345

    @pytest.mark.asyncio
    async def test_returns_none_when_fetch_fails(self, mock_client):
        """fetch 返回 None（如 404）时返回 None"""
        assert await process_type(mock_client, 99999) is None

    @pytest.mark.asyncio
    async def test_market_group_id_none(self, mock_client):
        """marketGroupID 为 None 时不崩溃，市场组名称为空"""
        mock_client.fetch = AsyncMock(
            side_effect=[
                {
                    "type_id": 12346,
                    "groupID": 101,
                    "marketGroupID": None,
                    "volume": 1.0,
                    "iconID": 0,
                    "name": {"en": "PLEX", "zh": "PLEX"},
                },
                {"groupID": 101, "name": {"en": "Special", "zh": "特殊"}, "iconID": 0},
            ]
        )

        result = await process_type(mock_client, 12346)
        assert result is not None
        (_, _, _, _, _, mkt_grp_id, en_mkt, zh_mkt, _, _, _) = result
        assert mkt_grp_id is None
        assert en_mkt == ""
        assert zh_mkt == ""

    @pytest.mark.asyncio
    async def test_name_is_string_not_dict(self, mock_client):
        """name 为字符串时直接作为 en_name，zh_name 为空（兼容 SDE 旧格式）"""
        mock_client.fetch = AsyncMock(
            side_effect=[
                {
                    "type_id": 777,
                    "groupID": 10,
                    "volume": 1.0,
                    "iconID": 0,
                    "name": "SimpleStringName",
                },
                {"groupID": 10, "name": {"en": "Group", "zh": "组"}, "iconID": 0},
            ]
        )

        result = await process_type(mock_client, 777)
        assert result is not None
        en_name, zh_name, *_ = result
        assert en_name == "SimpleStringName"
        assert zh_name == ""


# ─── Test: get_group_info 缓存 ───────────────────────────


class TestGetGroupInfoCaching:
    """get_group_info / get_market_group_info — 模块级缓存避免重复请求"""

    @pytest.mark.asyncio
    async def test_cache_hits_avoid_api(self, mock_client):
        """同一 group_id 第二次调用不走 API"""
        mock_client.fetch = AsyncMock(
            return_value={
                "groupID": 999,
                "name": {"en": "Cache Group", "zh": "缓存组"},
                "iconID": 77,
            }
        )

        r1 = await get_group_info(mock_client, 999)
        assert r1 == ("Cache Group", "缓存组", 77)
        assert mock_client.fetch.call_count == 1

        r2 = await get_group_info(mock_client, 999)
        assert r2 == ("Cache Group", "缓存组", 77)
        assert mock_client.fetch.call_count == 1  # 未增加

    @pytest.mark.asyncio
    async def test_none_or_zero_returns_early(self, mock_client):
        """group_id 为 None/0 时直接返回，不请求 API"""
        assert await get_group_info(mock_client, None) == ("", "", 0)
        assert await get_group_info(mock_client, 0) == ("", "", 0)
        mock_client.fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_market_group_cache_separate(self, mock_client):
        """market_group_cache 与 group_cache 相互独立"""
        mock_client.fetch = AsyncMock(
            return_value={
                "marketGroupID": 500,
                "nameID": {"en": "MktGroup", "zh": "市场组"},
                "iconID": 88,
            }
        )

        await get_market_group_info(mock_client, 500)
        assert 500 in market_group_cache
        assert 500 not in group_cache


# ─── Test: initialize_database ───────────────────────────


class TestInitializeDatabase:
    """initialize_database — 建表 & 幂等性"""

    @pytest.mark.asyncio
    async def test_creates_tables(self, temp_db_path):
        """调用后 item 和 market_tree 两张表存在"""
        with patch("services.workers.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()

        conn = sqlite3.connect(temp_db_path)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "item" in tables
        assert "market_tree" in tables

    @pytest.mark.asyncio
    async def test_idempotent(self, temp_db_path):
        """重复调用不报错"""
        with patch("services.workers.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()
            await initialize_database()  # 第二次不应抛异常

    @pytest.mark.asyncio
    async def test_item_table_columns(self, temp_db_path):
        """item 表包含预期的全部 11 列"""
        with patch("services.workers.getitems.DATABASE_PATH", temp_db_path):
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


# ─── Test: DatabaseWriter ────────────────────────────────


class TestDatabaseWriter:
    """DatabaseWriter — 异步批量 UPDATE 与自动提交"""

    @pytest.mark.asyncio
    async def test_commit_flushes_buffer(self, temp_db_path):
        """手动 commit 后缓冲区清空且数据持久化到数据库"""
        with patch("services.workers.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()
            _preinsert_item_rows(temp_db_path, [12345])

            async with DatabaseWriter() as writer:
                row = (
                    "Tritanium",
                    "三钛合金",
                    100,
                    "Mineral",
                    "矿物",
                    200,
                    "Raw Materials",
                    "原材料",
                    0.01,
                    42,
                    12345,
                )
                await writer.add_data(row)
                assert len(writer.buffer) == 1

                await writer.commit()
                assert len(writer.buffer) == 0

            conn = sqlite3.connect(temp_db_path)
            row = conn.execute("SELECT en_name, zh_name, volume, iconID FROM item WHERE type_id=?", (12345,)).fetchone()
            conn.close()
            assert row == ("Tritanium", "三钛合金", 0.01, 42)

    @pytest.mark.asyncio
    async def test_batch_auto_commit_at_limit(self, temp_db_path):
        """缓冲区达到 BATCH_SIZE 时自动提交"""
        total = BATCH_SIZE + 1  # 多一条以保证最后一条触发 flush
        with patch("services.workers.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()
            _preinsert_item_rows(temp_db_path, list(range(20000, 20000 + total)))

            async with DatabaseWriter() as writer:
                for i in range(BATCH_SIZE):  # 第 0 … 99 条
                    row = (f"Item_{i}", "", 0, "", "", None, "", "", 0.0, 0, 20000 + i)
                    await writer.add_data(row)
                # BATCH_SIZE 条后缓冲区应刚好触发提交
                assert len(writer.buffer) == 0, "BATCH_SIZE 条后应自动提交"

                # 再写 1 条 —— buffer 应有 1 条未提交
                row = (f"Item_{BATCH_SIZE}", "", 0, "", "", None, "", "", 0.0, 0, 20000 + BATCH_SIZE)
                await writer.add_data(row)
                assert len(writer.buffer) == 1, "多出的 1 条应暂存 buffer"

            # exit 时自动 commit，所有数据应已写入
            conn = sqlite3.connect(temp_db_path)
            updated = conn.execute("SELECT COUNT(*) FROM item WHERE en_name IS NOT NULL").fetchone()[0]
            conn.close()
            assert updated == total

    @pytest.mark.asyncio
    async def test_delete_data_removes_row(self, temp_db_path):
        """delete_data 从数据库中移除指定 type_id"""
        with patch("services.workers.getitems.DATABASE_PATH", temp_db_path):
            await initialize_database()
            conn = sqlite3.connect(temp_db_path)
            conn.execute("INSERT INTO item (type_id, en_name) VALUES (?, ?)", (99999, "ToBeDeleted"))
            conn.commit()
            conn.close()

            async with DatabaseWriter() as writer:
                await writer.delete_data(99999)

            conn = sqlite3.connect(temp_db_path)
            row = conn.execute("SELECT type_id FROM item WHERE type_id=?", (99999,)).fetchone()
            conn.close()
            assert row is None
