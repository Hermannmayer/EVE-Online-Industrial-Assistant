"""合同判定纯计算测试 —— 价差 / 制造利润 / 每方每跳

纯函数、无 DB，按测试判定表属「纯计算」档，跑 `fast`。

重点守的是**几个静默算错的坑**（算错了界面上看不出来，只会给出误导性的排序）：
  - 缺价物品被当 0 计入 → 总市价被压低，看起来「大幅折价」
  - `runs` 没进制造利润 → BPC 的收益被低估成单次
  - 跳数未知时用 0 兜底 → 排到最后，看起来像「不值得跑」
  - ME 没进材料量 → 成本高估
"""

from datetime import UTC, datetime

import pytest

from domain.contract_analysis import (
    STATUS_NO_ITEMS,
    STATUS_NO_PRICE,
    STATUS_OK,
    STATUS_PARTIAL_PRICE,
    auction_metrics,
    blueprint_exchange_metrics,
    courier_metrics,
    exchange_metrics,
    icon_type_ids,
    manufacturing_profit,
    market_value,
    parse_expiry,
    price_diff,
    remaining_seconds,
)

pytestmark = pytest.mark.fast

_NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)


def _item(type_id: int, qty: int = 1, **extra) -> dict:
    return {"type_id": type_id, "quantity": qty, **extra}


def _contract(**extra) -> dict:
    base = {
        "price": 0.0,
        "buyout": 0.0,
        "reward": 0.0,
        "collateral": 0.0,
        "volume": 0.0,
        "days_to_complete": 0,
        "date_expired": "2026-09-21T12:00:00Z",
    }
    base.update(extra)
    return base


# ═══════════════════════════════════════════════════════
#  基础量
# ═══════════════════════════════════════════════════════


class TestRemainingSeconds:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("2026-09-21T12:00:00Z", 86_400),
            ("2026-09-19T12:00:00Z", -86_400),  # 已过期给负数，由界面决定怎么显示
            ("", None),
            (None, None),
            ("not-a-date", None),
        ],
    )
    def test_remaining(self, raw, expected):
        assert remaining_seconds(raw, _NOW) == expected

    def test_parse_expiry_handles_z_suffix(self):
        assert parse_expiry("2026-09-21T12:00:00Z") == datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


class TestMarketValue:
    def test_sums_price_times_quantity(self):
        items = [_item(34, 100), _item(35, 2)]
        assert market_value(items, {34: 5.0, 35: 1_000.0}) == (2_500.0, 2, 0)

    def test_missing_price_is_not_zero_filled(self):
        """缺价必须单独计数 —— 当 0 计会把总市价压低成假的「折价」"""
        items = [_item(34, 100), _item(35, 2)]
        total, priced, missing = market_value(items, {34: 5.0})
        assert (total, priced, missing) == (500.0, 1, 1)

    @pytest.mark.parametrize("bad_price", [0, -1, None])
    def test_non_positive_price_counts_as_missing(self, bad_price):
        total, priced, missing = market_value([_item(34, 10)], {34: bad_price})
        assert (total, priced, missing) == (0.0, 0, 1)

    def test_empty_items(self):
        assert market_value([], {34: 5.0}) == (0.0, 0, 0)


class TestPriceDiff:
    def test_diff_and_percent(self):
        diff, pct = price_diff(1_000.0, 800.0)
        assert (diff, pct) == (200.0, 25.0)

    def test_negative_when_overpaying(self):
        diff, pct = price_diff(700.0, 800.0)
        assert diff == -100.0
        assert pct == -12.5

    def test_zero_cost_has_no_percent(self):
        diff, pct = price_diff(1_000.0, 0.0)
        assert diff == 1_000.0
        assert pct is None  # 0 成本算不出百分比，不能返回 inf

    @pytest.mark.parametrize("value, cost", [(None, 100.0), (100.0, None), (None, None)])
    def test_none_propagates(self, value, cost):
        assert price_diff(value, cost) == (None, None)


