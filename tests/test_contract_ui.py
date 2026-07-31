"""合同 UI 过滤测试 — ContractFilterProxy

使用 qapp fixture 提供 QApplication 实例。
"""

import pytest
from PySide6.QtCore import QModelIndex

from ui_pyside6.views.contract_view import ContractFilterProxy, ContractTableModel

# ── 测试数据（与 test_contract_models.py 共享结构） ──

SAMPLE_CONTRACTS = [
    {
        "contract_id": 1001,
        "type": "item_exchange",
        "title": "Tritanium Bulk",
        "price": 5000000.00,
        "collateral": 1000000.00,
        "volume": 50000.0,
        "days_completed": 7,
        "status": "outstanding",
        "date_issued": "2026-06-01 12:00:00",
        "date_expired": "2026-07-01 12:00:00",
    },
    {
        "contract_id": 1002,
        "type": "auction",
        "title": "Raven Blueprint",
        "price": 100000000.00,
        "collateral": 0.0,
        "volume": 1.0,
        "days_completed": 0,
        "status": "finished_issuer",
        "date_issued": "2026-05-15 08:00:00",
        "date_expired": "2026-06-15 08:00:00",
    },
    {
        "contract_id": 1003,
        "type": "courier",
        "title": "Jita → Amarr",
        "price": 0.0,
        "collateral": 50000000.00,
        "volume": 150000.0,
        "days_completed": 3,
        "status": "in_progress",
        "date_issued": "2026-06-20 10:00:00",
        "date_expired": "2026-06-30 10:00:00",
    },
    {
        "contract_id": 1004,
        "type": "item_exchange",
        "title": "Rented Refinery",
        "price": 750000000.00,
        "collateral": 0.0,
        "volume": 0.0,
        "days_completed": None,
        "status": "cancelled",
        "date_issued": "2026-04-01 00:00:00",
        "date_expired": "2026-05-01 00:00:00",
    },
    {
        "contract_id": 1005,
        "type": "item_exchange",
        "title": "",
        "price": 1200.50,
        "collateral": 500.00,
        "volume": 10.0,
        "days_completed": 1,
        "status": "expired",
        "date_issued": "2026-03-01 00:00:00",
        "date_expired": "2026-04-01 00:00:00",
    },
]


def _setup(qapp):
    """创建带数据的模型和代理"""
    model = ContractTableModel()
    model.set_rows(SAMPLE_CONTRACTS)
    proxy = ContractFilterProxy()
    proxy.setSourceModel(model)
    return model, proxy


# ═══════════════════════════════════════════════════════
#  ContractFilterProxy 测试
# ═══════════════════════════════════════════════════════


@pytest.fixture
def setup_proxy(qapp):
    return _setup(qapp)


class TestContractFilterProxy:
    """合同列表实时过滤"""

    def test_no_filter_shows_all(self, setup_proxy):
        _, proxy = setup_proxy
        assert proxy.rowCount() == 5

    # ── 文本搜索 ──

    @pytest.mark.parametrize(
        "search_text, expected_count",
        [
            ("Tritanium", 1),
            ("Bulk", 1),
            ("tritanium", 1),
            ("NonExistentXYZ", 0),
            ("Ji", 1),
        ],
    )
    def test_filter_by_title(self, setup_proxy, search_text, expected_count):
        _, proxy = setup_proxy
        proxy.set_search_text(search_text)
        assert proxy.rowCount() == expected_count

    def test_filter_by_title_empty_clears(self, setup_proxy):
        _, proxy = setup_proxy
        proxy.set_search_text("Tritanium")
        assert proxy.rowCount() == 1
        proxy.set_search_text("")
        assert proxy.rowCount() == 5

    # ── 价格区间 ──

    @pytest.mark.parametrize(
        "price_min, price_max, expected_count",
        [
            (100_000_000, 0, 2),  # min 100M, no max → 2 (100M + 750M)
            (0, 1_000_000, 2),  # max 1M → 2 (0 + 1200.5)
            (4_000_000, 6_000_000, 1),  # range → 1 (5M)
            (0, 0, 5),  # no range → all
            (50_000_000, 0, 2),  # min 50M, no max → 2
        ],
    )
    def test_filter_price_range(self, setup_proxy, price_min, price_max, expected_count):
        _, proxy = setup_proxy
        proxy.set_price_range(price_min, price_max)
        assert proxy.rowCount() == expected_count

    # ── 买卖类型 ──

    @pytest.mark.parametrize(
        "buy_sell, expected_count, desc",
        [
            ("全部", 5, "全部不过滤"),
            ("我要买", 4, "item_exchange + auction，排除 courier"),
            ("我要卖", 3, "仅 item_exchange"),
        ],
    )
    def test_filter_buy_sell(self, setup_proxy, buy_sell, expected_count, desc):
        _, proxy = setup_proxy
        proxy.set_buy_sell(buy_sell)
        assert proxy.rowCount() == expected_count, desc

    @pytest.mark.parametrize(
        "buy_sell, excluded_type",
        [
            ("我要买", "courier"),
            ("我要卖", "courier"),
            ("我要卖", "auction"),
        ],
    )
    def test_filter_buy_sell_excludes(self, setup_proxy, buy_sell, excluded_type):
        """验证特定类型被排除"""
        _, proxy = setup_proxy
        proxy.set_buy_sell(buy_sell)
        for r in range(proxy.rowCount()):
            src_idx = proxy.mapToSource(proxy.index(r, 0))
            row = proxy.sourceModel().get_row(src_idx.row())
            assert row["type"] != excluded_type

    # ── 组合过滤 ──

    def test_filter_combined_search_and_price(self, setup_proxy):
        _, proxy = setup_proxy
        proxy.set_search_text("a")
        proxy.set_price_range(1_000_000, 10_000_000)
        assert proxy.rowCount() == 1

    def test_filter_combined_search_and_buy_sell(self, setup_proxy):
        _, proxy = setup_proxy
        proxy.set_search_text("Rented")
        proxy.set_buy_sell("我要卖")
        assert proxy.rowCount() == 1

    def test_filter_clear_all(self, setup_proxy):
        _, proxy = setup_proxy
        proxy.set_search_text("Tritanium")
        proxy.set_price_range(1_000_000, 10_000_000)
        proxy.set_buy_sell("我要卖")
        assert proxy.rowCount() >= 0
        proxy.set_search_text("")
        proxy.set_price_range(0, 0)
        proxy.set_buy_sell("全部")
        assert proxy.rowCount() == 5

    # ── 边界条件 ──

    def test_filter_with_empty_model(self, qapp):
        model = ContractTableModel()
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)
        assert proxy.rowCount() == 0
        proxy.set_search_text("test")
        assert proxy.rowCount() == 0

    def test_filter_accepts_row_direct(self, setup_proxy):
        _, proxy = setup_proxy
        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy.filterAcceptsRow(1, QModelIndex()) is True

    def test_filter_title_with_special_chars(self, setup_proxy):
        _, proxy = setup_proxy
        proxy.set_search_text("→")
        assert proxy.rowCount() == 1  # "Jita → Amarr"

    def test_source_model_changed(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)
        proxy.set_search_text("Tritanium")
        assert proxy.rowCount() == 1

        model2 = ContractTableModel()
        model2.set_rows(SAMPLE_CONTRACTS[:3])
        proxy.setSourceModel(model2)
        proxy.set_search_text("")
        assert proxy.rowCount() == 3
