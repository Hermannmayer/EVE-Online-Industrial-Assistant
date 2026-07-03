"""植入体数据拉取单元测试 — services/workers/getimplantdata.py

测试覆盖:
  - get_industry_type_ids: 按组名查询 type_id
  - init_db: 建表
"""

from unittest.mock import MagicMock, patch

import pytest

from services.workers.getimplantdata import (
    DB_PATH,
    INDUSTRY_GROUP_NAMES,
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
            [(101, "Implant A"), (102, "Implant B")],  # Cyber Armor
            [(103, "Implant C")],  # Cyber Electronic Systems
            [],  # Cyber Engineering
            [],  # Cyber Gunnery
            [],  # Cyber Leadership
            [],  # Cyber Learning
            [],  # Cyber Missile
            [],  # Cyber Navigation
            [],  # Cyber Shields
            [(104, "Implant D")],  # Cyber Targeting
        ]
        mock_conn.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_conn

        result = get_industry_type_ids(DB_PATH)

        assert result == [101, 102, 103, 104]
        assert mock_cursor.execute.call_count == len(INDUSTRY_GROUP_NAMES)

    @patch("services.workers.getimplantdata.sqlite3.connect")
    def test_returns_empty_when_no_rows(self, mock_connect):
        """无匹配行时返回空列表"""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.side_effect = [[], [], [], [], [], [], [], [], [], []]
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
