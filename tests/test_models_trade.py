"""贸易 Table Model 单元测试 — ui_pyside6/models/trade_models.py

测试覆盖:
  - TradeHubTableModel 构造与维度
  - 表头数据
  - 数据显示格式
  - 价差前景色（正/负/零）
  - 图标 DecorationRole
"""

from unittest.mock import patch

from PySide6.QtCore import QModelIndex, Qt

from ui_pyside6.models.trade_models import TradeHubTableModel


class TestTradeHubTableModel:
    """TradeHubTableModel — 跨区域价格对比表模型"""

    def test_construction(self):
        """可构造，行数列数正确"""
        rows = [
            {"hub": "Jita", "buy_price": 4.0, "sell_price": 5.0, "spread": 1.0, "spread_pct": 25.0, "volume": 1000000},
        ]
        model = TradeHubTableModel(rows)
        assert model.rowCount() == 1
        assert model.columnCount() == 6

        # 空数据
        empty = TradeHubTableModel([])
        assert empty.rowCount() == 0
        assert empty.columnCount() == 6

    def test_header_data(self):
        """表头文字正确"""
        model = TradeHubTableModel([])
        headers = ["贸易中心", "买价", "卖价", "价差", "价差%", "成交量"]
        for i, expected in enumerate(headers):
            actual = model.headerData(i, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            assert actual == expected

        # 垂直表头返回 None
        assert model.headerData(0, Qt.Orientation.Vertical) is None

    def test_data_display_format(self, qapp):
        """各列 DisplayRole 格式化正确"""
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
        idx = model.index(0, 0)
        assert model.data(idx, Qt.ItemDataRole.DisplayRole) == "Jita"
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole) == "4.12"
        assert model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole) == "5.68"
        assert model.data(model.index(0, 3), Qt.ItemDataRole.DisplayRole) == "1.56"
        assert model.data(model.index(0, 4), Qt.ItemDataRole.DisplayRole) == "37.7%"
        assert model.data(model.index(0, 5), Qt.ItemDataRole.DisplayRole) == "1,000,000"

        # 字段缺失回退
        sparse = TradeHubTableModel([{}])
        assert sparse.data(sparse.index(0, 0), Qt.ItemDataRole.DisplayRole) == ""

    def test_data_foreground_spread(self, qapp):
        """价差百分比列前景色：正→绿色，负→红色，零→None"""
        from ui_pyside6 import theme

        # 正价差 → ACCENT_GREEN
        pos = TradeHubTableModel([{"hub": "Jita", "spread_pct": 15.0}])
        color = pos.data(pos.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color is not None
        assert color.name() == theme.ACCENT_GREEN

        # 负价差 → ACCENT_RED
        neg = TradeHubTableModel([{"hub": "Jita", "spread_pct": -5.0}])
        color = neg.data(neg.index(0, 4), Qt.ItemDataRole.ForegroundRole)
        assert color is not None
        assert color.name() == theme.ACCENT_RED

        # 零价差 → None
        zero = TradeHubTableModel([{"hub": "Jita", "spread_pct": 0}])
        assert zero.data(zero.index(0, 4), Qt.ItemDataRole.ForegroundRole) is None

        # 其他列 ForegroundRole 返回 None
        assert pos.data(pos.index(0, 0), Qt.ItemDataRole.ForegroundRole) is None

    def test_data_decoration_icon(self, qapp):
        """第一列 DecorationRole：有图标返回 QPixmap，无图标/无 type_id 返回 None"""
        rows = [{"hub": "Jita", "type_id": 2001}]
        model = TradeHubTableModel(rows)

        # 图标文件存在 → 返回 QPixmap
        with patch("ui_pyside6.models.trade_models.os.path.exists") as mock_exists:
            with patch("ui_pyside6.models.trade_models.QPixmap") as mock_pix:
                mock_exists.return_value = True
                mock_pix_instance = mock_pix.return_value
                mock_pix_instance.isNull.return_value = False
                result = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
                assert result is not None

        # 图标文件不存在 → 返回 None
        with patch("ui_pyside6.models.trade_models.os.path.exists") as mock_exists:
            mock_exists.return_value = False
            result = model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)
            assert result is None

        # type_id 缺失 → 返回 None
        no_type = TradeHubTableModel([{"hub": "Jita"}])
        assert no_type.data(no_type.index(0, 0), Qt.ItemDataRole.DecorationRole) is None

        # 非第一列 DecorationRole → None
        assert model.data(model.index(0, 1), Qt.ItemDataRole.DecorationRole) is None

        # 无效索引 → None
        assert model.data(QModelIndex(), Qt.ItemDataRole.DecorationRole) is None