class TestIconTypeIds:
    """合同行「里面是什么」取哪几件 —— 取错只会让列表看着眼熟但没信息。"""

    def test_ranks_by_total_value_not_by_input_order(self):
        items = [_item(34, 1000), _item(35, 2)]
        assert icon_type_ids(items, {34: 1.0, 35: 1_000.0}) == [35, 34]

    def test_limited_and_deduped(self):
        items = [_item(34, 10), _item(35, 5), _item(36, 1), _item(34, 7)]
        assert icon_type_ids(items, {34: 5.0, 35: 5.0, 36: 5.0}, limit=2) == [34, 35]

    def test_unpriced_items_rank_after_priced_ones(self):
        """缺价的不能按 0 参与价值排序 —— 那样大家都是 0，顺序随数据库给，图标每次刷新都在变。"""
        items = [_item(34, 1), _item(35, 100)]
        assert icon_type_ids(items, {34: 5.0}) == [34, 35]

    def test_empty_and_unknown(self):
        assert icon_type_ids([], {34: 5.0}) == []
        assert icon_type_ids([{"quantity": 3}], {}) == []


# ═══════════════════════════════════════════════════════
#  拍卖 / 物品交换
# ═══════════════════════════════════════════════════════


class TestAuctionMetrics:
    def test_prefers_buyout_when_present(self):
        """有一口价就按一口价 —— 否则会低估拿到手的成本（叫价还会往上涨）"""
        out = auction_metrics(_contract(price=100.0, buyout=500.0), [_item(34, 10)], {34: 100.0}, _NOW)
        assert out["entry_kind"] == "buyout"
        assert out["entry_cost"] == 500.0
        assert (out["market_value"], out["price_diff"]) == (1_000.0, 500.0)
        assert out["current_bid"] == 100.0  # 当前出价仍然给出来供参考

    def test_falls_back_to_current_bid(self):
        out = auction_metrics(_contract(price=100.0), [_item(34, 10)], {34: 100.0}, _NOW)
        assert out["entry_kind"] == "bid"
        assert out["entry_cost"] == 100.0
        assert out["price_diff"] == 900.0

    def test_partial_price_flagged(self):
        out = auction_metrics(_contract(price=100.0), [_item(34, 1), _item(35, 1)], {34: 100.0}, _NOW)
        assert out["status"] == STATUS_PARTIAL_PRICE
        assert out["unpriced_items"] == 1

    def test_no_price_at_all(self):
        out = auction_metrics(_contract(price=100.0), [_item(34, 1)], {}, _NOW)
        assert out["status"] == STATUS_NO_PRICE
        assert out["price_diff"] == -100.0  # 总市价 0，价差就是负的合同价

    def test_status_ok_and_carries_timer_volume(self):
        out = auction_metrics(_contract(price=50.0, volume=12.5), [_item(34, 1)], {34: 100.0}, _NOW)
        assert out["status"] == STATUS_OK
        assert out["remaining_seconds"] == 86_400
        assert out["volume_m3"] == 12.5
        assert out["total_quantity"] == 1


class TestExchangeMetrics:
    def test_diff_against_price(self):
        out = exchange_metrics(_contract(price=800.0), [_item(34, 10)], {34: 100.0}, _NOW)
        assert (out["market_value"], out["entry_cost"]) == (1_000.0, 800.0)
        assert (out["price_diff"], out["diff_pct"]) == (200.0, 25.0)

    def test_no_items_reported(self):
        out = exchange_metrics(_contract(price=800.0), [], {34: 100.0}, _NOW)
        assert out["status"] == STATUS_NO_ITEMS

    def test_free_contract_has_no_percent(self):
        out = exchange_metrics(_contract(price=0.0), [_item(34, 10)], {34: 100.0}, _NOW)
        assert out["diff_pct"] is None
        assert out["price_diff"] == 1_000.0


# ═══════════════════════════════════════════════════════
#  蓝图合同
# ═══════════════════════════════════════════════════════

_BP_TYPE = 1000
_PRODUCT = 2000
_MAT_A = 34
_MAT_B = 35

