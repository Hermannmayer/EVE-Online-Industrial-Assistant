"""活动契约测试 — services/plan_job_kinds 与 plan_category / char_capacity 的接线。

这是「生产计划从制造计划泛化为工业计划」的语义边界：
所有消费方都必须经这里判定，不能各自硬编码 activity='manufacturing'。
"""

from __future__ import annotations

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
)

# 全部已知活动（normalize 必须原样放行的那一组）
_KNOWN = (
    "manufacturing",
    "copying",
    "invention",
    "researching_material_efficiency",
    "researching_time_efficiency",
    "reaction",
)


class TestNormalize:
    def test_known_activities_pass_through(self):
        """已知活动原样返回 —— 漏登记 = 静默降级成制造。"""
        for act in _KNOWN:
            assert pk.normalize(act) == act, act

    def test_unknown_falls_back_to_manufacturing(self):
        for raw in (None, "", "   ", "unknown_activity", "COPYING"):
            assert pk.normalize(raw) == "manufacturing", raw


class TestInputBlueprintRule:
    def test_rule_table(self):
        """activity → 规则；accepts_bpo/accepts_bpc 必须与规则同源。

        未知活动走 `.get(default)` → 沿用制造的宽松规则，不得返回 None。
        """
        expected = {
            "manufacturing": pk.RULE_BPO_OR_BPC,
            "reaction": pk.RULE_BPO_OR_BPC,
            "copying": pk.RULE_BPO_ONLY,
            "researching_material_efficiency": pk.RULE_BPO_ONLY,
            "researching_time_efficiency": pk.RULE_BPO_ONLY,
            "invention": pk.RULE_BPC_RUNS,
        }
        for act, rule in expected.items():
            assert pk.input_blueprint_rule(act) == rule, act
            assert pk.accepts_bpo(act) == (rule != pk.RULE_BPC_RUNS), act
            assert pk.accepts_bpc(act) == (rule != pk.RULE_BPO_ONLY), act
        assert pk.input_blueprint_rule("bogus") == pk.RULE_BPO_OR_BPC


class TestOutputKind:
    def test_output_kind_table(self):
        """产物口径：科研产物是蓝图 → 消费方禁止按制造产物反查。"""
        expected = {
            "manufacturing": pk.OUTPUT_ITEM,
            "reaction": pk.OUTPUT_ITEM,
            "copying": pk.OUTPUT_BPC,
            "invention": pk.OUTPUT_BPC,
            "researching_material_efficiency": pk.OUTPUT_IMPROVED_BPO,
            "researching_time_efficiency": pk.OUTPUT_IMPROVED_BPO,
        }
        for act, kind in expected.items():
            assert pk.output_kind(act) == kind, act
            assert pk.product_is_blueprint(act) == (kind != pk.OUTPUT_ITEM), act


class TestIsScience:
    def test_science_classification(self):
        for act in ("copying", "invention", "researching_material_efficiency"):
            assert pk.is_science(act), act
        for act in ("manufacturing", "reaction", None, "", "bogus"):
            assert not pk.is_science(act), act


class TestHints:
    def test_manufacturing_hint_keeps_legacy_wording(self):
        """历史文案不能变（用户习惯与启动校验的提示依赖「无可用蓝图」）。"""
        assert pk.input_blueprint_hint("manufacturing") == "无可用蓝图"


class TestMaterialActivity:
    def test_research_uses_short_name_in_materials_table(self):
        """blueprint_materials 里研究活动名无 -ing 后缀，查表必须换算。"""
        assert pk.material_activity("researching_material_efficiency") == "research_material"
        assert pk.material_activity("researching_time_efficiency") == "research_time"
        assert pk.material_activity("manufacturing") == "manufacturing"  # 其余原样透传


class TestCategoryMapping:
    def test_activity_maps_to_category(self):
        expected = {
            "manufacturing": CATEGORY_MANUFACTURING,
            "copying": CATEGORY_COPYING,
            "invention": CATEGORY_INVENTION,
            "researching_material_efficiency": CATEGORY_RESEARCH,
            "researching_time_efficiency": CATEGORY_RESEARCH,
        }
        for act, cat in expected.items():
            assert category_for_activity(act) == cat, act
        assert category_for_activity(None) == CATEGORY_MANUFACTURING
        assert category_for_activity("bogus") == CATEGORY_MANUFACTURING


class TestCapacityLine:
    def test_research_activities_occupy_research_line(self):
        """拷贝/发明/ME/TE 必须是科研线——漏配会占满制造线，角色超员误报。"""
        for act in ("copying", "invention", "researching_material_efficiency", "researching_time_efficiency"):
            assert capacity_line_for_category(category_for_activity(act)) == CAPACITY_LINE_RESEARCH, act
        assert capacity_line_for_category(category_for_activity("manufacturing")) == CAPACITY_LINE_MANUFACTURING
