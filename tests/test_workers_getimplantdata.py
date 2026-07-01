"""测试 services/workers/getimplantdata.py — 真实数据库集成测试

覆盖现有 test_getimplantdata.py 未触及的场景：
  - get_industry_type_ids 在真实 SQLite 上的组过滤与排序
  - init_db 幂等性（重复调用不报错）
  - 完整读写流程：init_db → 查询 → 拉取 → 写入 → 读取验证
"""

import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from services.workers.getimplantdata import (
    fetch_attribute_name,
    fetch_type_dogma,
    get_industry_type_ids,
    init_db,
)


@pytest.fixture
def temp_ref_db():
    """创建含 item 表及多组数据的临时 reference.db"""
    tmpdir = tempfile.mkdtemp(prefix="eve_test_implant_")
    db_path = Path(tmpdir) / "reference.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE item (
            type_id INTEGER PRIMARY KEY,
            en_name TEXT,
            en_group_name TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO item VALUES (?, ?, ?)",
        [
            # Cyber Production × 2
            (48112, "Implant A", "Cyber Armor"),
            (48114, "Implant B", "Cyber Armor"),
            # Cyber Resource Processing × 1
            (48116, "Implant C", "Cyber Electronic Systems"),
            # Cyber Science × 2
            (48118, "Implant D", "Cyber Engineering"),
            (48120, "Implant E", "Cyber Engineering"),
            # 非工业组（不应被返回）
            (2001, "Raven", "Ship"),
            (2002, "Drone", "Drone"),
        ],
    )
    conn.commit()
    conn.commit()
    conn.close()

    yield str(db_path)

    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)


class TestGetIndustryTypeIdsRealDb:
    """get_industry_type_ids — 真实数据库集成"""

    def test_filters_by_industry_groups_and_sorts(self, temp_ref_db):
        """只返回 INDUSTRY_GROUP_NAMES 中组的 type_id，结果升序"""
        result = get_industry_type_ids(temp_ref_db)

        assert result == [48112, 48114, 48116, 48118, 48120]
        assert 2001 not in result
        assert 2002 not in result

    def test_returns_empty_when_no_matching_groups(self):
        """数据库中无匹配组时返回空列表"""
        tmpdir = tempfile.mkdtemp(prefix="eve_test_empty_")
        db_path = Path(tmpdir) / "reference.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE item (type_id INTEGER PRIMARY KEY, en_name TEXT, en_group_name TEXT)")
        conn.execute("INSERT INTO item VALUES (1, 'Foo', 'UnknownGroup')")
        conn.commit()
        conn.close()

        result = get_industry_type_ids(str(db_path))
        assert result == []

        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


class TestInitDbIdempotent:
    """init_db — 幂等性"""

    def test_double_init_does_not_raise(self, temp_ref_db):
        """连续两次 init_db 不报错且表结构正确"""
        init_db(temp_ref_db)
        init_db(temp_ref_db)  # 第二次不应抛异常

        # 验证表可正常写入和读取
        conn = sqlite3.connect(temp_ref_db)
        conn.execute(
            "INSERT INTO item_dogma (type_id, dogma_attrs, dogma_effects) VALUES (?, ?, ?)",
            (48112, "[]", "[]"),
        )
        row = conn.execute(
            "SELECT type_id, dogma_attrs, dogma_effects FROM item_dogma WHERE type_id = ?",
            (48112,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == 48112
        assert row[1] == "[]"
        assert row[2] == "[]"


class TestFullRoundTrip:
    """完整读写流程：init_db → 查询 → fetch_type_dogma → 写入 → 读取"""

    @pytest.mark.asyncio
    async def test_dogma_fetch_and_persist(self, temp_ref_db):
        """模拟 ESI 拉取多条植入体，验证数据正确存入 item_dogma 并可直接读取"""
        # 1) 初始化表 + 查询待拉取列表
        init_db(temp_ref_db)
        type_ids = get_industry_type_ids(temp_ref_db)
        assert len(type_ids) == 5

        # 2) 模拟 ESI 客户端
        mock_client = AsyncMock()

        async def _mock_fetch(url):
            if "universe/types/48112/" in url:
                return {
                    "type_id": 48112,
                    "dogma_attributes": [{"attribute_id": 164, "value": 3}],
                    "dogma_effects": [{"effect_id": 257, "is_default": True}],
                }
            if "universe/types/48114/" in url:
                return {
                    "type_id": 48114,
                    "dogma_attributes": [{"attribute_id": 164, "value": 5}],
                    "dogma_effects": [],
                }
            # 模拟 48116 返回 None（如 ESI 404）
            if "universe/types/48116/" in url:
                return None
            return None

        mock_client.fetch = AsyncMock(side_effect=_mock_fetch)

        # 3) 模拟 main 中的并发拉取逻辑
        sem = asyncio.Semaphore(20)

        async def _fetch_one(tid):
            async with sem:
                return await fetch_type_dogma(mock_client, tid)

        results = await asyncio.gather(*[_fetch_one(t) for t in type_ids])
        results = [r for r in results if r]

        # 4) 写入 item_dogma
        conn = sqlite3.connect(temp_ref_db)
        cur = conn.cursor()
        for r in results:
            cur.execute(
                "INSERT OR REPLACE INTO item_dogma (type_id, dogma_attrs, dogma_effects) VALUES (?, ?, ?)",
                (r["type_id"], r["dogma_attrs"], r["dogma_effects"]),
            )
        conn.commit()

        # 5) 验证写入数据
        rows = conn.execute("SELECT type_id, dogma_attrs, dogma_effects FROM item_dogma ORDER BY type_id").fetchall()
        conn.close()

        # 只有 2 条有效（48116 返回 None 被过滤）
        assert len(rows) == 2

        # 48112: 1 个 attr + 1 个 effect
        tid1, attrs1, effects1 = rows[0]
        assert tid1 == 48112
        assert json.loads(attrs1) == [{"attribute_id": 164, "value": 3}]
        assert json.loads(effects1) == [{"effect_id": 257, "is_default": True}]

        # 48114: 1 个 attr + 空 effects
        tid2, attrs2, effects2 = rows[1]
        assert tid2 == 48114
        assert json.loads(attrs2) == [{"attribute_id": 164, "value": 5}]
        assert json.loads(effects2) == []

        # 6) 验证 attribute 名称查询
        result = await fetch_attribute_name(mock_client, 164)
        assert result == (164, "unknown")  # mock 未匹配 → None → unknown


class TestFetchAttributeNameEdgeCase:
    """fetch_attribute_name 边界场景"""

    @pytest.mark.asyncio
    async def test_large_attr_id_returns_unknown(self):
        """极大 attribute_id 不匹配 mock 时返回 unknown"""
        mock_client = AsyncMock()
        mock_client.fetch = AsyncMock(return_value=None)

        result = await fetch_attribute_name(mock_client, 999999)
        assert result == (999999, "unknown")
