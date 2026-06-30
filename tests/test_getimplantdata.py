"""植入体数据拉取单元测试 — services/workers/getimplantdata.py

测试覆盖:
  - get_industry_type_ids: 按组名查询 type_id
  - init_db: 建表
  - fetch_type_dogma: ESI 请求 → dogma 数据
  - fetch_attribute_name: ESI 请求 → attribute 名称
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.workers.getimplantdata import (
    DB_PATH,
    INDUSTRY_GROUP_NAMES,
    fetch_attribute_name,
    fetch_type_dogma,
    get_industry_type_ids,
    init_db,
)


class TestGetIndustryTypeIds:
    """从数据库获取工业植入体 type_id"""

    @patch("services.workers.getimplantdata.sqlite3.connect")
    def test_returns_type_ids_for_groups(self, mock_connect):
        """按 INDUSTRY_GROUP_NAMES 查询返回正确的 type_id"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()

        # 模拟按组名返回不同结果
        mock_cursor.fetchall.side_effect = [
            [(101, "Implant A"), (102, "Implant B")],  # Cyber Production
            [(103, "Implant C")],  # Cyber Resource Processing
            [],  # Cyber Science (empty)
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_cursor  # 注意: conn = sqlite3.connect(...)
        mock_connect.return_value = mock_conn

        result = get_industry_type_ids(DB_PATH)

        assert result == [101, 102, 103]
        assert mock_cursor.execute.call_count == len(INDUSTRY_GROUP_NAMES)

    @patch("services.workers.getimplantdata.sqlite3.connect")
    def test_returns_empty_when_no_rows(self, mock_connect):
        """无匹配行时返回空列表"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [[], [], []]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = get_industry_type_ids(DB_PATH)
        assert result == []


class TestInitDb:
    """初始化 item_dogma 表"""

    @patch("services.workers.getimplantdata.sqlite3.connect")
    def test_creates_item_dogma_table(self, mock_connect):
        """init_db 执行建表 SQL"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        init_db(DB_PATH)

        sql = mock_cursor.execute.call_args[0][0]
        assert "CREATE TABLE IF NOT EXISTS item_dogma" in sql
        assert "type_id INTEGER PRIMARY KEY" in sql
        assert "dogma_attrs TEXT" in sql
        assert "dogma_effects TEXT" in sql
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()


class TestFetchTypeDogma:
    """从 ESI 拉取单个 type 的 dogma"""

    @pytest.mark.asyncio
    async def test_returns_dogma_data(self):
        """成功拉取时返回 type_id + dogma_attrs + dogma_effects"""
        mock_client = AsyncMock()
        mock_client.fetch = AsyncMock(
            return_value={
                "type_id": 102001,
                "name": "Implant",
                "dogma_attributes": [{"attribute_id": 123, "value": 5.0}],
                "dogma_effects": [{"effect_id": 456, "is_default": True}],
            }
        )

        result = await fetch_type_dogma(mock_client, 102001)

        assert result is not None
        assert result["type_id"] == 102001
        # dogma_attrs 和 dogma_effects 是 JSON 字符串
        attrs = json.loads(result["dogma_attrs"])
        assert len(attrs) == 1
        assert attrs[0]["attribute_id"] == 123
        assert attrs[0]["value"] == 5.0

        effects = json.loads(result["dogma_effects"])
        assert len(effects) == 1
        assert effects[0]["effect_id"] == 456

    @pytest.mark.asyncio
    async def test_returns_none_on_empty_response(self):
        """API 返回空数据时返回 None"""
        mock_client = AsyncMock()
        mock_client.fetch = AsyncMock(return_value=None)

        result = await fetch_type_dogma(mock_client, 99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_missing_dogma_fields(self):
        """API 响应不含 dogma_attributes/dogma_effects 时容错"""
        mock_client = AsyncMock()
        mock_client.fetch = AsyncMock(return_value={"type_id": 666, "name": "Old"})

        result = await fetch_type_dogma(mock_client, 666)

        assert result is not None
        assert result["type_id"] == 666
        # 缺失字段 → 空列表
        assert json.loads(result["dogma_attrs"]) == []
        assert json.loads(result["dogma_effects"]) == []


class TestFetchAttributeName:
    """从 ESI 拉取 attribute 名称"""

    @pytest.mark.asyncio
    async def test_returns_attr_name(self):
        """成功拉取时返回 (attr_id, name)"""
        mock_client = AsyncMock()
        mock_client.fetch = AsyncMock(return_value={"attribute_id": 123, "name": "charisma"})

        result = await fetch_attribute_name(mock_client, 123)
        assert result == (123, "charisma")

    @pytest.mark.asyncio
    async def test_returns_unknown_on_failure(self):
        """API 失败时返回 (attr_id, 'unknown')"""
        mock_client = AsyncMock()
        mock_client.fetch = AsyncMock(return_value=None)

        result = await fetch_attribute_name(mock_client, 999)
        assert result == (999, "unknown")
