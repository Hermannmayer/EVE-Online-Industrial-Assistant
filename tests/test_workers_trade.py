"""贸易 Worker 线程单元测试"""

from unittest.mock import MagicMock, patch

from PySide6.QtCore import QThread

from ui_pyside6.workers.trade_workers import (
    CrossRegionPriceWorker,
    TradeScoreWorker,
    TransportWorker,
)


class TestCrossRegionPriceWorker:
    def test_worker_construction(self):
        """CrossRegionPriceWorker 可构造，参数正确保存"""
        db = MagicMock()
        w = CrossRegionPriceWorker(type_id=2001, db=db)
        assert isinstance(w, QThread)
        assert w._tid == 2001

    @patch("ui_pyside6.workers.trade_workers.get_price")
    @patch("ui_pyside6.workers.trade_workers.get_volume")
    def test_run_emits_finished(self, mock_get_volume, mock_get_price, qapp):
        """run() 为每个贸易中心获取价格并通过 finished 返回"""
        mock_get_price.side_effect = lambda tid, ptype, hub: {
            ("sell", "Jita"): 5.0,
            ("buy", "Jita"): 4.0,
            ("sell", "Amarr"): 6.0,
            ("buy", "Amarr"): 5.0,
            ("sell", "Dodixie"): 5.5,
            ("buy", "Dodixie"): 4.5,
            ("sell", "Rens"): 4.8,
            ("buy", "Rens"): 3.8,
        }.get((ptype, hub), 0)
        mock_get_volume.return_value = 1000

        db = MagicMock()
        received = []

        def collect(data):
            received.append(data)

        w = CrossRegionPriceWorker(type_id=2001, db=db)
        w.finished.connect(collect)
        w.run()

        assert len(received) == 1
        hubs = received[0]
        assert len(hubs) == 5  # 五大贸易中心

        jita = next(h for h in hubs if h["hub"] == "Jita")
        assert jita["buy_price"] == 4.0
        assert jita["sell_price"] == 5.0
        assert jita["spread"] == 1.0
        assert jita["spread_pct"] == 25.0
        assert jita["volume"] == 1000
        assert jita["region_id"] == 10000002

        amarr = next(h for h in hubs if h["hub"] == "Amarr")
        assert amarr["region_id"] == 10000043

    @patch("ui_pyside6.workers.trade_workers.get_price")
    @patch("ui_pyside6.workers.trade_workers.get_volume")
    def test_no_price_returns_zero(self, mock_get_volume, mock_get_price, qapp):
        """无价格数据时 spread 和 spread_pct 为 0"""
        mock_get_price.return_value = None
        mock_get_volume.return_value = 0

        db = MagicMock()
        received = []

        def collect(data):
            received.append(data)

        w = CrossRegionPriceWorker(type_id=99999, db=db)
        w.finished.connect(collect)
        w.run()

        hubs = received[0]
        for h in hubs:
            assert h["buy_price"] == 0
            assert h["sell_price"] == 0
            assert h["spread"] == 0
            assert h["spread_pct"] == 0


class TestTradeScoreWorker:
    def test_worker_construction(self):
        """TradeScoreWorker 可构造，参数正确保存"""
        w = TradeScoreWorker(
            type_id=2001,
            buy_hub="Jita",
            sell_hub="Amarr",
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=10,
        )
        assert isinstance(w, QThread)
        assert w._tid == 2001
        assert w._buy_hub == "Jita"
        assert w._sell_hub == "Amarr"
        assert w._quantity == 10

    @patch("ui_pyside6.workers.trade_workers.calc_trade_score")
    def test_run_emits_finished(self, mock_calc, qapp):
        """run() 调用 calc_trade_score 并通过 finished 返回"""
        expected = {
            "status": "",
            "score": 50000.0,
            "buy_cost": 1000000.0,
            "sell_revenue": 1100000.0,
        }
        mock_calc.return_value = expected

        received = []

        def collect(data):
            received.append(data)

        w = TradeScoreWorker(type_id=2001, buy_hub="Jita", sell_hub="Amarr")
        w.finished.connect(collect)
        w.run()

        mock_calc.assert_called_once_with(
            type_id=2001,
            buy_hub="Jita",
            sell_hub="Amarr",
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=1,
        )
        assert received[0]["score"] == 50000.0


class TestTransportWorker:
    def test_worker_construction(self):
        """TransportWorker 可构造，参数正确保存"""
        w = TransportWorker(
            type_id=2001,
            buy_hub="Jita",
            sell_hub="Amarr",
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=10,
            distance_jumps=80,
            use_public_freight=True,
        )
        assert isinstance(w, QThread)
        assert w._tid == 2001
        assert w._distance_jumps == 80
        assert w._quantity == 10
        assert w._use_public_freight is True

    @patch("services.logistics.calc_transport_profit")
    def test_run_emits_finished(self, mock_calc, qapp):
        """run() 调用 calc_transport_profit（延迟导入）并通过 finished 返回"""
        expected = {
            "buy_cost": 1000000.0,
            "sell_revenue": 1200000.0,
            "freight_cost": 50000.0,
            "net_profit": 150000.0,
            "margin_pct": 15.0,
            "status": "",
        }
        mock_calc.return_value = expected

        received = []

        def collect(data):
            received.append(data)

        w = TransportWorker(
            type_id=2001,
            buy_hub="Jita",
            sell_hub="Amarr",
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=10,
            distance_jumps=80,
            char_config={"skills": {"会计学": 5}},
        )
        w.finished.connect(collect)
        w.run()

        mock_calc.assert_called_once_with(
            type_id=2001,
            buy_hub="Jita",
            sell_hub="Amarr",
            buy_price_type="buy",
            sell_price_type="sell",
            quantity=10,
            distance_jumps=80,
            use_public_freight=True,
            char_config={"skills": {"会计学": 5}},
        )
        assert received[0]["net_profit"] == 150000.0
