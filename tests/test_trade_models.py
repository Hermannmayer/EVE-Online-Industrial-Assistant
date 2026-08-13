"""贸易 Table Model 单元测试 — ui_pyside6/models/trade_models.py

测试覆盖:
  - TradeHubTableModel: 跨区域价格对比表模型
"""

from unittest.mock import MagicMock, patch

from PySide6.QtCore import QModelIndex, Qt

from ui_pyside6.models.trade_models import TradeHubTableModel


class TestTradeHubTableModel:
    def test_construction(self):
        """可构造，行数列数正确"""
        rows = [
            {"hub": "Jita", "buy_price": 4.0, "sell_price": 5.0, "spread": 1.0, "spread_pct": 25.0, "volume": 1000000},
        ]
        model = TradeHubTableModel(rows)
        assert model.rowCount() == 1
        assert model.columnCount() == 6

    def test_empty_rows(self):
        """空数据构造"""
        model = TradeHubTableModel([])
        assert model.rowCount() == 0
        assert model.columnCount() == 6

    def test_header_data(self, qapp):
        """表头正确"""
        model = TradeHubTableModel([])
        headers = ["贸易中心", "买价", "卖价", "价差", "价差%", "成交量"]
        for i, h in enumerate(headers):
            assert model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) == h

    def test_data_display(self, qapp):
        """数据展示格式正确"""
        rows = [
            {
                "hub": "Jita",
                "buy_price": 4.1234,
                "sell_price": 5.6789,
                "spread": 1.5555,
                "spread_pct": 37.7,
                "volume": 1000000,
            },
        ]
        model = TradeHubTableModel(rows)
        assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "Jita"
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "4.12"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "5.68"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "1.56"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "37.7%"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "1,000,000"

    def test_data_foreground_spread_positive(self, qapp):
        """价差为正时绿色"""
        from ui_pyside6 import theme

        rows = [{"hub": "Jita", "spread_pct": 15.0}]
        model = TradeHubTableModel(rows)
        color = model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.ACCENT_GREEN

    def test_data_foreground_spread_negative(self, qapp):
        """价差为负时红色"""
        from ui_pyside6 import theme

        rows = [{"hub": "Jita", "spread_pct": -5.0}]
        model = TradeHubTableModel(rows)
        color = model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == theme.ACCENT_RED

    def test_data_foreground_spread_zero(self, qapp):
        """价差为 0 时无色"""
        rows = [{"hub": "Jita", "spread_pct": 0}]
        model = TradeHubTableModel(rows)
        assert model.data(model.index(0, 4), Qt.ItemDataRole.ForegroundRole) is None

    def test_data_decoration_icon_exists(self, qapp):
        """有图标文件时 DecorationRole 返回 QPixmap"""
        rows = [{"hub": "Jita", "type_id": 2001}]
        model = TradeHubTableModel(rows)

        with patch("ui_pyside6.models.trade_models.load_item_icon", return_value=MagicMock()):
            result = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
            assert result is not None

    def test_data_decoration_no_icon(self, qapp):
        """无图标文件时 DecorationRole 返回 None"""
        rows = [{"hub": "Jita", "type_id": 99999}]
        model = TradeHubTableModel(rows)

        with patch("ui_pyside6.models.trade_models.load_item_icon", return_value=None):
            result = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
            assert result is None

    def test_data_decoration_no_type_id(self, qapp):
        """type_id 缺失时 DecorationRole 返回 None"""
        rows = [{"hub": "Jita"}]
        model = TradeHubTableModel(rows)
        result = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
        assert result is None

    def test_invalid_index_returns_none(self, qapp):
        """无效索引返回 None"""
        model = TradeHubTableModel([])
        assert model.data(QModelIndex(), Qt.ItemDataRole.DisplayRole) is None

    def test_multiple_rows(self, qapp):
        """多行数据"""
        rows = [
            {"hub": "Jita", "buy_price": 4.0, "sell_price": 5.0, "spread": 1.0, "spread_pct": 25.0, "volume": 1000000},
            {"hub": "Amarr", "buy_price": 5.0, "sell_price": 6.0, "spread": 1.0, "spread_pct": 20.0, "volume": 500000},
        ]
        model = TradeHubTableModel(rows)
        assert model.rowCount() == 2
        assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == "Amarr"
