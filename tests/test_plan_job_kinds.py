"""活动契约测试 — services/plan_job_kinds 与 plan_category / char_capacity 的接线。

这是「生产计划从制造计划泛化为工业计划」的语义边界：
所有消费方都必须经这里判定，不能各自硬编码 activity='manufacturing'。
"""

from __future__ import annotations

import pytest

from services import plan_job_kinds as pk
from services.char_capacity import (
    CAPACITY_LINE_MANUFACTURING,
    CAPACITY_LINE_RESEARCH,
    capacity_line_for_category,
)
from services.plan_category import (
    CATEGORY_COPYING,
    CATEGORY_INVENTION,
    CATEGORY_MANUFACTURING,
    CATEGORY_RESEARCH,
    category_for_activity,
    category_symbol,
)


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("manufacturing", "manufacturing"),
            ("copying", "copying"),
            ("invention", "invention"),
            ("researching_material_efficiency", "researching_material_efficiency"),
            ("researching_time_efficiency", "researching_time_efficiency"),
            ("reaction", "reaction"),
        ],
    )
    def test_known_activities_pass_through(self, raw, expected):
        assert pk.normalize(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "   ", "unknown_activity", "COPYING"])
    def test_unknown_falls_back_to_manufacturing(self, raw):
        assert pk.normalize(raw) == "manufacturing"


class TestInputBlueprintRule:
    def test_manufacturing_accepts_both(self):
        assert pk.input_blueprint_rule("manufacturing") == pk.RULE_BPO_OR_BPC
        assert pk.accepts_bpo("manufacturing")
        assert pk.accepts_bpc("manufacturing")

    @pytest.mark.parametrize("activity", ["copying", "researching_material_efficiency", "researching_time_efficiency"])
    def test_copying_and_research_require_bpo(self, activity):
        assert pk.input_blueprint_rule(activity) == pk.RULE_BPO_ONLY
        assert pk.accepts_bpo(activity)
        assert not pk.accepts_bpc(activity), "BPC 不可再拷贝或研究"

    def test_invention_requires_bpc(self):
        assert pk.input_blueprint_rule("invention") == pk.RULE_BPC_RUNS
        assert pk.accepts_bpc("invention")
        assert not pk.accepts_bpo("invention"), "BPO 不能用于发明"

    def test_reaction_accepts_both(self):
        assert pk.accepts_bpo("reaction") and pk.accepts_bpc("reaction")


class TestOutputKind:
    def test_manufacturing_outputs_item(self):
        assert pk.output_kind("manufacturing") == pk.OUTPUT_ITEM
        assert pk.output_kind("reaction") == pk.OUTPUT_ITEM
        assert not pk.product_is_blueprint("manufacturing")

    @pytest.mark.parametrize("activity", ["copying", "invention"])
    def test_science_outputs_blueprint(self, activity):
        assert pk.output_kind(activity) == pk.OUTPUT_BPC
        assert pk.product_is_blueprint(activity), "产物是蓝图 → 禁止按制造产物反查"

    @pytest.mark.parametrize("activity", ["researching_material_efficiency", "researching_time_efficiency"])
    def test_research_outputs_improved_bpo(self, activity):
        assert pk.output_kind(activity) == pk.OUTPUT_IMPROVED_BPO
        assert pk.product_is_blueprint(activity)


class TestIsScience:
    @pytest.mark.parametrize("activity", ["copying", "invention", "researching_material_efficiency"])
    def test_science_activities(self, activity):
        assert pk.is_science(activity)

    @pytest.mark.parametrize("activity", ["manufacturing", "reaction", None, "", "bogus"])
    def test_non_science_activities(self, activity):
        assert not pk.is_science(activity)


class TestHints:
    def test_manufacturing_hint_keeps_legacy_wording(self):
        """历史文案不能变（既有测试与用户习惯都依赖「无可用蓝图」）。"""
        assert pk.input_blueprint_hint("manufacturing") == "无可用蓝图"

    def test_copying_hint_mentions_bpo(self):
        assert "BPO" in pk.input_blueprint_hint("copying")

    def test_invention_hint_mentions_bpc(self):
        assert "BPC" in pk.input_blueprint_hint("invention")


class TestMaterialActivity:
    def test_research_uses_short_name_in_materials_table(self):
        """blueprint_materials 里研究活动名无 -ing 后缀，查表必须换算。"""
        assert pk.material_activity("researching_material_efficiency") == "research_material"
        assert pk.material_activity("researching_time_efficiency") == "research_time"

    def test_others_pass_through(self):
        assert pk.material_activity("manufacturing") == "manufacturing"
        assert pk.material_activity("copying") == "copying"
        assert pk.material_activity("invention") == "invention"


class TestCategoryMapping:
    @pytest.mark.parametrize(
        ("activity", "expected"),
        [
            ("manufacturing", CATEGORY_MANUFACTURING),
            ("copying", CATEGORY_COPYING),
            ("invention", CATEGORY_INVENTION),
            ("researching_material_efficiency", CATEGORY_RESEARCH),
            ("researching_time_efficiency", CATEGORY_RESEARCH),
        ],
    )
    def test_activity_maps_to_category(self, activity, expected):
        assert category_for_activity(activity) == expected

    def test_unknown_falls_back(self):
        assert category_for_activity(None) == CATEGORY_MANUFACTURING
        assert category_for_activity("bogus") == CATEGORY_MANUFACTURING

    def test_every_category_has_symbol(self):
        """每类都要有展示符号（生产计划表「类别」列）。"""
        for act in ("manufacturing", "copying", "invention", "reaction"):
            assert category_symbol(category_for_activity(act))
        assert category_symbol(CATEGORY_RESEARCH)


class TestCapacityLine:
    @pytest.mark.parametrize("activity", ["copying", "invention"])
    def test_copy_and_invention_occupy_research_line(self, activity):
        assert capacity_line_for_category(category_for_activity(activity)) == CAPACITY_LINE_RESEARCH

    @pytest.mark.parametrize("activity", ["researching_material_efficiency", "researching_time_efficiency"])
    def test_me_te_research_occupies_research_line(self, activity):
        """ME/TE 研究必须是科研线——漏配会占满制造线，角色超员误报。"""
        assert capacity_line_for_category(category_for_activity(activity)) == CAPACITY_LINE_RESEARCH

    def test_manufacturing_occupies_manufacturing_line(self):
        assert capacity_line_for_category(category_for_activity("manufacturing")) == CAPACITY_LINE_MANUFACTURING
