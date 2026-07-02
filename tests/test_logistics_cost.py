"""物流运费和运输利润计算测试

测试覆盖:
  - estimate_freight_cost: 公开货运和自有运输两种模式
  - calc_transport_profit: 跨区域运输净利润计算（价格/体积 mock）

依赖: services.logistics 纯计算函数，calc_transport_profit 需要 mock 数据库。
"""

from unittest.mock import MagicMock, patch

import pytest

from services.logistics import calc_transport_profit, estimate_freight_cost

# ═══════════════════════════════════════════════════════
#  运费估算
# ═══════════════════════════════════════════════════════


class TestEstimateFreightCost:
    """货运费用估算"""

    def test_public_freight_default(self):
        """公开货运模式：体积费 + 抵押附加费"""
        result = estimate_freight_cost(
            volume_m3=1000,
            distance_jumps=10,
            collateral=10_000_000,
        )
        assert result["mode"] == "public_freight"
        # 体积费 = 1000 * 200 = 200000
        # 抵押附加费 = 10M * 0.02 = 200000
        assert result["freight_cost"] == 400000.0
        assert result["total_cost"] == 400000.0
        assert result["collateral_fee"] == 200000.0
        assert result["fuel_cost"] == 0.0

    def test_self_transport(self):
        """自有运输模式：燃料成本"""
        result = estimate_freight_cost(
            volume_m3=1000,
            distance_jumps=10,
            collateral=10_000_000,
            use_public_freight=False,
        )
        assert result["mode"] == "self_transport"
        # 燃料成本 = 500000 * 10 = 5000000
        assert result["freight_cost"] == 5_000_000.0
        assert result["total_cost"] == 5_000_000.0
        assert result["collateral_fee"] == 0.0
        assert result["fuel_cost"] == 5_000_000.0

    @pytest.mark.parametrize("volume, expected_cost, desc", [
        (0, 200.0, "clamped to 1.0 * 200 = 200"),
        (-100, 200.0, "negative clamped to 1.0 * 200 = 200"),
    ])
    def test_extreme_volume_clamped(self, volume, expected_cost, desc):
        """体积为 0 或负数时被限制为 1.0"""
        result = estimate_freight_cost(
            volume_m3=volume,
            distance_jumps=5,
            collateral=0,
        )
        assert result["freight_cost"] == expected_cost

    def test_zero_distance_clamped_to_one(self):
        """距离为 0 时被限制为 1（自有运输）"""
        result = estimate_freight_cost(
            volume_m3=100,
            distance_jumps=0,
            collateral=0,
            use_public_freight=False,
        )
        # 燃料成本 = 500000 * 1 = 500000
        assert result["freight_cost"] == 500_000.0

    def test_public_freight_collateral_components(self):
        """公开货运的明细结构正确"""
        result = estimate_freight_cost(
            volume_m3=5000,
            distance_jumps=20,
            collateral=50_000_000,
        )
        bd = result["breakdown"]
        assert "volume_fee" in bd
        assert "collateral_pct" in bd
        assert "collateral_fee" in bd
        assert "price_per_m3" in bd
        assert bd["price_per_m3"] == 200
        assert bd["collateral_pct"] == 2.0

    def test_self_transport_breakdown(self):
        """自有运输的明细结构正确"""
        result = estimate_freight_cost(
            volume_m3=100,
            distance_jumps=15,
            collateral=0,
            use_public_freight=False,
        )
        bd = result["breakdown"]
        assert "price_per_jump" in bd
        assert "fuel_cost" in bd
        assert bd["price_per_jump"] == 500_000

    def test_custom_freight_rate(self):
        """自定义费率"""
        result = estimate_freight_cost(
            volume_m3=1000,
            distance_jumps=10,
            collateral=0,
            price_per_m3=500,
            use_public_freight=True,
        )
        # 体积费 = 1000 * 500 = 500000
        assert result["freight_cost"] == 500_000.0

    def test_custom_jump_cost(self):
        """自定义每跳燃料成本"""
        result = estimate_freight_cost(
            volume_m3=100,
            distance_jumps=10,
            collateral=0,
            price_per_jump=1_000_000,
            use_public_freight=False,
        )
        assert result["freight_cost"] == 10_000_000.0

    def test_high_collateral(self):
        """高抵押价值下的附加费"""
        result = estimate_freight_cost(
            volume_m3=100,
            distance_jumps=5,
            collateral=1_000_000_000,  # 1B
        )
        # 抵押附加费 = 1B * 0.02 = 20M
        assert result["collateral_fee"] == 20_000_000.0

    def test_large_volume(self):
        """大体积运费"""
        result = estimate_freight_cost(
            volume_m3=1_000_000,
            distance_jumps=10,
            collateral=0,
        )
        # 体积费 = 1M * 200 = 200M
        assert result["freight_cost"] == 200_000_000.0

    def test_rounding(self):
        """运费精确到 2 位小数"""
        result = estimate_freight_cost(
            volume_m3=333.333,
            distance_jumps=7,
            collateral=1234567.89,
        )
        cost_str = str(result["freight_cost"])
        if "." in cost_str:
            decimal_places = len(cost_str.split(".")[1])
            assert decimal_places <= 2

    def test_zero_collateral_public_freight(self):
        """零抵押时抵押附加费为 0"""
        result = estimate_freight_cost(
            volume_m3=100,
            distance_jumps=10,
            collateral=0,
            use_public_freight=True,
        )
        assert result["collateral_fee"] == 0.0
        assert result["freight_cost"] == 20_000.0  # 100 * 200

    def test_very_small_volume(self):
        """极小体积（<1 m³）时按实际体积计算"""
        result = estimate_freight_cost(
            volume_m3=0.01,
            distance_jumps=5,
            collateral=0,
            use_public_freight=True,
        )
        assert result["freight_cost"] == 2.0  # 0.01 * 200

    def test_custom_m3_rate_zero_collateral(self):
        """自定义 m³ 费率 + 零抵押"""
        result = estimate_freight_cost(
            volume_m3=1_000,
            distance_jumps=10,
            collateral=0,
            price_per_m3=1_000,
            use_public_freight=True,
        )
        assert result["freight_cost"] == 1_000_000.0  # 1000 * 1000

    def test_negative_collateral(self):
        """负抵押产生负附加费（代码不取绝对值）"""
        result = estimate_freight_cost(
            volume_m3=100,
            distance_jumps=5,
            collateral=-10_000_000,
        )
        assert result["collateral_fee"] == -200_000.0

    def test_breakdown_includes_mode(self):
        """结果中包含 mode 字段"""
        r1 = estimate_freight_cost(100, 10, 0, use_public_freight=True)
        assert r1["mode"] == "public_freight"
        r2 = estimate_freight_cost(100, 10, 0, use_public_freight=False)
        assert r2["mode"] == "self_transport"


