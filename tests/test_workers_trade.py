"""贸易 Worker 线程单元测试"""

from unittest.mock import MagicMock, patch

from ui_pyside6.workers.trade_workers import (
    CrossRegionPriceWorker,
    TradeScoreWorker,
    TransportWorker,
)


class TestCrossRegionPriceWorker:
    @patch("ui_pyside6.workers.trade_workers.get_container")
    def test_run_emits_finished(self, mock_get_container, qapp):
        """run() 为每个贸易中心获取价格并通过 finished 返回"""
        mock_pricing = MagicMock()
        mock_pricing.get_price.side_effect = lambda tid, ptype, hub: {
            ("sell", "Jita"): 5.0,
            ("buy", "Jita"): 4.0,
            ("sell", "Amarr"): 6.0,
            ("buy", "Amarr"): 5.0,
            ("sell", "Dodixie"): 5.5,
            ("buy", "Dodixie"): 4.5,
            ("sell", "Rens"): 4.8,
            ("buy", "Rens"): 3.8,
        }.get((ptype, hub), 0)
        mock_pricing.get_volume.return_value = 1000
        mock_get_container.return_value.pricing_service = mock_pricing

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

    @patch("ui_pyside6.workers.trade_workers.get_container")
    def test_no_price_returns_zero(self, mock_get_container, qapp):
        """无价格数据时 spread 和 spread_pct 为 0"""
        mock_pricing = MagicMock()
        mock_pricing.get_price.return_value = None
        mock_pricing.get_volume.return_value = 0
        mock_get_container.return_value.pricing_service = mock_pricing

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
    @patch("ui_pyside6.workers.trade_workers.get_container")
    def test_run_emits_finished(self, mock_get_container, qapp):
        """run() 调用 scoring_service().calc_trade_score 并通过 finished 返回"""
        expected = {
            "status": "",
            "score": 50000.0,
            "buy_cost": 1000000.0,
            "sell_revenue": 1100000.0,
        }
        mock_svc = MagicMock()
        mock_svc.calc_trade_score.return_value = expected
        mock_get_container.return_value.scoring_service.return_value = mock_svc

        received = []

        def collect(data):
            received.append(data)

        w = TradeScoreWorker(type_id=2001, buy_hub="Jita", sell_hub="Amarr")
        w.finished.connect(collect)
        w.run()

        mock_svc.calc_trade_score.assert_called_once_with(
            type_id=2001,
            buy_hub="Jita",
            sell_hub="Amarr",
            buy_price_type="buy",
            sell_price_type="sell",
            char_config={"skills": {"工业理论": 5, "高级工业理论": 5}, "market": {}},
            quantity=1,
        )
        assert received[0]["score"] == 50000.0


class TestTransportWorker:
    @patch("ui_pyside6.workers.trade_workers.calc_transport_profit")
    def test_run_emits_finished(self, mock_calc, qapp):
        """run() 调用 calc_transport_profit 并通过 finished 返回"""
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
