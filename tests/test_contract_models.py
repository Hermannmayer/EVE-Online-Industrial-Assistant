"""合同数据模型测试 — ContractTableModel

使用 qapp fixture 提供 QApplication 实例。
"""

import pytest
from PySide6.QtCore import Qt

from ui_qml.models.contract_models import (
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

    # ── 字段显示 ──

    # (row, col) → 期望 DisplayRole。数值/日期/空值边界都在这一张表里 —— 任一列格式化改坏必红。
    DISPLAY = {
        (0, 0): "1001",
        (0, 1): CONTRACT_TYPE_CN["item_exchange"],
        (1, 1): CONTRACT_TYPE_CN["auction"],
        (2, 1): CONTRACT_TYPE_CN["courier"],
        (0, 2): "Tritanium Bulk",
        (4, 2): "—",  # 空标题
        (0, 3): "5,000,000.00",
        (2, 3): "—",  # 零价
        (0, 4): "1,000,000.00",
        (1, 4): "—",  # 零抵押
        (0, 5): "50,000.0",
        (0, 6): "7",
        (1, 6): "—",  # days_completed=0
        (2, 6): "3",
        (3, 6): "—",  # days_completed=None
        (4, 6): "1",
        (0, 7): CONTRACT_STATUS_CN["outstanding"],
        (0, 8): "2026-06-01 12:00:00",
        (0, 9): "2026-07-01 12:00:00",
    }

    def test_display_values(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        for (row, col), expected in self.DISPLAY.items():
            actual = model.index(row, col).data(Qt.ItemDataRole.DisplayRole)
            assert actual == expected, f"({row}, {col}) 期望 {expected!r} 得到 {actual!r}"

    # ── UserRole ──

    def test_user_role_returns_full_row(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        row = model.index(0, 0).data(Qt.ItemDataRole.UserRole)
        assert row["contract_id"] == 1001
        assert row["type"] == "item_exchange"
        assert row["price"] == 5000000.00

    # ── get_row ──

    def test_get_row(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.get_row(0)["contract_id"] == 1001
        # 越界与未填充一律 None
        assert model.get_row(-1) is None
        assert model.get_row(5) is None
        assert model.get_row(999) is None
        assert ContractTableModel().get_row(0) is None

    # ── 表头 ──

    HEADERS = {
        0: "合同ID",
        1: "类型",
        2: "标题",
        3: "价格 (ISK)",
        4: "抵押 (ISK)",
        5: "体积 (m³)",
        6: "运输天数",
        7: "状态",
        8: "签发日期",
        9: "过期日期",
    }

    def test_header_data(self, qapp):
        model = ContractTableModel()
        for section, label in self.HEADERS.items():
            assert model.headerData(section, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == label

    # ── 排序 ──

    def test_sort_by_price(self, qapp):
        model = ContractTableModel()
        # set_rows 存引用、sort 原地重排 —— 传副本，避免污染模块级 SAMPLE_CONTRACTS
        model.set_rows(list(SAMPLE_CONTRACTS))
        model.sort(3, Qt.SortOrder.DescendingOrder)
        assert model._rows[0]["contract_id"] == 1004  # 750M 最高
        model.sort(3, Qt.SortOrder.AscendingOrder)
        assert model._rows[0]["contract_id"] == 1003  # 0（零价排最后）

    def test_sort_by_title(self, qapp):
        model = ContractTableModel()
        model.set_rows(list(SAMPLE_CONTRACTS))
        model.sort(2, Qt.SortOrder.AscendingOrder)
        sorted_titles = [r["title"] for r in model._rows if r["title"]]
        assert sorted_titles == sorted(sorted_titles)

    def test_invalid_column_does_nothing(self, qapp):
        model = ContractTableModel()
        model.set_rows(list(SAMPLE_CONTRACTS))
        model.sort(99, Qt.SortOrder.AscendingOrder)
        assert model.rowCount() == 5

    # ── 样式 ──

    def test_foreground_colors(self, qapp):
        from ui_qml.theme import registry as theme

        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        expected = {
            (0, 3): theme.GREEN,  # price > 0
            (2, 3): theme.TEXT_SECONDARY,  # price = 0
            (0, 4): theme.ACCENT_ORANGE,  # collateral > 0
            (1, 4): theme.TEXT_SECONDARY,  # collateral = 0
            (0, 7): theme.GREEN,  # outstanding
            (2, 7): theme.GREEN,  # in_progress
            (3, 7): theme.RED,  # cancelled
        }
        for (row, col), color in expected.items():
            actual = model.index(row, col).data(Qt.ItemDataRole.ForegroundRole)
            assert actual.name() == color, f"({row}, {col}) 期望 {color} 得到 {actual.name()}"

    def test_background_alternating_rows(self, qapp):
        """隔行换色：偶数行 BG_SURFACE，奇数行 BG_DARK"""
        from ui_qml.theme import registry as theme

        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        bg0 = model.index(0, 0).data(Qt.ItemDataRole.BackgroundRole)
        bg1 = model.index(1, 0).data(Qt.ItemDataRole.BackgroundRole)
        assert bg0.name() == theme.BG_SURFACE
        assert bg1.name() == theme.BG_DARK

    # ── 空数据状态 ──

    def test_set_rows_replaces_data(self, qapp):
        model = ContractTableModel()
        model.set_rows(SAMPLE_CONTRACTS)
        assert model.rowCount() == 5
        model.set_rows([])
        assert model.rowCount() == 0
        model.set_rows(SAMPLE_CONTRACTS[:2])
        assert model.rowCount() == 2

    def test_column_count(self, qapp):
        """列数不随数据变化"""
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
            ("Tritanium", 1),  # 命中标题
            ("Bulk", 1),  # 子串命中
            ("tritanium", 1),  # 大小写不敏感
            ("NonExistentXYZ", 0),
            ("Ji", 1),  # 命中 "Jita → Amarr"
            ("→", 1),  # 特殊字符
            ("", 5),  # 清空恢复全部
        ],
    )
    def test_filter_by_title(self, setup_proxy, search_text, expected_count):
        _, proxy = setup_proxy
        proxy.set_search_text(search_text)
        assert proxy.rowCount() == expected_count

    @pytest.mark.parametrize(
        "price_min, price_max, expected_count",
        [
            (100_000_000, 0, 2),  # max=0 表示不限
            (0, 1_000_000, 2),  # min=0 表示不限
            (4_000_000, 6_000_000, 1),  # 闭区间只留 5M
            (0, 0, 5),  # 不限
        ],
    )
    def test_filter_price_range(self, setup_proxy, price_min, price_max, expected_count):
        _, proxy = setup_proxy
        proxy.set_price_range(price_min, price_max)
        assert proxy.rowCount() == expected_count

    @pytest.mark.parametrize(
        "buy_sell, expected_count",
        [
            ("全部", 5),
            ("我要买", 4),  # item_exchange + auction，排除 courier
            ("我要卖", 3),  # 仅 item_exchange
        ],
    )
    def test_filter_buy_sell(self, setup_proxy, buy_sell, expected_count):
        _, proxy = setup_proxy
        proxy.set_buy_sell(buy_sell)
        assert proxy.rowCount() == expected_count

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

    def test_filter_with_empty_model(self, qapp):
        model = ContractTableModel()
        proxy = ContractFilterProxy()
        proxy.setSourceModel(model)
        assert proxy.rowCount() == 0
        proxy.set_search_text("test")
        assert proxy.rowCount() == 0

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