# ═══════════════════════════════════════════════════════
#  运输利润计算
# ═══════════════════════════════════════════════════════


class TestCalcTransportProfit:
    """跨区域运输净利润计算（需 mock 价格数据和数据库）"""

    # ── 通用参数：不同场景的价格/体积数据 ──
    _SCENARIOS = {
        "basic_profit": {
            "prices": {("buy", "Jita"): 1000.0, ("sell", "Amarr"): 1200.0},
            "volume": 10.0,
        },
        "sell_lower": {
            "prices": {("buy", "Jita"): 1000.0, ("sell", "Amarr"): 900.0},
            "volume": 5.0,
        },
        "zero_standing": {
            "prices": {("buy", "Jita"): 5000.0, ("sell", "Dodixie"): 5500.0},
            "volume": 10.0,
        },
        "sell_as_buy": {
            "prices": {("sell", "Jita"): 5000.0, ("sell", "Amarr"): 5500.0},
            "volume": 5.0,
        },
        "short_route": {
            "prices": {("buy", "Hek"): 100.0, ("sell", "Rens"): 110.0},
            "volume": 1.0,
        },
        "field_check": {
            "prices": {("buy", "Jita"): 500.0, ("sell", "Amarr"): 600.0},
            "volume": 2.0,
        },
    }

    def _mock_scenario(self, scenario_name, mock_get_price, extra_kwargs=None):
        """辅助方法：mock 指定场景的价格和数据库"""
        scenario = self._SCENARIOS[scenario_name]
        mock_get_price.side_effect = lambda tid, pt, hub: scenario["prices"].get((pt, hub))

        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (scenario["volume"],)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            return calc_transport_profit(
                type_id=1001,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=1,
                distance_jumps=72,
                **(extra_kwargs or {}),
            )

    def test_no_price_returns_status(self):
        """无价格数据时返回 no_price 状态"""
        with patch("services.logistics.get_price", return_value=None):
            result = calc_transport_profit(
                type_id=99999,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=1,
                distance_jumps=72,
            )
        assert result["status"] == "no_price"

    @patch("services.logistics.get_price")
    def test_no_volume_returns_default(self, mock_get_price):
        """物品无体积数据时使用 1.0 默认值"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 100.0,
            ("sell", "Amarr"): 150.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = None  # No volume found
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=999,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=1,
                distance_jumps=72,
            )
        assert result["status"] == ""
        assert result["total_volume_m3"] >= 1.0

    @patch("services.logistics.get_price")
    def test_basic_profit_calculation(self, mock_get_price):
        """基础利润计算：买入→卖出有正利润"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 1000.0,
            ("sell", "Amarr"): 1200.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (10.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1001,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=100,
                distance_jumps=72,
                char_config={
                    "skills": {"经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5},
                    "market": {
                        "jita": {"faction_standing": 6.7, "corp_standing": 5.0},
                        "amarr": {"faction_standing": 6.7, "corp_standing": 5.0},
                    },
                },
            )
        assert result["status"] == ""
        assert result["buy_cost"] > 0
        assert result["sell_revenue"] > 0
        assert result["net_profit"] != 0
        assert result["freight_cost"] > 0
        assert result["total_volume_m3"] == 1000.0

    @patch("services.logistics.get_price")
    def test_profit_negative_when_sell_lower(self, mock_get_price):
        """卖价低于买价时利润为负"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 1000.0,
            ("sell", "Amarr"): 900.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (5.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1001,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=10,
                distance_jumps=72,
                char_config={
                    "skills": {"经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5},
                    "market": {
                        "jita": {"faction_standing": 6.7, "corp_standing": 5.0},
                        "amarr": {"faction_standing": 6.7, "corp_standing": 5.0},
                    },
                },
            )
        assert result["status"] == ""
        assert result["net_profit"] < 0

    @patch("services.logistics.get_price")
    def test_result_fields_present(self, mock_get_price):
        """返回结果包含所有必需字段"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 500.0,
            ("sell", "Amarr"): 600.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (2.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1002,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=5,
                distance_jumps=72,
            )
        required = [
            "buy_cost", "sell_revenue", "freight_cost", "broker_cost",
            "sales_tax", "net_profit", "margin_pct", "isk_per_m3",
            "total_volume_m3", "freight_breakdown", "freight_mode", "status",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"

    @patch("services.logistics.get_price")
    def test_self_transport_mode(self, mock_get_price):
        """自有运输模式的计算"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 1000.0,
            ("sell", "Dodixie"): 1100.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (1.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1001,
                buy_hub="Jita",
                sell_hub="Dodixie",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=1,
                distance_jumps=12,
                use_public_freight=False,
            )
        assert result["freight_mode"] == "self_transport"
        assert result["freight_cost"] > 0

    @patch("services.logistics.get_price")
    def test_zero_standing_values(self, mock_get_price):
        """所有声望为 0 时仍正常计算"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 5000.0,
            ("sell", "Dodixie"): 5500.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (10.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1001,
                buy_hub="Jita",
                sell_hub="Dodixie",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=1,
                distance_jumps=12,
                char_config={
                    "skills": {},
                    "market": {
                        "jita": {"faction_standing": 0.0, "corp_standing": 0.0},
                        "dodixie": {"faction_standing": 0.0, "corp_standing": 0.0},
                    },
                },
            )
        assert result["status"] == ""
        assert result["freight_cost"] > 0
        assert result["broker_cost"] > 0

    @patch("services.logistics.get_price")
    def test_sell_price_as_buy_type(self, mock_get_price):
        """使用卖价作为买入价（即买断）"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("sell", "Jita"): 5000.0,
            ("sell", "Amarr"): 5500.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (5.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1001,
                buy_hub="Jita",
                sell_hub="Amarr",
                buy_price_type="sell",
                sell_price_type="sell",
                quantity=10,
                distance_jumps=72,
                char_config={
                    "skills": {"经纪人关系学": 5, "高级经纪人关系学": 5, "会计学": 5},
                    "market": {
                        "jita": {"faction_standing": 6.7, "corp_standing": 5.0},
                        "amarr": {"faction_standing": 6.7, "corp_standing": 5.0},
                    },
                },
            )
        assert result["status"] == ""
        assert result["buy_cost"] > 0
        assert result["sell_revenue"] > 0

    @patch("services.logistics.get_price")
    def test_hek_to_rens_short_route(self, mock_get_price):
        """短距离路线（Hek→Rens 5 跳）"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Hek"): 100.0,
            ("sell", "Rens"): 110.0,
        }.get((pt, hub))
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (1.0,)
            mock_conn.cursor.return_value = mock_cursor
            mock_db.connect.return_value.__enter__.return_value = mock_conn
            result = calc_transport_profit(
                type_id=1001,
                buy_hub="Hek",
                sell_hub="Rens",
                buy_price_type="buy",
                sell_price_type="sell",
                quantity=1,
                distance_jumps=5,
                use_public_freight=False,
            )
        assert result["freight_mode"] == "self_transport"
        assert result["freight_cost"] == 2_500_000.0
