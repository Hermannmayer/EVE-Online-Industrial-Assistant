"""getrigdata worker 测试 — 结构改装件加成拉取"""

import asyncio
import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.downloaders import getrigdata


@pytest.fixture
def rig_db(tmp_path):
    """临时 reference.db + item 表（含改件组行 + 1818 应被排除）"""
    db_path = tmp_path / "reference.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE item (type_id INTEGER PRIMARY KEY, en_name TEXT, zh_name TEXT, group_id INTEGER);
        INSERT INTO item VALUES (43920, 'M Mat Rig', '材料效率I', 1816);
        INSERT INTO item VALUES (37160, 'M Time Rig', '时间效率I', 1819);
        INSERT INTO item VALUES (37158, 'L Rig', '大型效率I', 1850);
        INSERT INTO item VALUES (999, 'Strong Box', '强效箱', 1818);
        """
    )
    conn.commit()
    conn.close()
    return db_path


def test_init_db_idempotent(rig_db):
    getrigdata.init_db(str(rig_db))
    getrigdata.init_db(str(rig_db))  # 二次运行幂等
    conn = sqlite3.connect(str(rig_db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(structure_rigs)")}
    conn.close()
    assert "type_id" in cols
    assert "mat_bonus" in cols
    assert "time_bonus" in cols


def test_get_rig_type_ids_excludes_1818(rig_db):
    type_ids = getrigdata.get_rig_type_ids(str(rig_db))
    assert 43920 in type_ids
    assert 37160 in type_ids
    assert 37158 in type_ids
    assert 999 not in type_ids  # 1818 Strong Boxes 排除


def test_fetch_rig_bonuses_parses():
    """解析 attributeEngRigMatBonus=2594 / attributeEngRigTimeBonus=2593"""
    client = MagicMock()
    client.fetch = AsyncMock(
        return_value={
            "dogma_attributes": [
                {"attribute_id": 2594, "value": -2.0},
                {"attribute_id": 2593, "value": -20.0},
            ]
        }
    )
    r = asyncio.run(getrigdata.fetch_rig_bonuses(client, 43920))
    assert r == {"type_id": 43920, "mat_bonus": -2.0, "time_bonus": -20.0}


def test_fetch_rig_bonuses_failure():
    """ESI 失败 → None（增量拉取跳过）"""
    client = MagicMock()
    client.fetch = AsyncMock(return_value=None)
    assert asyncio.run(getrigdata.fetch_rig_bonuses(client, 43920)) is None


def test_fetch_rig_bonuses_missing_attrs():
    """无加成属性 → 默认 0"""
    client = MagicMock()
    client.fetch = AsyncMock(return_value={"dogma_attributes": []})
    r = asyncio.run(getrigdata.fetch_rig_bonuses(client, 43920))
    assert r == {"type_id": 43920, "mat_bonus": 0.0, "time_bonus": 0.0}
