"""订单簿深度取价测试 — 纯计算，无 DB/Qt。"""

import pytest

from domain.market_depth import BUY, SELL, depth_price, sell_price_reliable

# 真实订单簿（type 3993 大型EMP立体炸弹 I，Jita 4-4）
# 卖单里有一笔 2 个 @543,800 的凑数单，真实深度在 995,900（1,640 个）
SELL_BOOK: list[tuple[float, int]] = [
    (543800.0, 2),
    (995800.0, 2),
    (995900.0, 1640),
    (996000.0, 388),
    (997000.0, 3),
    (999900.0, 2),
    (1000000.0, 3),
    (1258000.0, 15),
    (1259000.0, 39),
]

# 买单里有一笔 1 ISK × 10,000 的钓鱼挂单
BUY_BOOK: list[tuple[float, int]] = [
    (543700.0, 20),
    (543600.0, 35),
    (543500.0, 32),
    (543400.0, 27),
    (540000.0, 6),
    (485000.0, 382),
    (374400.0, 82),
    (50000.0, 100),
    (1.0, 10000),
]


class TestDepthPrice:
    def test_real_sell_book_skips_thin_order(self):
        """回归：2 个 @543,800 的凑数单应被跳过，取 995,900。"""
        assert depth_price(SELL_BOOK, SELL) == 995900.0

    def test_real_buy_book_ignores_lowball_order(self):
        """回归：1 ISK × 10,000 的钓鱼单不得把买价拉到 1 ISK。"""
        price = depth_price(BUY_BOOK, BUY)
        assert price == 543600.0

    def test_huge_lowball_order_cannot_collapse_price(self):
        """阈值以「中位挂单量」封顶，单笔巨量离群单无法把阈值抬到真实挂单量之上。"""
        inflated = [*BUY_BOOK, (1.0, 1_000_000)]
        price = depth_price(inflated, BUY)
        assert price is not None
        assert price > 500_000, f"买价被巨量钓鱼单拉低到 {price}"

    def test_empty_returns_none(self):
        assert depth_price([], SELL) is None

    def test_thin_book_falls_back_to_extreme(self):
        """盘口总量 < PRICE_DEPTH_MIN_BOOK：不剔除薄单，直接取极值。"""
        assert depth_price([(100.0, 3), (200.0, 4), (300.0, 5)], SELL) == 100.0
        assert depth_price([(300.0, 5), (200.0, 4), (100.0, 3)], BUY) == 300.0

    def test_uniform_book_keeps_extreme(self):
        """各档挂单量均匀时没有凑数单，取价应等于极值。"""
        uniform = [(float(100 + i), 100) for i in range(10)]
        assert depth_price(uniform, SELL) == 100.0
        assert depth_price(uniform, BUY) == 109.0

    def test_order_independent(self):
        assert depth_price(list(reversed(SELL_BOOK)), SELL) == 995900.0
        assert depth_price(list(reversed(BUY_BOOK)), BUY) == 543600.0


class TestSellPriceReliable:
    """`sell_price_reliable` —— 卖单价能不能拿去估值的判据。"""

    # (case, row, expected)。前三条是**真实数据回归**（Jita，2026-10-10 ESI 实测盘口）：
    # 隔热剂/预燃室卖侧各只有 1 笔 4 件挂单，买侧两百多万件 —— 库里 3 件库存因此
    # 按卖单价估成 135.42 亿 ISK（按买盘实际 8,504 ISK），仓库页与资产快照都被带崩。
    RELIABLE_CASES = [
        (
            "隔热剂-卖侧仅4件离群",
            {"sell_price": 68_000_000, "buy_price": 12.0, "buy_volume": 2_034_545, "sell_volume": 4},
            False,
        ),
        (
            "预燃室-卖侧仅4件离群",
            {"sell_price": 64_000_000, "buy_price": 12.1, "buy_volume": 5_408_323, "sell_volume": 4},
            False,
        ),
        (
            # 卖侧 486 件 ≥ PRICE_CREDIBLE_MIN_SELL_VOLUME，薄但立得住价 → 不能误杀
            "内部隔层-薄但卖侧有量",
            {"sell_price": 23_440_000, "buy_price": 105.0, "buy_volume": 858_830, "sell_volume": 486},
            True,
        ),
        (
            "厚盘-正常品种",
            {"sell_price": 17_860.0, "buy_price": 17_330.0, "buy_volume": 1_015_690_532, "sell_volume": 5_057_544},
            True,
        ),
        (
            "无买价-没有对手盘作证",
            {"sell_price": 100.0, "buy_price": 0, "buy_volume": 1_000_000, "sell_volume": 500},
            False,
        ),
        # 无卖价 → None：没有价可估，不是「不可信」（调用方据此不计入「N 项未计入」）
        ("无卖价", {"sell_price": 0, "buy_price": 10.0, "buy_volume": 1_000, "sell_volume": 900}, None),
        ("缺卖价键", {"buy_price": 10.0, "buy_volume": 1_000, "sell_volume": 900}, None),
        ("卖价None", {"sell_price": None, "buy_price": 10.0, "buy_volume": 1_000, "sell_volume": 900}, None),
        ("空字典", {}, None),
        # 脏数据不得抛异常：字符串价当 0；量缺失/负数当 0（＝没量数据 → 不判离群，放行）
        ("脏数据-字符串价", {"sell_price": "abc", "buy_price": 10.0, "buy_volume": 10, "sell_volume": 10}, None),
        ("脏数据-负数量", {"sell_price": 5.0, "buy_price": 4.0, "buy_volume": -100, "sell_volume": -5}, True),
        ("脏数据-缺量键", {"sell_price": 5.0, "buy_price": 4.0}, True),
        # 阈值边界：卖侧刚够绝对量即放行；差一件才看相对量（该例相对量也不够）
        (
            "边界-卖侧刚好100件",
            {"sell_price": 100.0, "buy_price": 50.0, "buy_volume": 1_000_000, "sell_volume": 100},
            True,
        ),
        (
            "边界-卖侧99件且不足买侧1%",
            {"sell_price": 100.0, "buy_price": 50.0, "buy_volume": 1_000_000, "sell_volume": 99},
            False,
        ),
        (
            # 相对量分支的独立覆盖：绝对量不够（<100），但相对买侧够厚（50 ≥ 1,000×1%）→ 放行
            "边界-卖侧不足100件但相对买侧够厚",
            {"sell_price": 100.0, "buy_price": 99.0, "buy_volume": 1_000, "sell_volume": 50},
            True,
        ),
    ]

    @pytest.mark.parametrize(("case", "row", "expected"), RELIABLE_CASES, ids=[c[0] for c in RELIABLE_CASES])
    def test_sell_price_reliable(self, case, row, expected):
        assert sell_price_reliable(row) is expected, f"{case}: {row}"
