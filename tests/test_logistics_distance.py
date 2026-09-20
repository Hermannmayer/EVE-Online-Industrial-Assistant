"""物流距离计算测试 —— 星门图 BFS 与贸易中心跳数

`get_distance_jumps` 自 2026-09-20 起改为走 `reference.db.stargate` 的**真实星门图**
（原先是一张硬编码表，多处与实测不符：Amarr↔Dodixie 标 62、真值高安 34；Amarr↔Rens
标 60、真值 20；Jita↔Amarr 标 72、真值 45）。

**必须用真实数据库**：本文件的全部意义就是「BFS 在真图上给出的跳数与游戏一致」，
桩上比对测不出星门图那个反直觉的 join（`destination_system_id` 存的是星门 id 而非星系 id）。
`database/` 是 gitignored、CI 上不生成 —— 缺库时整模块 skip。
"""

from pathlib import Path

import pytest

from core.constants import TRADE_HUB_SYSTEM_IDS
from core.paths import reference_db_path
from services.logistics import (
    TRADE_HUB_DISTANCES,
    compute_jumps,
    get_distance_jumps,
    list_trade_hub_distances,
)

pytestmark = pytest.mark.fast

if not Path(reference_db_path()).is_file():
    pytest.skip("需要真实 database/reference.db（星门图）；CI 上不生成这些库", allow_module_level=True)

_JITA = TRADE_HUB_SYSTEM_IDS["Jita"]
_AMARR = TRADE_HUB_SYSTEM_IDS["Amarr"]

# ── 参数化数据集 ──

#: `(起点, 终点, 最短, 高安)` —— 全部经游戏内跳数核对（2026-09-20）。
#: 两者差距最大的是 Jita↔Amarr：最短 11 跳走 Ahbazon 低安捷径，高安要绕 45 跳。
HUB_JUMPS = [
    ("Jita", "Amarr", 11, 45),
    ("Jita", "Dodixie", 12, 15),
    ("Jita", "Rens", 15, 25),
    ("Jita", "Hek", 9, 19),
    ("Amarr", "Dodixie", 14, 34),
    ("Amarr", "Rens", 11, 20),
    ("Amarr", "Hek", 15, 26),
    ("Dodixie", "Rens", 10, 14),
    ("Dodixie", "Hek", 8, 8),
    ("Rens", "Hek", 6, 6),
]

UNKNOWN_PAIRS = [
    ("Jita", "Unknown"),
    ("Unknown", "Amarr"),
    ("Unknown", "Unknown"),
    ("Foo", "Bar"),
]


def _pair(hub_a: str, hub_b: str) -> tuple[int, int]:
    return TRADE_HUB_SYSTEM_IDS[hub_a], TRADE_HUB_SYSTEM_IDS[hub_b]


class TestComputeJumps:
    """星门图 BFS —— 两种口径 + 边界"""

    @pytest.mark.parametrize("hub_a, hub_b, shortest, highsec", HUB_JUMPS)
    def test_hub_pairs_match_game(self, hub_a, hub_b, shortest, highsec):
        src, dst = _pair(hub_a, hub_b)
        assert compute_jumps(src, dst, "shortest") == shortest
        assert compute_jumps(src, dst, "highsec") == highsec

    @pytest.mark.parametrize("hub_a, hub_b, shortest, highsec", HUB_JUMPS)
    def test_symmetric(self, hub_a, hub_b, shortest, highsec):
        """跳数必须对称 —— 星门图是无向图"""
        src, dst = _pair(hub_a, hub_b)
        assert compute_jumps(dst, src, "shortest") == shortest
        assert compute_jumps(dst, src, "highsec") == highsec

    def test_same_system_is_zero(self):
        assert compute_jumps(_JITA, _JITA) == 0

    @pytest.mark.parametrize("missing", [0, None, 999999999])
    def test_missing_system_returns_none(self, missing):
        assert compute_jumps(_JITA, missing) is None  # type: ignore[arg-type]
        assert compute_jumps(missing, _JITA) is None  # type: ignore[arg-type]

    def test_unreachable_returns_none(self):
        """虫洞星系不在星门图上 —— J 空间（31xxxxxx）跳不到"""
        assert compute_jumps(_JITA, 31000001, "shortest") is None

    def test_highsec_never_shorter_than_shortest(self):
        """限高安是加约束，结果不可能更短"""
        for hub_a, hub_b, shortest, highsec in HUB_JUMPS:
            src, dst = _pair(hub_a, hub_b)
            assert highsec >= shortest

    def test_custom_mode_respects_floor(self):
        """自定义安全下限：下限越高越绕，0.45 等价于 highsec"""
        src, dst = _pair("Jita", "Amarr")
        assert compute_jumps(src, dst, "custom", 0.45) == compute_jumps(src, dst, "highsec")
        assert compute_jumps(src, dst, "custom", 0.0) == compute_jumps(src, dst, "shortest")


class TestGetDistanceJumps:
    """贸易中心名 → 跳数（按高安路线，与跑货实际走法一致）"""

    @pytest.mark.parametrize("hub_a, hub_b, _shortest, highsec", HUB_JUMPS)
    def test_known_distances(self, hub_a, hub_b, _shortest, highsec):
        assert get_distance_jumps(hub_a, hub_b) == highsec

    @pytest.mark.parametrize("hub_a, hub_b", [("Jita", "Amarr"), ("Dodixie", "Rens"), ("Hek", "Jita")])
    def test_symmetry(self, hub_a, hub_b):
        assert get_distance_jumps(hub_a, hub_b) == get_distance_jumps(hub_b, hub_a)

    def test_same_hub_is_zero(self):
        assert get_distance_jumps("Jita", "Jita") == 0

    @pytest.mark.parametrize("hub_a, hub_b", UNKNOWN_PAIRS)
    def test_unknown_pair_returns_none(self, hub_a, hub_b):
        assert get_distance_jumps(hub_a, hub_b) is None


class TestFallbackTable:
    """内置距离表只在星门图不可用时兜底 —— 它本身的数值是错的，但必须完整且对称"""

    def test_all_pairs_symmetric(self):
        for (a, b), d in list(TRADE_HUB_DISTANCES.items()):
            assert TRADE_HUB_DISTANCES.get((b, a)) == d

    def test_covers_every_hub_pair(self):
        """5 个中心两两 = 10 对，双向齐全"""
        hubs = list(TRADE_HUB_SYSTEM_IDS)
        for a in hubs:
            for b in hubs:
                if a != b:
                    assert (a, b) in TRADE_HUB_DISTANCES


class TestListTradeHubDistances:
    def test_returns_unique_pairs(self):
        result = list_trade_hub_distances()
        assert len(result) == 10  # C(5,2) = 10

    def test_values_match_get_distance_jumps(self):
        """两条路径不能给出不同数字（原先前者读硬编码表、后者走星门图）"""
        for entry in list_trade_hub_distances():
            assert entry["jumps"] == get_distance_jumps(entry["from"], entry["to"])
            assert entry["jumps"] > 0