#: 1 份产物，材料 A 100 / B 10
_RECIPE = {
    "product_type_id": _PRODUCT,
    "output_qty": 1,
    "materials": [(_MAT_A, 100), (_MAT_B, 10)],
}


class TestManufacturingProfit:
    def test_bpc_profit_scales_with_runs(self):
        """10 次作业的 BPC 收益必须是单次的 10 倍 —— 漏乘 runs 会严重低估"""
        prices = {_PRODUCT: 1_000.0, _MAT_A: 1.0, _MAT_B: 5.0}
        one = manufacturing_profit({"is_blueprint_copy": True, "runs": 1, "material_efficiency": 0}, _RECIPE, prices)
        ten = manufacturing_profit({"is_blueprint_copy": True, "runs": 10, "material_efficiency": 0}, _RECIPE, prices)
        # 单次：1000 - (100*1 + 10*5) = 850
        assert one == 850.0
        assert ten == 8_500.0

    def test_bpo_estimates_one_run(self):
        """BPO 没有作业数上限，按 1 次作业估（并如实返回这一个数）"""
        prices = {_PRODUCT: 1_000.0, _MAT_A: 1.0, _MAT_B: 5.0}
        bpo = manufacturing_profit({"is_blueprint_copy": False, "runs": 1, "material_efficiency": 0}, _RECIPE, prices)
        assert bpo == 850.0

    def test_me_lowers_material_cost(self):
        """ME 10 → 材料 A 从 100 降到 90；不算 ME 会把成本算高、利润算低"""
        prices = {_PRODUCT: 1_000.0, _MAT_A: 1.0, _MAT_B: 5.0}
        me0 = manufacturing_profit({"is_blueprint_copy": True, "runs": 1, "material_efficiency": 0}, _RECIPE, prices)
        me10 = manufacturing_profit({"is_blueprint_copy": True, "runs": 1, "material_efficiency": 10}, _RECIPE, prices)
        assert me10 > me0
        # A 是单件料（基础量 100 > 1，适用 ME）：100→90；B 10→9
        assert me10 == 1_000.0 - (90 * 1.0 + 9 * 5.0)

    @pytest.mark.parametrize("missing_key", [_PRODUCT, _MAT_A, _MAT_B])
    def test_any_missing_price_yields_zero(self, missing_key):
        """任一材料缺价 → 成本被低估 → 利润是假的，一律返回 0 而不是乐观值"""
        prices = {_PRODUCT: 1_000.0, _MAT_A: 1.0, _MAT_B: 5.0}
        del prices[missing_key]
        assert (
            manufacturing_profit({"is_blueprint_copy": True, "runs": 5, "material_efficiency": 0}, _RECIPE, prices)
            == 0.0
        )


