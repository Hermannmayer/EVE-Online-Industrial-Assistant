"""订单簿深度取价测试 — 纯计算，无 DB/Qt。"""

from domain.market_depth import BUY, SELL, depth_price

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

    def test_single_level(self):
        assert depth_price([(42.0, 1000)], SELL) == 42.0

    def test_order_independent(self):
        assert depth_price(list(reversed(SELL_BOOK)), SELL) == 995900.0
        assert depth_price(list(reversed(BUY_BOOK)), BUY) == 543600.0
