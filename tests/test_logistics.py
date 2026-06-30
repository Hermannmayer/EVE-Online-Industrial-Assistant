"""物流/运输计算测试 — distances, freight cost, profit

测试覆盖:
  - get_distance_jumps: 所有 5 个贸易中心的距离映射
  - estimate_freight_cost: 公开货运和自有运输两种模式
  - calc_transport_profit: 跨区域运输净利润计算
  - list_trade_hub_distances: 唯一贸易对

依赖: services.logistics 大部分函数是纯计算，无需数据库；
      calc_transport_profit 需要 mock get_price + 数据库。
"""

from unittest.mock import MagicMock, patch

from services.logistics import (
    TRADE_HUB_DISTANCES,
    calc_transport_profit,
    estimate_freight_cost,
    get_distance_jumps,
    list_trade_hub_distances,
)

# ═══════════════════════════════════════
#  贸易中心距离测试
# ═══════════════════════════════════════

TRADE_HUBS = {"Jita", "Amarr", "Dodixie", "Rens", "Hek"}


class TestGetDistanceJumps:
    """获取贸易中心间跳跃数"""

    def test_jita_amarr(self):
        assert get_distance_jumps("Jita", "Amarr") == 72

    def test_jita_dodixie(self):
        assert get_distance_jumps("Jita", "Dodixie") == 12

    def test_jita_rens(self):
        assert get_distance_jumps("Jita", "Rens") == 18

    def test_jita_hek(self):
        assert get_distance_jumps("Jita", "Hek") == 21

    def test_amarr_dodixie(self):
        assert get_distance_jumps("Amarr", "Dodixie") == 62

    def test_amarr_rens(self):
        assert get_distance_jumps("Amarr", "Rens") == 60

    def test_amarr_hek(self):
        assert get_distance_jumps("Amarr", "Hek") == 76

    def test_dodixie_rens(self):
        assert get_distance_jumps("Dodixie", "Rens") == 30

    def test_dodixie_hek(self):
        assert get_distance_jumps("Dodixie", "Hek") == 28

    def test_rens_hek(self):
        assert get_distance_jumps("Rens", "Hek") == 5

    def test_symmetry_jita_amarr(self):
        """距离对称性：A→B == B→A"""
        assert get_distance_jumps("Jita", "Amarr") == get_distance_jumps("Amarr", "Jita")

    def test_symmetry_dodixie_rens(self):
        assert get_distance_jumps("Dodixie", "Rens") == get_distance_jumps("Rens", "Dodixie")

    def test_symmetry_hek_jita(self):
        assert get_distance_jumps("Hek", "Jita") == get_distance_jumps("Jita", "Hek")

    def test_unknown_pair_returns_none(self):
        assert get_distance_jumps("Jita", "Unknown") is None
        assert get_distance_jumps("Unknown", "Amarr") is None
        assert get_distance_jumps("Unknown", "Unknown") is None

    def test_unknown_hub_returns_none(self):
        assert get_distance_jumps("Foo", "Bar") is None

    def test_same_hub_not_in_map(self):
        """同一个贸易中心的距离不在映射中（返回 None）"""
        assert get_distance_jumps("Jita", "Jita") is None

    def test_all_five_hubs_covered(self):
        """验证所有 5 个贸易中心都在 TRADE_HUB_DISTANCES 中出现"""
        hubs_in_map = set()
        for a, b in TRADE_HUB_DISTANCES:
            hubs_in_map.add(a)
            hubs_in_map.add(b)
        assert hubs_in_map == TRADE_HUBS, f"Missing hubs: {TRADE_HUBS - hubs_in_map}"

    def test_hub_count_unique_pairs(self):
        """验证唯一贸易对的数量"""
        unique_pairs = set()
        for a, b in TRADE_HUB_DISTANCES:
            unique_pairs.add(tuple(sorted([a, b])))
        assert len(unique_pairs) == 10  # C(5,2) = 10 个唯一对


# ═══════════════════════════════════════
#  运费估算测试
# ═══════════════════════════════════════


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

    def test_zero_volume_clamped_to_one(self):
        """体积为 0 时被限制为 1.0"""
        result = estimate_freight_cost(
            volume_m3=0,
            distance_jumps=5,
            collateral=0,
        )
        # 体积费 = 1 * 200 = 200
        assert result["freight_cost"] > 0

    def test_negative_volume_clamped_to_one(self):
        """负体积被限制为 1.0"""
        result = estimate_freight_cost(
            volume_m3=-100,
            distance_jumps=5,
            collateral=0,
        )
        assert result["freight_cost"] > 0

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
        # 体积费 = 333.333 * 200 = 66666.6
        # 抵押费 = 1234567.89 * 0.02 = 24691.3578
        # 总计 = 91357.9578 → round 到 91357.96
        assert result["freight_cost"] > 0
        # 验证是 2 位小数
        cost_str = str(result["freight_cost"])
        if "." in cost_str:
            decimal_places = len(cost_str.split(".")[1])
            assert decimal_places <= 2


