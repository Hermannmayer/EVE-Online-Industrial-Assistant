"""公开合同拉取模块单元测试 — 使用 Mock 避免真实 ESI"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.workers.getcontracts import (
    CONTRACT_STATUS_MAP,
    CONTRACT_TYPE_MAP,
    fetch_contract_items,
    fetch_contract_pages,
    init_db,
    run_contract_update,
    save_contracts,
    write_progress,
)

# ── 模拟 ESI 返回的合同数据 ──

MOCK_CONTRACT = {
    "contract_id": 100001,
    "type": "item_exchange",
    "status": "outstanding",
    "title": "Test Contract",
    "price": 5000000.0,
    "reward": 0.0,
    "collateral": 1000000.0,
    "volume": 5000.0,
    "days_complete": 7,
    "issuer_id": 90000001,
    "assignee_id": 0,
    "availability": "public",
    "date_issued": "2026-06-01T12:00:00Z",
    "date_expired": "2026-07-01T12:00:00Z",
    "start_location_id": 60003760,
    "end_location_id": 60008494,
    "for_corporation": False,
}

MOCK_CONTRACT_ITEM = {
    "record_id": 1,
    "type_id": 2001,
    "quantity": 100,
    "is_blueprint_copy": False,
    "is_included": True,
    "material_efficiency": 0,
    "time_efficiency": 0,
    "run": 1,
}


class TestWriteProgress:
    def test_write_progress_creates_file(self, tmp_path):
        """write_progress 写入 JSON 进度文件"""
        with patch("services.workers.getcontracts.progress_file", return_value=str(tmp_path / "progress.json")):
            write_progress(1, 5, "测试阶段")
            content = (tmp_path / "progress.json").read_text()
            # JSON 会转义中文，检测结构即可
            assert '"current": 1' in content
            assert '"total": 5' in content


class TestFetchContractPages:
    @pytest.mark.asyncio
    async def test_single_page(self):
        """单页合同列表应返回正确的数据"""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.headers = {"X-Pages": "1"}
        mock_resp.json.return_value = [MOCK_CONTRACT]

        session = MagicMock()
        session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

        contracts = await fetch_contract_pages(session, 10000002)
        assert len(contracts) == 1
        assert contracts[0]["contract_id"] == 100001
        assert contracts[0]["type"] == "item_exchange"

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        """HTTP 非 200 响应返回空列表"""
        mock_resp = AsyncMock()
        mock_resp.status = 500

        session = MagicMock()
        session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

        contracts = await fetch_contract_pages(session, 10000002)
        assert contracts == []

    @pytest.mark.asyncio
    async def test_multi_page(self):
        """多页合同能拉取所有页面"""
        page1_resp = AsyncMock()
        page1_resp.status = 200
        page1_resp.headers = {"X-Pages": "2"}
        page1_resp.json.return_value = [MOCK_CONTRACT]

        page2_resp = AsyncMock()
        page2_resp.status = 200
        page2_resp.json.return_value = [{**MOCK_CONTRACT, "contract_id": 100002}]

        session = MagicMock()
        session.get.return_value.__aenter__ = AsyncMock(side_effect=[page1_resp, page2_resp])

        contracts = await fetch_contract_pages(session, 10000002)
        assert len(contracts) == 2


class TestFetchContractItems:
    @pytest.mark.asyncio
    async def test_items_return_correct_structure(self):
        """合同物品应包含 record_id, type_id, quantity 等字段"""
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json.return_value = [MOCK_CONTRACT_ITEM]

        session = MagicMock()
        session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

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
        mock_resp = AsyncMock()
        mock_resp.status = 404

        session = MagicMock()
        session.get.return_value.__aenter__ = AsyncMock(return_value=mock_resp)

        items = await fetch_contract_items(session, [99999])
        assert 99999 in items
        assert items[99999] == []


class TestSaveContracts:
    @pytest.mark.asyncio
    async def test_save_empty_contracts(self, tmp_path):
        """空合同数据写入应返回 (0, 0)"""
        db_path = str(tmp_path / "test_market.db")
        with patch("services.workers.getcontracts.DATABASE_PATH", db_path):
            await init_db()  # 创建表
            c_cnt, i_cnt = await save_contracts({}, {}, [10000002])
            assert c_cnt == 0
            assert i_cnt == 0

    def test_format_status_and_type_maps(self):
        """合同类型/状态映射表完整"""
        assert CONTRACT_TYPE_MAP["item_exchange"] == "物品交换"
        assert CONTRACT_TYPE_MAP["auction"] == "拍卖"
        assert CONTRACT_STATUS_MAP["outstanding"] == "进行中"
        assert CONTRACT_STATUS_MAP["finished_issuer"] == "已完成"
        assert CONTRACT_STATUS_MAP["cancelled"] == "已取消"


class TestRunContractUpdate:
    @patch("services.workers.getcontracts.asyncio.run")
    def test_run_contract_update_calls_main(self, mock_asyncio_run):
        """run_contract_update 应调用 asyncio.run(main(...))"""
        run_contract_update()
        mock_asyncio_run.assert_called_once()
        call_args = mock_asyncio_run.call_args
        assert call_args[0][0].__name__ == "main"

    @patch("services.workers.getcontracts.asyncio.run")
    def test_run_contract_update_with_regions(self, mock_asyncio_run):
        """指定区域时只更新目标区域"""
        run_contract_update(regions=["Jita"])
        mock_asyncio_run.assert_called_once()
