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

    def test_each_entry_has_jumps_positive(self):
        result = list_trade_hub_distances()
        for entry in result:
            assert entry["jumps"] > 0


# ═══════════════════════════════════════════════════════
#  TRADE_HUB_DISTANCES 映射完整性
# ═══════════════════════════════════════════════════════


class TestTradeHubDistancesMap:
    """距离映射数据完整性"""

    def test_all_pairs_symmetric(self):
        """所有距离对都是对称的（缺失反向条目会让用户查到 None 距离）"""
        for (a, b), d in list(TRADE_HUB_DISTANCES.items()):
            assert TRADE_HUB_DISTANCES.get((b, a)) == d
