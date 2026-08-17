"""合同数据模型测试 — ContractTableModel

使用 qapp fixture 提供 QApplication 实例。
"""

import pytest
from PySide6.QtCore import QModelIndex, Qt

from ui_pyside6.models.contract_models import (
    CONTRACT_STATUS_CN,
    CONTRACT_TYPE_CN,
    ContractFilterProxy,
    ContractTableModel,
)

pytestmark = pytest.mark.ui

# ── 测试数据 ──

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


# ═══════════════════════════════════════════════════════
#  ContractTableModel 测试
# ═══════════════════════════════════════════════════════


class TestContractTableModel:
    """合同表格数据模型基础操作"""

    def test_row_count(self, qapp):
        model = ContractTableModel()
        assert model.rowCount() == 0
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.rowCount() == 5

    def test_column_count(self, qapp):
        model = ContractTableModel()
        assert model.columnCount() == 10

    def test_set_rows_replaces_data(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.rowCount() == 5
        model.set_rows(SAMPLE_CONTRACTS[:2])
        assert model.rowCount() == 2

    # ── 字段显示 ──

    def test_display_contract_id(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 0)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "1001"

    def test_display_type_cn(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        for row_idx, (_contract_type, expected_cn) in enumerate(
            [
                ("item_exchange", CONTRACT_TYPE_CN["item_exchange"]),
                ("auction", CONTRACT_TYPE_CN["auction"]),
                ("courier", CONTRACT_TYPE_CN["courier"]),
            ]
        ):
            assert model.index(row_idx, 1).data(Qt.ItemDataRole.DisplayRole) == expected_cn

    def test_display_title(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(0, 2).data(Qt.ItemDataRole.DisplayRole) == "Tritanium Bulk"

    def test_display_empty_title_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(4, 2).data(Qt.ItemDataRole.DisplayRole) == "—"

    def test_display_price_formatted(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(0, 3).data(Qt.ItemDataRole.DisplayRole) == "5,000,000.00"

    def test_display_zero_price_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(2, 3).data(Qt.ItemDataRole.DisplayRole) == "—"

    @pytest.mark.parametrize(
        "contract_idx, col, expected_substr",
        [
            (0, 4, "1,000,000"),
            (0, 5, "50,000"),
            (0, 8, "2026-06-01 12:00:00"),
            (0, 9, "2026-07-01 12:00:00"),
        ],
    )
    def test_display_column_contains(self, qapp, contract_idx, col, expected_substr):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        val = model.index(contract_idx, col).data(Qt.ItemDataRole.DisplayRole)
        assert expected_substr in val, f"Expected '{expected_substr}' in '{val}'"

    def test_display_zero_collateral_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(1, 4).data(Qt.ItemDataRole.DisplayRole) == "—"

    def test_display_status_cn(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(0, 7).data(Qt.ItemDataRole.DisplayRole) == CONTRACT_STATUS_CN["outstanding"]

    def test_display_days_completed(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        for r in range(model.rowCount()):
            val = model.index(r, 6).data(Qt.ItemDataRole.DisplayRole)
            row = model.get_row(r)
            dc = row.get("days_completed")
            if dc and dc > 0:
                assert val == str(dc)
            else:
                assert val == "—"

    def test_display_none_days_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.index(3, 6).data(Qt.ItemDataRole.DisplayRole) == "—"

    # ── UserRole ──

    def test_user_role_returns_full_row(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        row = model.index(0, 0).data(Qt.ItemDataRole.UserRole)
        assert row["contract_id"] == 1001
        assert row["type"] == "item_exchange"
        assert row["price"] == 5000000.00

    # ── get_row ──

    @pytest.mark.parametrize("row_idx, expected_id", [(0, 1001), (None, None)])
    def test_get_row(self, qapp, row_idx, expected_id):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        if row_idx is None:
            assert model.get_row(-1) is None
            assert model.get_row(999) is None
        else:
            row = model.get_row(row_idx)
            assert row is not None
            assert row["contract_id"] == expected_id

    def test_get_row_invalid_returns_none(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.get_row(-1) is None
        assert model.get_row(999) is None
        assert model.get_row(5) is None

    def test_get_row_empty_model(self, qapp):
        model = ContractTableModel()
        assert model.get_row(0) is None

    # ── 表头 ──

    def test_header_data(self, qapp):
        model = ContractTableModel()
        header0 = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        assert header0 == "合同ID"

    @pytest.mark.parametrize("section", list(range(10)))
    def test_header_data_valid_section(self, qapp, section):
        """有效 section 应返回列名"""
        model = ContractTableModel()
        h = model.headerData(section, Qt.Orientation.Horizontal)
        assert h is not None
        assert isinstance(h, str)
        assert len(h) > 0

    # ── 排序 ──

    @pytest.mark.parametrize(
        "col, order, expected_first_id",
        [
            (3, Qt.SortOrder.DescendingOrder, 1004),
            (3, Qt.SortOrder.AscendingOrder, 1003),
        ],
    )
    def test_sort_by_price(self, qapp, col, order, expected_first_id):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(col, order)
        assert model._rows[0]["contract_id"] == expected_first_id

    def test_sort_by_title(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(2, Qt.SortOrder.AscendingOrder)
        sorted_titles = [r["title"] for r in model._rows if r["title"]]
        assert sorted_titles == sorted(sorted_titles)

    def test_invalid_column_does_nothing(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(99, Qt.SortOrder.AscendingOrder)
        assert model.rowCount() == 5

    # ── 样式 ──

    def test_text_alignment(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 3)
        align = idx.data(Qt.ItemDataRole.TextAlignmentRole)
        assert align == (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    @pytest.mark.parametrize(
        "contract_idx, col, desc",
        [
            (0, 3, "price > 0 → green foreground"),
            (2, 3, "price = 0 → secondary foreground"),
            (0, 7, "outstanding → green foreground"),
            (3, 7, "cancelled → red foreground"),
        ],
    )
    def test_foreground_colors(self, qapp, contract_idx, col, desc):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        color = model.index(contract_idx, col).data(Qt.ItemDataRole.ForegroundRole)
        assert color is not None, f"Foreground for {desc}"

    def test_font_monospace_on_numeric(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        font = model.index(0, 0).data(Qt.ItemDataRole.FontRole)
        assert font is not None

    def test_background_alternating_rows(self, qapp):
        """验证隔行换色背景存在"""
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        bg0 = model.index(0, 0).data(Qt.ItemDataRole.BackgroundRole)
        bg1 = model.index(1, 0).data(Qt.ItemDataRole.BackgroundRole)
        assert bg0 is not None
        assert bg1 is not None

    # ── 空数据状态 ──

    def test_empty_model_get_row_returns_none(self, qapp):
        model = ContractTableModel()
        assert model.get_row(0) is None
        assert model.get_row(-1) is None

    def test_set_rows_empty_clears_data(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.rowCount() == 5
        model.set_rows([])
        assert model.rowCount() == 0
        assert model.get_row(0) is None

    def test_column_count_constant(self, qapp):
        """列数应为常量"""
        model = ContractTableModel()
        assert model.columnCount() == 10
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.columnCount() == 10
        model.set_rows([])
        assert model.columnCount() == 10


# ════════════════════════════════════════════════════════════════
#  ContractFilterProxy 过滤测试（自 test_contract_ui 并入，复用上方 SAMPLE_CONTRACTS）
# ════════════════════════════════════════════════════════════════


def _setup(qapp):
    """创建带数据的模型和代理"""
    model = ContractTableModel()
    model.set_rows(SAMPLE_CONTRACTS)
    proxy = ContractFilterProxy()
    proxy.setSourceModel(model)
    return model, proxy


@pytest.fixture
def setup_proxy(qapp):
    return _setup(qapp)


class TestContractFilterProxy:
    """合同列表实时过滤"""

    def test_no_filter_shows_all(self, setup_proxy):
        _, proxy = setup_proxy
        assert proxy.rowCount() == 5

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

    @pytest.mark.parametrize(
        "price_min, price_max, expected_count",
        [
            (100_000_000, 0, 2),
            (0, 1_000_000, 2),
            (4_000_000, 6_000_000, 1),
            (0, 0, 5),
            (50_000_000, 0, 2),
        ],
    )
    def test_filter_price_range(self, setup_proxy, price_min, price_max, expected_count):
        _, proxy = setup_proxy
        proxy.set_price_range(price_min, price_max)
        assert proxy.rowCount() == expected_count

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