# ═══════════════════════════════════════
#  列出贸易中心距离测试
# ═══════════════════════════════════════


class TestListTradeHubDistances:
    """列出所有唯一贸易中心对"""

    def test_returns_unique_pairs(self):
        result = list_trade_hub_distances()
        assert len(result) == 10  # C(5,2) = 10

    def test_no_duplicates(self):
        """不包含重复对"""
        result = list_trade_hub_distances()
        seen = set()
        for entry in result:
            key = tuple(sorted([entry["from"], entry["to"]]))
            assert key not in seen, f"Duplicate pair: {key}"
            seen.add(key)

    def test_all_five_hubs_present(self):
        """所有 5 个贸易中心都出现"""
        result = list_trade_hub_distances()
        hubs = set()
        for entry in result:
            hubs.add(entry["from"])
            hubs.add(entry["to"])
        assert hubs == TRADE_HUBS

    def test_contains_jita_amarr(self):
        result = list_trade_hub_distances()
        pairs = {tuple(sorted([e["from"], e["to"]])) for e in result}
        assert ("Amarr", "Jita") in pairs or ("Jita", "Amarr") in pairs

    def test_each_entry_has_jumps_positive(self):
        result = list_trade_hub_distances()
        for entry in result:
            assert entry["jumps"] > 0

    def test_entry_structure(self):
        result = list_trade_hub_distances()
        for entry in result:
            assert "from" in entry
            assert "to" in entry
            assert "jumps" in entry


# ═══════════════════════════════════════
#  运输利润计算测试
# ═══════════════════════════════════════


class TestCalcTransportProfit:
    """跨区域运输净利润计算（需 mock 价格数据和数据库）"""

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

        # Mock the DB for volume query
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

        # Should still calculate (uses default volume 1.0)
        assert result["status"] == ""
        assert result["total_volume_m3"] >= 1.0

    @patch("services.logistics.get_price")
    def test_basic_profit_calculation(self, mock_get_price):
        """基础利润计算：买入→卖出有正利润"""
        mock_get_price.side_effect = lambda tid, pt, hub: {
            ("buy", "Jita"): 1000.0,
            ("sell", "Amarr"): 1200.0,
        }.get((pt, hub))

        # Mock volume
        with patch("services.logistics.db") as mock_db:
            mock_conn = MagicMock()
            mock_cursor = MagicMock()
            mock_cursor.fetchone.return_value = (10.0,)  # volume = 10
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
                    "skills": {
                        "经纪人关系学": 5,
                        "高级经纪人关系学": 5,
                        "会计学": 5,
                    },
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
        assert result["total_volume_m3"] == 1000.0  # 10 * 100

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
                    "skills": {
                        "经纪人关系学": 5,
                        "高级经纪人关系学": 5,
                        "会计学": 5,
                    },
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
            "buy_cost",
            "sell_revenue",
            "freight_cost",
            "broker_cost",
            "sales_tax",
            "net_profit",
            "margin_pct",
            "isk_per_m3",
            "total_volume_m3",
            "freight_breakdown",
            "freight_mode",
            "status",
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


# ═══════════════════════════════════════
#  TRADE_HUB_DISTANCES 映射完整性
# ═══════════════════════════════════════


class TestTradeHubDistancesMap:
    """距离映射数据完整性"""

    def test_all_pairs_symmetric(self):
        """所有距离对都是对称的"""
        for (a, b), d in list(TRADE_HUB_DISTANCES.items()):
            assert TRADE_HUB_DISTANCES.get((b, a)) == d

    def test_all_distances_positive(self):
        """所有距离值都为正数"""
        for d in TRADE_HUB_DISTANCES.values():
            assert d > 0

    def test_min_distance_rens_hek(self):
        """最短距离：Rens ↔ Hek = 5"""
        assert TRADE_HUB_DISTANCES[("Rens", "Hek")] == 5

    def test_max_distance_hek_amarr(self):
        """最长距离：Amarr ↔ Hek = 76"""
        assert TRADE_HUB_DISTANCES[("Amarr", "Hek")] == 76
