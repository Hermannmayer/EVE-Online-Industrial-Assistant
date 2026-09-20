"""合同表模型 —— 渲染文本与排序。

**没有外观断言**（不测颜色/字号/对齐，按测试判定表属禁止档）；测的是**文本内容**，
它是用户做判断的依据：剩余时间算错、跳数状态混为一谈、缺价显示成 0，都会让人做错决定。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from ui_qml.models.contract_models import (
    AUCTION_VIEW,
    COURIER_VIEW,
    EXCHANGE_VIEW,
    ContractItemTableModel,
    ContractTableModel,
    _isk,
    _m3,
    _pct_signed,
    _place,
    _remaining,
)

pytestmark = pytest.mark.ui


def _row(view, row: dict, col: int) -> str:
    return str(view.render(row, col))


class TestFormatters:
    @pytest.mark.parametrize(
        "seconds, expected",
        [
            (None, "—"),
            (-5, "已过期"),
            (0, "已过期"),
            (90, "0小时1分"),
            (3_600, "1小时0分"),
            (86_400, "1天0小时"),
            (86_400 * 2 + 7_200, "2天2小时"),
        ],
    )
    def test_remaining(self, seconds, expected):
        """剩余时间是合同最要紧的一列 —— 跨天/一天内两种档位都要对"""
        assert _remaining(seconds) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [(0, "—"), (None, "—"), (1234.5, "1,234"), (1_500_000_000.0, "1,500,000,000")],
    )
    def test_isk(self, value, expected):
        """0 显示「—」而不是「0」——「没有」和「是零」不是一回事"""
        assert _isk(value) == expected

    @pytest.mark.parametrize("value, expected", [(None, "—"), (0, "—"), (12.34, "12.3")])
    def test_m3(self, value, expected):
        assert _m3(value) == expected

    @pytest.mark.parametrize("value, expected", [(None, "—"), (25.0, "+25.0%"), (-12.5, "-12.5%"), (0, "+0.0%")])
    def test_pct_signed(self, value, expected):
        assert _pct_signed(value) == expected

    def test_place_includes_system_and_security(self):
        """同名站点遍布新伊甸，只给站名会认错地方 —— 星系与安全等级必须一起给"""
        text = _place("Jita IV - Moon 4", "Jita", 0.95)
        assert "Jita IV - Moon 4" in text and "Jita" in text and "0.9" in text

    def test_place_unknown(self):
        assert _place("", "", None) == "未知地点"


class TestCourierJumpColumn:
    def test_jumps_are_shown_when_computed(self):
        assert _row(COURIER_VIEW, {"jumps": 12, "jumps_status": "ok"}, 3) == "12"

    @pytest.mark.parametrize(
        "status, expected",
        [
            ("not_computed", "未计算"),
            ("unknown_endpoint", "未知地点"),
            ("unroutable", "需穿低安"),
        ],
    )
    def test_empty_jumps_are_distinguished_by_reason(self, status, expected):
        """三种空值必须给出不同文字。

        「高安口径下无路线」意味着这活要穿低安（决策信息）；「起止点解析不出」是我们
        不知道这是哪（风险信息）。都显示成「—」等于把两种相反的结论抹平。
        """
        assert _row(COURIER_VIEW, {"jumps": None, "jumps_status": status}, 3) == expected


class TestAuctionView:
    def test_entry_cost_columns(self):
        row = {"buyout": 500.0, "current_bid": 100.0, "market_value": 1_000.0, "price_diff": 500.0}
        assert _row(AUCTION_VIEW, row, 2) == "500"  # 一口价
        assert _row(AUCTION_VIEW, row, 3) == "100"  # 当前出价
        assert _row(AUCTION_VIEW, row, 5) == "+500"

    def test_missing_diff_shows_dash_not_zero(self):
        """价差算不出来时必须是「—」—— 显示 0 会被读成「不赚不亏」"""
        row = {"price_diff": None, "diff_pct": None}
        assert _row(AUCTION_VIEW, row, 5) == "—"
        assert _row(AUCTION_VIEW, row, 6) == "—"

    @pytest.mark.parametrize("status", ["no_items", "no_price"])
    def test_unanalyzed_contract_shows_dash_not_huge_loss(self, status):
        """物品还没拉时，价差等于「−合同价」—— 整屏巨额负数看着像「全都不值得买」。

        那是「还没算」，不是「算了，是亏的」。市价与价差三列都必须显示「—」。
        """
        row = {
            "status": status,
            "entry_cost": 35_000_000_000.0,
            "market_value": 0.0,
            "price_diff": -35_000_000_000.0,
            "diff_pct": -100.0,
        }
        for col in (4, 5, 6):
            assert _row(AUCTION_VIEW, row, col) == "—"

    def test_analyzed_contract_still_shows_real_numbers(self):
        row = {
            "status": "ok",
            "entry_cost": 500.0,
            "market_value": 1_000.0,
            "price_diff": 500.0,
            "diff_pct": 100.0,
        }
        assert _row(AUCTION_VIEW, row, 4) == "1,000"
        assert _row(AUCTION_VIEW, row, 5) == "+500"


class TestExchangeView:
    def test_blueprint_columns_blank_for_plain_contracts(self):
        """非蓝图合同的「蓝图市价/制造利润」留空，不显示 0（0 会被读成「蓝图不值钱」）"""
        row = {"has_blueprint": False, "blueprint_value": 0.0, "manufacturing_profit": 0.0}
        assert _row(EXCHANGE_VIEW, row, 6) == ""
        assert _row(EXCHANGE_VIEW, row, 7) == "—"
        assert _row(EXCHANGE_VIEW, row, 8) == "—"

    def test_blueprint_row_shows_breakdown(self):
        row = {"has_blueprint": True, "blueprint_value": 2e7, "manufacturing_profit": 3e6}
        assert _row(EXCHANGE_VIEW, row, 6) == "是"
        assert _row(EXCHANGE_VIEW, row, 7) == "20,000,000"
        assert _row(EXCHANGE_VIEW, row, 8) == "3,000,000"


class TestSorting:
    def test_sort_numeric_desc_with_none_last(self):
        model = ContractTableModel(COURIER_VIEW)
        model.set_rows([{"isk_per_jump": 5.0}, {"isk_per_jump": 50.0}, {"isk_per_jump": None}])
        model.sort(7, Qt.SortOrder.DescendingOrder)
        assert [r["isk_per_jump"] for r in model._rows] == [50.0, 5.0, None]

    def test_sort_on_column_without_key_is_noop(self):
        model = ContractTableModel(COURIER_VIEW)
        model.set_rows([{"contract_id": 1}])
        model.sort(9, Qt.SortOrder.AscendingOrder)  # 「剩余」列没有排序键
        assert model.rowCount() == 1


class TestItemModel:
    def test_runs_only_for_copies(self):
        """可运行数只有复制品才有意义；BPO 显示「—」而不是 1（会被读成「只能造一次」）"""
        model = ContractItemTableModel()
        model.set_rows(
            [
                {"type_id": 1, "quantity": 1, "is_blueprint_copy": False, "runs": 1},
                {"type_id": 2, "quantity": 1, "is_blueprint_copy": True, "runs": 42},
            ]
        )
        assert model._display(model._rows[0], 8) == "—"
        assert model._display(model._rows[1], 8) == "42"

    def test_unit_price_and_subtotal(self):
        model = ContractItemTableModel()
        model.set_rows([{"type_id": 1, "quantity": 10, "unit_price": 5.0}])
        assert model._display(model._rows[0], 9) == "5"
        assert model._display(model._rows[0], 10) == "50"

    def test_no_price_shows_dash(self):
        model = ContractItemTableModel()
        model.set_rows([{"type_id": 1, "quantity": 10}])
        assert model._display(model._rows[0], 9) == "—"
        assert model._display(model._rows[0], 10) == "—"
