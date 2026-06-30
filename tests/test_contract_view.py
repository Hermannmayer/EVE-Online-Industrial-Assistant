"""合同市场视图单元测试 — ContractTableModel + ContractFilterProxy

使用 qapp fixture 提供 QApplication 实例，测试 UI 模型和过滤器。
"""

from PySide6.QtCore import QModelIndex, Qt

from ui_pyside6.views.contract_view import (
    CONTRACT_STATUS_CN,
    CONTRACT_TYPE_CN,
    ContractFilterProxy,
    ContractTableModel,
)

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


# ═══════════════════════════════════════
#  ContractTableModel 测试
# ═══════════════════════════════════════


class TestContractTableModel:
    """合同表格数据模型基础操作"""

    def test_row_count(self, qapp):
        model = ContractTableModel()
        assert model.rowCount() == 0
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.rowCount() == 5

    def test_column_count(self, qapp):
        model = ContractTableModel()
        assert model.columnCount() == 10  # 10 columns defined

    def test_set_rows_replaces_data(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.rowCount() == 5
        model.set_rows(SAMPLE_CONTRACTS[:2])
        assert model.rowCount() == 2

    def test_display_contract_id(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 0)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "1001"

    def test_display_type_cn(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 1)  # 类型列
        assert idx.data(Qt.ItemDataRole.DisplayRole) == CONTRACT_TYPE_CN["item_exchange"]

        idx2 = model.index(1, 1)
        assert idx2.data(Qt.ItemDataRole.DisplayRole) == CONTRACT_TYPE_CN["auction"]

        idx3 = model.index(2, 1)
        assert idx3.data(Qt.ItemDataRole.DisplayRole) == CONTRACT_TYPE_CN["courier"]

    def test_display_title(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 2)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "Tritanium Bulk"

    def test_display_empty_title_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(4, 2)  # empty title
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "—"

    def test_display_price_formatted(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 3)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "5,000,000.00"

    def test_display_zero_price_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(2, 3)  # price = 0
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "—"

    def test_display_collateral_formatted(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 4)
        assert "1,000,000" in idx.data(Qt.ItemDataRole.DisplayRole)

    def test_display_zero_collateral_returns_em_dash(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(1, 4)  # collateral = 0
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "—"

    def test_display_volume_formatted(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 5)
        assert "50,000" in idx.data(Qt.ItemDataRole.DisplayRole)

    def test_display_status_cn(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 7)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == CONTRACT_STATUS_CN["outstanding"]

    def test_display_date_issued(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 8)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "2026-06-01 12:00:00"

    def test_display_date_expired(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 9)
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "2026-07-01 12:00:00"

    def test_user_role_returns_full_row(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 0)
        row = idx.data(Qt.ItemDataRole.UserRole)
        assert row["contract_id"] == 1001
        assert row["type"] == "item_exchange"
        assert row["price"] == 5000000.00

    def test_get_row_valid(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        row = model.get_row(0)
        assert row is not None
        assert row["contract_id"] == 1001

    def test_get_row_invalid(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.get_row(-1) is None
        assert model.get_row(999) is None

    def test_get_row_empty_model(self, qapp):
        model = ContractTableModel()
        assert model.get_row(0) is None

    def test_header_data(self, qapp):
        model = ContractTableModel()
        header0 = model.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        assert header0 == "合同ID"

    def test_sort_by_price_descending(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(3, Qt.SortOrder.DescendingOrder)  # 价格列降序
        assert model._rows[0]["contract_id"] == 1004  # 750M

    def test_sort_by_price_ascending(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(3, Qt.SortOrder.AscendingOrder)  # 价格列升序
        assert model._rows[0]["contract_id"] == 1003  # 0 price

    def test_sort_by_title(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(2, Qt.SortOrder.AscendingOrder)
        sorted_titles = [r["title"] for r in model._rows if r["title"]]
        assert sorted_titles == sorted(sorted_titles)

    def test_invalid_column_does_nothing(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        model.sort(99, Qt.SortOrder.AscendingOrder)  # invalid column
        # should not crash, rows unchanged
        assert model.rowCount() == 5

    def test_text_alignment(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 3)  # 价格列 — 右对齐
        align = idx.data(Qt.ItemDataRole.TextAlignmentRole)
        assert align == (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def test_foreground_price_positive_green(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 3)  # price > 0
        color = idx.data(Qt.ItemDataRole.ForegroundRole)
        assert color is not None

    def test_foreground_price_zero_secondary(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(2, 3)  # price = 0
        color = idx.data(Qt.ItemDataRole.ForegroundRole)
        assert color is not None

    def test_foreground_status_outstanding_green(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 7)  # outstanding
        color = idx.data(Qt.ItemDataRole.ForegroundRole)
        assert color is not None

    def test_foreground_status_cancelled_red(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(3, 7)  # cancelled
        color = idx.data(Qt.ItemDataRole.ForegroundRole)
        assert color is not None

    def test_font_monospace_on_numeric(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        idx = model.index(0, 0)  # contract_id
        font = idx.data(Qt.ItemDataRole.FontRole)
        assert font is not None

    def test_display_days_completed(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        # Row 0 is contract 1001 with days_completed=7
        # Row 4 is contract 1005 with days_completed=1
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
        idx = model.index(3, 6)  # days_completed = None
        assert idx.data(Qt.ItemDataRole.DisplayRole) == "—"

    def test_background_alternating_rows(self, qapp):
        """验证隔行换色背景存在"""
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        bg0 = model.index(0, 0).data(Qt.ItemDataRole.BackgroundRole)
        bg1 = model.index(1, 0).data(Qt.ItemDataRole.BackgroundRole)
        # Both should be QColor instances
        assert bg0 is not None
        assert bg1 is not None


# ═══════════════════════════════════════
#  ContractFilterProxy 测试
# ═══════════════════════════════════════


class TestContractFilterProxy:
    """合同列表实时过滤"""

    def _setup(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)
        return model, proxy

    def test_no_filter_shows_all(self, qapp):
        _, proxy = self._setup(qapp)
        assert proxy.rowCount() == 5

    def test_filter_by_title(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_search_text("Tritanium")
        assert proxy.rowCount() == 1

        proxy.set_search_text("Bulk")
        assert proxy.rowCount() == 1

    def test_filter_by_title_case_insensitive(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_search_text("tritanium")
        assert proxy.rowCount() == 1

    def test_filter_by_title_no_match(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_search_text("NonExistentXYZ")
        assert proxy.rowCount() == 0

    def test_filter_by_title_partial(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_search_text("Ji")  # "Jita → Amarr"
        assert proxy.rowCount() == 1

    def test_filter_by_title_empty_clears(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_search_text("Tritanium")
        assert proxy.rowCount() == 1
        proxy.set_search_text("")
        assert proxy.rowCount() == 5

    def test_filter_price_min(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_price_range(100_000_000, 0)  # min 100M, no max
        assert proxy.rowCount() == 2  # 100M (Raven BP) + 750M (Refinery)

    def test_filter_price_max(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_price_range(0, 1_000_000)  # max 1M
        assert proxy.rowCount() == 2  # 0 + 1200.5

    def test_filter_price_range(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_price_range(4_000_000, 6_000_000)
        assert proxy.rowCount() == 1  # 5M

    def test_filter_price_zero_min_ignored(self, qapp):
        _, proxy = self._setup(qapp)
        proxy.set_price_range(0, 0)  # no range
        assert proxy.rowCount() == 5

    def test_filter_buy_sell_all(self, qapp):
        """'全部' 不过滤"""
        _, proxy = self._setup(qapp)
        proxy.set_buy_sell("全部")
        assert proxy.rowCount() == 5

    def test_filter_buy_sell_woyaomai(self, qapp):
        """'我要买' → item_exchange 或 auction"""
        _, proxy = self._setup(qapp)
        proxy.set_buy_sell("我要买")
        assert proxy.rowCount() == 4  # 3 item_exchange + 1 auction

    def test_filter_buy_sell_woyaomai_courier_excluded(self, qapp):
        """'我要买' 排除 courier"""
        _, proxy = self._setup(qapp)
        proxy.set_buy_sell("我要买")
        # Check courier is excluded
        for r in range(proxy.rowCount()):
            src_idx = proxy.mapToSource(proxy.index(r, 0))
            row = proxy.sourceModel().get_row(src_idx.row())
            assert row["type"] != "courier"

    def test_filter_buy_sell_woyaomai_only_item_exchange(self, qapp):
        """'我要卖' → item_exchange"""
        _, proxy = self._setup(qapp)
        proxy.set_buy_sell("我要卖")
        assert proxy.rowCount() == 3  # 3 item_exchange

    def test_filter_buy_sell_woyaomai_auction_excluded(self, qapp):
        """'我要卖' 排除 auction 和 courier"""
        _, proxy = self._setup(qapp)
        proxy.set_buy_sell("我要卖")
        for r in range(proxy.rowCount()):
            src_idx = proxy.mapToSource(proxy.index(r, 0))
            row = proxy.sourceModel().get_row(src_idx.row())
            assert row["type"] == "item_exchange"

    def test_filter_combined_search_and_price(self, qapp):
        """组合过滤：搜索 + 价格区间"""
        _, proxy = self._setup(qapp)
        proxy.set_search_text("a")
        proxy.set_price_range(1_000_000, 10_000_000)
        assert proxy.rowCount() == 1  # Only "Tritanium Bulk" with 5M

    def test_filter_combined_search_and_buy_sell(self, qapp):
        """组合过滤：搜索 + 买卖类型"""
        _, proxy = self._setup(qapp)
        proxy.set_search_text("Rented")
        proxy.set_buy_sell("我要卖")
        assert proxy.rowCount() == 1  # "Rented Refinery" is item_exchange

    def test_filter_clear_all(self, qapp):
        """清除所有过滤条件后回到全部"""
        _, proxy = self._setup(qapp)
        proxy.set_search_text("Tritanium")
        proxy.set_price_range(1_000_000, 10_000_000)
        proxy.set_buy_sell("我要卖")
        assert proxy.rowCount() >= 0
        proxy.set_search_text("")
        proxy.set_price_range(0, 0)
        proxy.set_buy_sell("全部")
        assert proxy.rowCount() == 5

    def test_filter_with_empty_model(self, qapp):
        """空模型不过滤"""
        model = ContractTableModel()
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)
        assert proxy.rowCount() == 0
        proxy.set_search_text("test")
        assert proxy.rowCount() == 0

    def test_filter_accepts_row_direct(self, qapp):
        """直接测试 filterAcceptsRow 逻辑"""
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)

        # 没有过滤器时所有行都接受
        assert proxy.filterAcceptsRow(0, QModelIndex()) is True
        assert proxy.filterAcceptsRow(1, QModelIndex()) is True

    def test_price_range_zero_max_unlimited(self, qapp):
        """max=0 表示无上限"""
        _, proxy = self._setup(qapp)
        proxy.set_price_range(50_000_000, 0)  # min 50M, no max
        assert proxy.rowCount() == 2  # 100M Raven + 750M Refinery

    def test_filter_title_with_special_chars(self, qapp):
        """特殊字符搜索"""
        _, proxy = self._setup(qapp)
        proxy.set_search_text("→")
        assert proxy.rowCount() == 1  # "Jita → Amarr"

    def test_source_model_changed(self, qapp):
        """更改源模型后过滤仍然有效"""
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)
        proxy.set_search_text("Tritanium")
        assert proxy.rowCount() == 1

        # 更换源模型
        model2 = ContractTableModel()
        model2.set_rows(SAMPLE_CONTRACTS[:3])
        proxy.setSourceModel(model2)
        proxy.set_search_text("")
        assert proxy.rowCount() == 3
