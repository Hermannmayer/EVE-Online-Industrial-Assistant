"""路线 C · WP2 数值正确性修复的回归锚点（01-1 ~ 01-16 中的纯计算/数据面）。

每条用例都对应 `audit/reports/_draft-逐条-01.md` 里给出的「验证」命令与期望值；
数值来自 SDE/官方公式/真实库复算，不改公式就不要改这些数。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from domain.scoring import BlueprintRecipe, Material, calc_manufacturing_score

# ════════════════════════════════════════════════════════════════
#  01-2 / 01-11 — 制造时长（金标准锚点也在 test_manufacturing_calculator_golden.py）
# ════════════════════════════════════════════════════════════════


def test_bp_time_skill_whitelist_covers_sde_1982_only():
    """01-2：白名单就是 SDE 属性 1982 的 25 个技能 type_id（含突变稳定 -2%）。"""
    from domain.formulas import BP_TIME_SKILL_TYPE_IDS

    assert len(BP_TIME_SKILL_TYPE_IDS) == 25
    # 3380/3388/22242 均不带 1982 —— 绝不能进白名单
    assert not BP_TIME_SKILL_TYPE_IDS & {3380, 3388, 22242}
    assert {11452, 81896} <= BP_TIME_SKILL_TYPE_IDS


def test_missing_skills_do_not_default_to_level_five():
    """01-11：解析器兜底与计算默认值都必须是 0 级，不能默认满级。"""
    from domain.formulas import calc_production_time
    from services.char_config_resolver import DEFAULT_SKILLS

    assert DEFAULT_SKILLS == {}
    assert calc_production_time(3600) == pytest.approx(3600.0)


def test_new_character_template_skills_are_zero():
    """01-11：新用户默认配置里的技能全是 0 级，且键名与 reference.db 一致（英文键已清掉）。"""
    from services.char_config_validator import DEFAULT_CHAR_CONFIG

    skills = DEFAULT_CHAR_CONFIG["characters"]["main"]["skills"]
    assert set(skills.values()) == {0}
    assert not [k for k in skills if k.isascii()]
    # 面板/公式真正会读的键都得在
    assert {"工业理论", "高级工业理论", "会计学", "经纪人关系学", "高级经纪人关系学"} <= set(skills)


# ════════════════════════════════════════════════════════════════
#  01-4 — ME/TE 研究逐级时长
# ════════════════════════════════════════════════════════════════


def test_research_level_time_is_cumulative_not_linear():
    """01-4：bp11189（首级 42000 = rank 400）0→5 与 0→10 都按逐级表求和。"""
    from domain.research import research_level_time_seconds

    assert research_level_time_seconds(42000, target_level=5) == pytest.approx(400 * 5724.0)
    assert research_level_time_seconds(42000, target_level=10, current_level=5) == pytest.approx(
        400 * (441679.0 - 5724.0)
    )


# ════════════════════════════════════════════════════════════════
#  01-9 — 计划级时长用未取整秒数
# ════════════════════════════════════════════════════════════════


def test_total_metrics_uses_raw_seconds_not_rounded_hours():
    """01-9：单轮 204 s、2040 轮 → 416,160 s，而不是 round(204/3600,2)=0.06h → 440,640 s。"""
    from services.scoring_service import ScoringService

    per_run = {
        "hours_per_run": 0.06,  # domain 展示值（已 round）
        "actual_time_seconds": 204.0,  # 未取整原值
        "profit_per_run": 100.0,
        "revenue_per_run": 200.0,
        "materials": [],
        "breakdown": {"material_cost": 0.0, "bp_me": 0, "structure_mat_saving": 1.0},
    }
    total = ScoringService.calculate_total_metrics(per_run, runs=2040, parallels=1)
    assert total["total_time_seconds"] == pytest.approx(416160.0)
    assert total["total_time_hours"] == pytest.approx(115.6)
    # 旧口径（用 round 后的 0.06h）会得到 440,640 s
    assert total["total_time_seconds"] < 0.06 * 2040 * 3600


def test_combine_per_line_uses_raw_seconds():
    """01-9：逐线汇总同样优先取 actual_time_seconds（取最慢线 × runs）。"""
    from services.scoring_service import ScoringService

    per_line = [
        {"hours_per_run": 0.06, "actual_time_seconds": 204.0, "profit_per_run": 10.0},
        {"hours_per_run": 0.06, "actual_time_seconds": 300.0, "profit_per_run": 20.0},
    ]
    _per_run, total = ScoringService.combine_per_line(per_line, runs=2)
    assert total["total_time_seconds"] == pytest.approx(300.0 * 2)
    assert total["total_time_hours"] == pytest.approx(600.0 / 3600, abs=0.01)


# ════════════════════════════════════════════════════════════════
#  01-10 — 技能面板覆盖 + 术语注册
# ════════════════════════════════════════════════════════════════


def test_trade_skills_in_panel():
    """01-10：交易费率三技能必须在面板里，否则用户没地方填 → 恒按 0 级。"""
    from core.char_settings_common import ALL_SKILLS

    for name in ("会计学", "经纪人关系学", "高级经纪人关系学"):
        assert name in ALL_SKILLS


def test_blueprint_skills_all_fillable_in_panel():
    """01-10：蓝图要求但面板缺失的 31 个技能已补进 ALL_SKILLS。

    以 reference.db 为准做覆盖校验（DB 不存在时 skip，CI 干净检出不会因此红）。
    """
    from core.char_settings_common import ALL_SKILLS
    from core.paths import BP_DB_PATH, REF_DB_PATH

    if not Path(REF_DB_PATH).exists() or not Path(BP_DB_PATH).exists():
        pytest.skip("缺少 reference.db / blueprint.db（干净检出），跳过覆盖校验")
    ref = sqlite3.connect(f"file:{REF_DB_PATH}?mode=ro", uri=True)
    name = dict(ref.execute("SELECT type_id, zh_name FROM item"))
    bp = sqlite3.connect(f"file:{BP_DB_PATH}?mode=ro", uri=True)
    required = {
        name.get(sid, str(sid))
        for (sid,) in bp.execute("SELECT DISTINCT skill_type_id FROM blueprint_skills WHERE activity='manufacturing'")
    }
    panel = set(ALL_SKILLS)
    missing = sorted(required - panel)
    assert not missing, f"蓝图要求但面板填不了的技能（{len(missing)} 个）: {missing[:10]}"


def test_new_panel_skills_registered_in_terminology():
    """铁律「术语」：新增面板技能的中文名必须在 data/terminology.json 注册。"""
    from core.char_settings_common import SKILL_CATEGORIES

    term_file = Path(__file__).resolve().parent.parent / "data" / "terminology.json"
    data = json.loads(term_file.read_text(encoding="utf-8"))
    registered = set(data.get("skill_names", {}).values())
    new_categories = {name for name, _icon, _skills in SKILL_CATEGORIES if name in ("蓝图技能", "贸易")}
    assert new_categories == {"蓝图技能", "贸易"}
    for name, _icon, skills in SKILL_CATEGORIES:
        if name not in new_categories:
            continue
        missing = [s for s in skills if s not in registered]
        assert not missing, f"未在 terminology.json 注册: {missing}"


# ════════════════════════════════════════════════════════════════
#  01-15 — Upwell 精炼结构模型
# ════════════════════════════════════════════════════════════════


def test_refining_structure_types_and_cap():
    """01-15：结构类型区分基础产率，上限 90.6%；NPC 路径保持原值。"""
    from core.eve_formulas import calc_refining_yield

    skills = {"提炼学概论": 5, "提炼效率理论": 5}
    assert calc_refining_yield(skills, is_player_facility=True, ore_skill_level=5) == pytest.approx(0.72358)
    assert calc_refining_yield(
        skills, is_player_facility=True, ore_skill_level=5, structure_type="athanor"
    ) == pytest.approx(0.709665)
    assert calc_refining_yield(
        skills, is_player_facility=True, ore_skill_level=5, structure_type="citadel"
    ) == pytest.approx(0.69575)
    # NPC 站：R4/RE0 = 0.5×1.12 = 0.56（不变）
    assert calc_refining_yield({"提炼学概论": 4, "提炼效率理论": 0}) == pytest.approx(0.56)
    # 完美精炼上限 90.6%：用超高基础产率验证封顶（结构/技能/rig 组合本身远达不到）
    perfect = calc_refining_yield(skills, is_player_facility=True, station_base=1.5)
    assert perfect == pytest.approx(0.906)


# ════════════════════════════════════════════════════════════════
#  01-16 — EIV 单一来源（不混 adjusted 与 sell）
# ════════════════════════════════════════════════════════════════


class _FakePrices:
    def __init__(self, prices: dict[int, float], adjusted: dict[int, float]):
        self._prices = prices
        self._adjusted = adjusted

    def get_price(self, type_id: int, price_type: str, hub: str | None = None) -> float | None:
        return self._prices.get(type_id)

    def get_volume(self, type_id: int, vol_type: str = "total", hub: str | None = None) -> int:
        return 0

    def get_system_cost_index(self, system_id: int | None, activity: str = "manufacturing", hub: str = "Jita") -> float:
        return 0.0

    def get_adjusted_price(self, type_id: int) -> float | None:
        return self._adjusted.get(type_id)


def _score_with_prices(adjusted: dict[int, float]) -> dict:
    recipe = BlueprintRecipe(
        product_type_id=1,
        blueprint_type_id=2,
        prod_qty=1,
        base_time=60,
        materials=(Material(11, "料A", 2, 10), Material(12, "料B", 2, 10)),
    )
    return calc_manufacturing_score(
        recipe=recipe,
        prod_price=1.0,  # 压低售价 → 走负利润分支，但 breakdown 一定存在
        prices=_FakePrices({11: 10.0, 12: 10.0}, adjusted),
        research_cost=0.0,
        char_config={"skills": {}},
        mat_source_hub="Jita",
        sell_hub="Jita",
        price_type_mat="sell",
        bp_me=0,
        bp_te=0,
        system_id=None,
        structure_bonus=0.0,
        structure_time_mod=1.0,
        structure_mat_saving=1.0,
        facility_tax_pct=0.0,
        is_alpha=False,
    )


def test_eiv_falls_back_as_a_whole_when_adjusted_missing():
    """01-16：任一材料缺 adjusted_price → 整项用市价 EIV 并标注来源，不混源。"""
    result = _score_with_prices({11: 100.0})  # 料B 没有 adjusted
    breakdown = result["breakdown"]
    assert breakdown["eiv_source"] == "market_fallback"
    # 市价 EIV = 2×10 + 2×10 = 40（不是 2×100 + 2×10 的混源 220）
    assert breakdown["eiv"] == pytest.approx(40.0)


def test_eiv_uses_adjusted_when_all_available():
    result = _score_with_prices({11: 100.0, 12: 50.0})
    breakdown = result["breakdown"]
    assert breakdown["eiv_source"] == "adjusted"
    assert breakdown["eiv"] == pytest.approx(2 * 100.0 + 2 * 50.0)