class TestBlueprintExchangeMetrics:
    def test_value_is_blueprint_price_plus_manufacturing_profit(self):
        """合同价值 = 蓝图本身市价 + 制造利润（用户口径）"""
        prices = {_BP_TYPE: 20_000.0, _PRODUCT: 1_000.0, _MAT_A: 1.0, _MAT_B: 5.0}
        items = [_item(_BP_TYPE, 1, is_blueprint_copy=True, runs=2, material_efficiency=0)]
        out = blueprint_exchange_metrics(_contract(price=14_000.0), items, prices, {_BP_TYPE: _RECIPE}, now=_NOW)

        assert out["blueprint_value"] == 20_000.0
        assert out["manufacturing_profit"] == 1_700.0  # 850 × 2 次
        assert out["market_value"] == 21_700.0
        assert out["price_diff"] == 7_700.0
        assert out["blueprint_count"] == 1

    def test_blueprint_without_recipe_still_counts_as_blueprint(self):
        """`blueprints.db` 查不到配方时它仍必须被认成蓝图并算进蓝图市价。

        只看「有没有配方」的话，这类合同会在界面上显示成「不含蓝图」。
        """
        prices = {_BP_TYPE: 20_000.0}
        items = [_item(_BP_TYPE, 1, is_blueprint_copy=True, runs=5, material_efficiency=0)]
        out = blueprint_exchange_metrics(_contract(price=1_000.0), items, prices, {}, {_BP_TYPE}, now=_NOW)
        assert out["blueprint_count"] == 1
        assert out["blueprint_value"] == 20_000.0
        assert out["manufacturing_profit"] == 0.0
        assert out["market_value"] == 20_000.0

    def test_no_identity_set_means_treated_as_plain_item(self):
        """蓝图身份来自 `blueprint_type_ids`（item_kind 给的），不是 `is_blueprint_copy`
        —— 后者对 BPO 恒为假。没给身份集合时按普通物品计，但总额不变。"""
        prices = {_BP_TYPE: 20_000.0}
        items = [_item(_BP_TYPE, 1, is_blueprint_copy=True, runs=5, material_efficiency=0)]
        out = blueprint_exchange_metrics(_contract(price=1_000.0), items, prices, {}, now=_NOW)
        assert out["blueprint_count"] == 0
        assert out["other_value"] == 20_000.0
        assert out["market_value"] == 20_000.0

    def test_non_blueprint_items_kept_separate(self):
        prices = {_BP_TYPE: 100.0, _PRODUCT: 1_000.0, _MAT_A: 1.0, _MAT_B: 5.0, 999: 7.0}
        items = [
            _item(_BP_TYPE, 1, is_blueprint_copy=True, runs=1, material_efficiency=0),
            _item(999, 3),
        ]
        out = blueprint_exchange_metrics(_contract(price=0.0), items, prices, {_BP_TYPE: _RECIPE}, {_BP_TYPE}, now=_NOW)
        assert out["other_value"] == 21.0
        assert out["market_value"] == 100.0 + 850.0 + 21.0

    def test_unpriced_blueprint_flagged_not_zero_filled(self):
        items = [_item(_BP_TYPE, 1, is_blueprint_copy=True, runs=1, material_efficiency=0)]
        out = blueprint_exchange_metrics(_contract(price=10.0), items, {}, {_BP_TYPE: _RECIPE}, {_BP_TYPE}, now=_NOW)
        assert out["status"] == STATUS_NO_PRICE
        assert out["blueprint_count"] == 0  # 没价就没算进蓝图数


# ═══════════════════════════════════════════════════════
#  运输合同
# ═══════════════════════════════════════════════════════


class TestCourierMetrics:
    def test_per_jump_and_per_jump_m3(self):
        out = courier_metrics(
            _contract(reward=10_000_000.0, collateral=100_000_000.0, volume=1_000.0, days_to_complete=3), 20, _NOW
        )
        assert out["isk_per_jump"] == 500_000.0
        assert out["isk_per_jump_m3"] == 500.0
        assert out["reward_to_collateral"] == 0.1
        assert out["days_to_complete"] == 3

    @pytest.mark.parametrize("jumps", [None, 0])
    def test_unknown_jumps_yield_none_not_zero(self, jumps):
        """跳数算不出来时必须是 None —— 用 0 兜底会把它排到末尾，看起来像不值得跑"""
        out = courier_metrics(_contract(reward=1_000.0, volume=10.0), jumps, _NOW)
        assert out["isk_per_jump"] is None
        assert out["isk_per_jump_m3"] is None

    def test_zero_volume_has_no_per_m3(self):
        out = courier_metrics(_contract(reward=1_000.0, volume=0.0), 10, _NOW)
        assert out["isk_per_jump"] == 100.0
        assert out["isk_per_jump_m3"] is None  # 除以 0 不可定义，不能返回 inf

    def test_no_collateral_no_ratio(self):
        out = courier_metrics(_contract(reward=1_000.0, collateral=0.0, volume=1.0), 10, _NOW)
        assert out["reward_to_collateral"] is None

    def test_flagship_route_is_worse_than_short_haul(self):
        """每方每跳才是比较基准：同样报酬下长跳数/大方数的合同应该排后面"""
        short = courier_metrics(_contract(reward=10_000_000.0, volume=1_000.0), 5, _NOW)
        long = courier_metrics(_contract(reward=10_000_000.0, volume=1_000.0), 50, _NOW)
        assert short["isk_per_jump_m3"] > long["isk_per_jump_m3"]
