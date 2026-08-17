"""物流距离计算测试 — 贸易中心间跳跃距离映射

测试覆盖:
  - get_distance_jumps: 所有 5 个贸易中心的距离映射（参数化）
  - list_trade_hub_distances: 唯一贸易对（参数化验证）
  - TRADE_HUB_DISTANCES 映射完整性

依赖: services.logistics 纯计算函数，无需数据库。
"""

import pytest

from services.logistics import TRADE_HUB_DISTANCES, get_distance_jumps, list_trade_hub_distances

pytestmark = pytest.mark.fast

TRADE_HUBS = {"Jita", "Amarr", "Dodixie", "Rens", "Hek"}

# ── 参数化数据集 ──

KNOWN_DISTANCES = [
    ("Jita", "Amarr", 72),
    ("Jita", "Dodixie", 12),
    ("Jita", "Rens", 18),
    ("Jita", "Hek", 21),
    ("Amarr", "Dodixie", 62),
    ("Amarr", "Rens", 60),
    ("Amarr", "Hek", 76),
    ("Dodixie", "Rens", 30),
    ("Dodixie", "Hek", 28),
    ("Rens", "Hek", 5),
]

SYMMETRY_PAIRS = [
    ("Jita", "Amarr"),
    ("Dodixie", "Rens"),
    ("Hek", "Jita"),
    ("Rens", "Hek"),
    ("Amarr", "Dodixie"),
]

UNKNOWN_PAIRS = [
    ("Jita", "Unknown"),
    ("Unknown", "Amarr"),
    ("Unknown", "Unknown"),
    ("Foo", "Bar"),
]


# ═══════════════════════════════════════════════════════
#  跳跃数计算
# ═══════════════════════════════════════════════════════


class TestGetDistanceJumps:
    """获取贸易中心间跳跃数"""

    @pytest.mark.parametrize("hub_a, hub_b, expected", KNOWN_DISTANCES)
    def test_known_distances(self, hub_a, hub_b, expected):
        assert get_distance_jumps(hub_a, hub_b) == expected

    @pytest.mark.parametrize("hub_a, hub_b", SYMMETRY_PAIRS)
    def test_symmetry(self, hub_a, hub_b):
        assert get_distance_jumps(hub_a, hub_b) == get_distance_jumps(hub_b, hub_a)

    @pytest.mark.parametrize("hub_a, hub_b", UNKNOWN_PAIRS)
    def test_unknown_pair_returns_none(self, hub_a, hub_b):
        assert get_distance_jumps(hub_a, hub_b) is None

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

    @pytest.mark.parametrize(
        "hub, expected_pairs",
        [
            ("Hek", [("Hek", "Rens", 5), ("Hek", "Jita", 21), ("Hek", "Dodixie", 28), ("Hek", "Amarr", 76)]),
        ],
    )
    def test_hek_to_all_hubs(self, hub, expected_pairs):
        """Hek 到其他 4 个贸易中心的距离"""
        for h, other, expected in expected_pairs:
            assert get_distance_jumps(h, other) == expected, f"Expected {h}→{other} = {expected}"


# ═══════════════════════════════════════════════════════
#  列出唯一贸易对
# ═══════════════════════════════════════════════════════


class TestListTradeHubDistances:
    """列出所有唯一贸易中心对"""

    def test_returns_unique_pairs(self):
        result = list_trade_hub_distances()
        assert len(result) == 10  # C(5,2) = 10

    def test_no_duplicates(self):
        result = list_trade_hub_distances()
        seen = set()
        for entry in result:
            key = tuple(sorted([entry["from"], entry["to"]]))
            assert key not in seen, f"Duplicate pair: {key}"
            seen.add(key)

    def test_all_five_hubs_present(self):
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


# ═══════════════════════════════════════════════════════
#  TRADE_HUB_DISTANCES 映射完整性
# ═══════════════════════════════════════════════════════


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
