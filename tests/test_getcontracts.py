"""公开合同拉取模块单元测试 — 使用 Mock 避免真实 ESI"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.importers.getcontracts import (
    CONTRACT_TYPE_MAP,
    TRADE_REGIONS,
    _fetch_issuer_names_async,
    fetch_contract_items,
    fetch_contract_pages,
    init_db,
    list_contracts_needing_items,
    run_contract_update,
    save_contract_list,
    save_items_batch,
)

# ── 模拟 ESI 返回的合同数据 ──
#: 字段按 ESI 公开端点的**实测并集**取：没有 status / availability / assignee_id
#: （公开端点从不返回），auction 才有的 buyout 单独在这一条里给。
MOCK_CONTRACT = {
    "contract_id": 100001,
    "type": "item_exchange",
    "title": "Test Contract",
    "price": 5000000.0,
    "reward": 0.0,
    "collateral": 1000000.0,
    "volume": 5000.0,
    "days_to_complete": 7,
    "issuer_id": 90000001,
    "issuer_corporation_id": 98000001,
    "date_issued": "2026-06-01T12:00:00Z",
    "date_expired": "2026-07-01T12:00:00Z",
    "start_location_id": 60003760,
    "end_location_id": 60008494,
    "for_corporation": False,
}

MOCK_CONTRACT_ITEM = {
    "record_id": 1,
    "item_id": 1234567890,
    "type_id": 2001,
    "quantity": 100,
    "is_blueprint_copy": False,
    "is_included": True,
    "material_efficiency": 0,
    "time_efficiency": 0,
    "runs": 1,
}


class TestFetchContractPages:
    @pytest.mark.asyncio
    async def test_single_page(self):
        """单页合同列表应返回正确的数据"""
        session = MagicMock()
        session.get_headers = AsyncMock(return_value={"X-Pages": "1"})
        session.fetch_raw = AsyncMock(return_value=[MOCK_CONTRACT])

        contracts = await fetch_contract_pages(session, 10000002)
        assert len(contracts) == 1
        assert contracts[0]["contract_id"] == 100001
        assert contracts[0]["type"] == "item_exchange"

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        """HTTP 非 200 响应返回空列表"""
        session = MagicMock()
        session.get_headers = AsyncMock(return_value=None)

        contracts = await fetch_contract_pages(session, 10000002)
        assert contracts == []

    @pytest.mark.asyncio
    async def test_multi_page(self):
        """多页合同能拉取所有页面"""
        session = MagicMock()
        session.get_headers = AsyncMock(return_value={"X-Pages": "2"})
        session.fetch_raw = AsyncMock(side_effect=[[MOCK_CONTRACT], [{**MOCK_CONTRACT, "contract_id": 100002}]])

        contracts = await fetch_contract_pages(session, 10000002)
        assert len(contracts) == 2


class TestFetchContractItems:
    @pytest.mark.asyncio
    async def test_items_return_correct_structure(self):
        """合同物品应包含 record_id, type_id, quantity 等字段"""
        session = MagicMock()
        session.fetch_raw = AsyncMock(return_value=[MOCK_CONTRACT_ITEM])

        items = await fetch_contract_items(session, [100001])
        assert 100001 in items
        assert len(items[100001]) == 1
        item = items[100001][0]
        assert item["record_id"] == 1
        assert item["type_id"] == 2001
        assert item["quantity"] == 100

    @pytest.mark.asyncio
    async def test_http_error_skips_item_fetch(self):
        """合同物品拉取失败时返回空列表，不抛出异常"""
        session = MagicMock()
        session.fetch_raw = AsyncMock(return_value=None)

        items = await fetch_contract_items(session, [99999])
        assert 99999 in items
        assert items[99999] == []


class TestSaveContractList:
    @pytest.mark.asyncio
    async def test_stale_schema_is_rebuilt(self, tmp_path):
        """旧结构的表（缺 buyout、含 status/days_completed）应被整表重建。

        表是 market.db 里的可重建缓存，不进 schema_migrations；但 `CREATE TABLE IF NOT EXISTS`
        改不了已存在的表，判不到旧结构就会带着 `status NOT NULL` 等死列跑下去。
        """
        db_path = str(tmp_path / "test_market.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE public_contracts (contract_id INTEGER PRIMARY KEY, region_id INTEGER, "
            "type TEXT, status TEXT NOT NULL, days_completed INTEGER, fetch_time TEXT NOT NULL)"
        )
        conn.execute("INSERT INTO public_contracts VALUES (1, 10000002, 'item_exchange', '', 0, 'old')")
        conn.commit()
        conn.close()

        with patch("services.importers.getcontracts.DATABASE_PATH", db_path):
            await init_db()

        conn = sqlite3.connect(db_path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(public_contracts)")}
        assert "buyout" in cols
        assert "status" not in cols and "days_completed" not in cols
        # 旧行不能留着——它的 type/title 等列语义已经对不上
        assert conn.execute("SELECT COUNT(*) FROM public_contracts").fetchone()[0] == 0
        conn.close()

    @pytest.mark.asyncio
    async def test_relist_keeps_fetched_items(self, tmp_path):
        """重拉列表不得清掉已取物品与 items_fetched_at（否则每次重拉都要重跑几万次请求）。"""
        db_path = str(tmp_path / "test_market.db")
        with patch("services.importers.getcontracts.DATABASE_PATH", db_path):
            await init_db()
            keep = {**MOCK_CONTRACT, "contract_id": 100001}
            gone = {**MOCK_CONTRACT, "contract_id": 100002}
            await save_contract_list(10000002, [keep, gone], complete=True, fetch_time="T1")
            await save_items_batch({100001: [MOCK_CONTRACT_ITEM]}, "T1-items")

            # 第二轮：100002 已过期不再出现
            await save_contract_list(10000002, [keep], complete=True, fetch_time="T2")

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT contract_id, items_fetched_at FROM public_contracts ORDER BY contract_id"
        ).fetchall()
        conn.close()
        assert rows == [(100001, "T1-items")]
        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM contract_items").fetchone()[0] == 1
        conn.close()

    @pytest.mark.asyncio
    async def test_incomplete_fetch_keeps_old_rows(self, tmp_path):
        """拉取不完整的星域必须保留旧数据，不能把整区清空。"""
        db_path = str(tmp_path / "test_market.db")
        with patch("services.importers.getcontracts.DATABASE_PATH", db_path):
            await init_db()
            await save_contract_list(10000002, [MOCK_CONTRACT], complete=True, fetch_time="T1")
            assert await save_contract_list(10000002, [], complete=False, fetch_time="T2") == 0

        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT COUNT(*) FROM public_contracts").fetchone()[0] == 1
        conn.close()

    def test_format_type_map(self):
        """合同类型中文映射完整（UI 按它显示类型名）"""
        assert CONTRACT_TYPE_MAP["item_exchange"] == "物品交换"
        assert CONTRACT_TYPE_MAP["auction"] == "拍卖"
        assert CONTRACT_TYPE_MAP["courier"] == "运输"


class TestSaveItemsBatch:
    @pytest.mark.asyncio
    async def test_runs_field_is_persisted(self, tmp_path):
        """ESI 的键是 `runs` 不是 `run` —— 写错会让蓝图复制品可运行数恒为 1。"""
        db_path = str(tmp_path / "test_market.db")
        with patch("services.importers.getcontracts.DATABASE_PATH", db_path):
            await init_db()
            await save_contract_list(10000002, [MOCK_CONTRACT], complete=True, fetch_time="T1")
            await save_items_batch(
                {100001: [{**MOCK_CONTRACT_ITEM, "is_blueprint_copy": True, "runs": 42}]}, "T1-items"
            )

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT runs, item_id FROM contract_items WHERE contract_id = 100001").fetchone()
        conn.close()
        assert row == (42, 1234567890)


class TestListContractsNeedingItems:
    """courier 的 items 端点实测返回 HTTP 400 —— 永远不要为它排队拉物品。"""

    @pytest.mark.asyncio
    async def test_types_and_fetched_state(self, tmp_path):
        db_path = str(tmp_path / "test_market.db")
        with patch("services.importers.getcontracts.DATABASE_PATH", db_path):
            await init_db()
            await save_contract_list(
                10000002,
                [
                    {**MOCK_CONTRACT, "contract_id": 1, "type": "item_exchange"},
                    {**MOCK_CONTRACT, "contract_id": 2, "type": "auction", "buyout": 9e9},
                    {**MOCK_CONTRACT, "contract_id": 3, "type": "courier"},
                    {**MOCK_CONTRACT, "contract_id": 4, "type": "item_exchange"},
                ],
                complete=True,
                fetch_time="T1",
            )
            await save_items_batch({4: [MOCK_CONTRACT_ITEM]}, "T1-items")

            todo = list_contracts_needing_items(10000002, "item_exchange", limit=10)
            assert todo == [1], "已取过物品的 4 不该再排队"
            assert list_contracts_needing_items(10000002, "auction", limit=10) == [2]
            assert list_contracts_needing_items(10000002, "courier", limit=10) == []

    @pytest.mark.asyncio
    async def test_scoped_to_given_contract_ids(self, tmp_path):
        """给了 id 就只在这几份里挑，且**贵的先补** —— 自动补齐的范围是界面当前列表。

        一个星域 3.4 万份合同、一份一个请求，不收窄没人等得起；而列表按价格降序，
        先补上的正好是最该看的那几行。
        """
        db_path = str(tmp_path / "test_market.db")
        with patch("services.importers.getcontracts.DATABASE_PATH", db_path):
            await init_db()
            await save_contract_list(
                10000002,
                [
                    {**MOCK_CONTRACT, "contract_id": 1, "type": "item_exchange", "price": 100.0},
                    {**MOCK_CONTRACT, "contract_id": 2, "type": "item_exchange", "price": 9e9},
                    {**MOCK_CONTRACT, "contract_id": 4, "type": "item_exchange"},
                ],
                complete=True,
                fetch_time="T1",
            )
            await save_items_batch({4: [MOCK_CONTRACT_ITEM]}, "T1-items")

            assert list_contracts_needing_items(10000002, "item_exchange", contract_ids=[1, 2, 4]) == [2, 1]
            assert list_contracts_needing_items(10000002, "item_exchange", contract_ids=[4]) == []
            assert list_contracts_needing_items(10000002, "item_exchange", contract_ids=[]) == []


class TestIssuerNames:
    """发布者名字 —— ESI 的合同端点只给 `issuer_id`，名字得另问 `/universe/names/`。"""

    @pytest.mark.asyncio
    async def test_batch_with_single_fallback(self, tmp_path):
        """整批没解出来就逐个重试，且**查不到的绝不写缓存**。

        ESI 的 `/universe/names/` 只要有一个 id 解析不出就整个 POST 返 404，
        同批里本来查得到的名字会一起丢（`order_workers` 踩过同一个坑）。
        把「查不到」写进缓存等于永久显示空名字 —— 那比不写更糟。
        """
        db_path = str(tmp_path / "test_market.db")
        client = MagicMock()
        client.post = AsyncMock(
            side_effect=[
                None,  # 整批：有一个坏 id → 404 → None
                [{"id": 11, "name": "张三", "category": "character"}],
                None,  # 逐个重试里第二个也查不到
            ]
        )
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=client)
        session.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("services.importers.getcontracts.DATABASE_PATH", db_path),
            patch("services.importers.getcontracts.APIClient", MagicMock(return_value=session)),
        ):
            await init_db()
            written = await _fetch_issuer_names_async([11, 12])

        assert written == 1
        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT name FROM contract_issuers WHERE issuer_id = 11").fetchone() == ("张三",)
        assert conn.execute("SELECT COUNT(*) FROM contract_issuers").fetchone() == (1,)
        conn.close()


class TestRunContractUpdate:
    # 同时 patch `_fetch_and_save_list`：coroutine 一旦创建却无人 await（asyncio.run 被 mock 后
    # 没人驱动它），GC 时会冒 RuntimeWarning，并挂到**别的测试文件**头上；patch 成 Mock 则根本不创建协程。
    @patch("services.importers.getcontracts._fetch_and_save_list", new_callable=MagicMock)
    @patch("services.importers.getcontracts.asyncio.run")
    def test_defaults_to_all_trade_hubs(self, mock_asyncio_run, mock_fetch):
        """不指定星域时应带全部贸易中心的 region_id"""
        run_contract_update()
        mock_asyncio_run.assert_called_once()
        assert mock_fetch.call_args[0][0] == [rid for _, rid in TRADE_REGIONS]

    @patch("services.importers.getcontracts._fetch_and_save_list", new_callable=MagicMock)
    @patch("services.importers.getcontracts.asyncio.run")
    def test_explicit_region_ids(self, mock_asyncio_run, mock_fetch):
        """UI 传的是 region_id（星域名只用在 CLI 上）"""
        run_contract_update(region_ids=[10000002])
        mock_asyncio_run.assert_called_once()
        assert mock_fetch.call_args[0][0] == [10000002]
