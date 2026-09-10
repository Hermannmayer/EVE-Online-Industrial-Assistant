"""domain/research.py 金标准测试 — 发明成功率 / 产出 / 解码器 / 科学作业时长。

数值来源：
- 成功率公式：EVE University Wiki「Invention」（base × (1 + (s1+s2)/30 + enc/40) × decryptor）
- 解码器修正：docs/eve_wiki_knowledge_base.md「解码器」节（官方支持中心表格）
- 产出流程：SDE 实测（T1 拷贝上限 与 T2 制造上限取小）
"""

from __future__ import annotations

import pytest

from domain import formulas
from domain.research import (
    ACTIVITY_COPYING,
    ACTIVITY_INVENTION,
    ACTIVITY_RESEARCH_ME,
    ACTIVITY_RESEARCH_TE,
    DECRYPTORS,
    Decryptor,
    copy_job_runs,
    get_decryptor,
    invention_attempts,
    invention_output_me_te,
    invention_output_runs,
    invention_probability,
    science_job_time,
)


class TestInventionProbability:
    def test_base_only_no_skills(self):
        """无技能无解码器 → 就是基础成功率。"""
        assert invention_probability(0.34) == pytest.approx(0.34)
        assert invention_probability(0.26) == pytest.approx(0.26)

    def test_science_skills_add_one_thirtieth_each(self):
        """科学技能每级 +1/30 相对加成（两个技能各 5 级 → ×4/3）。"""
        # 0.34 × (1 + 10/30) = 0.34 × 1.3333…
        assert invention_probability(0.34, 5, 5, 0) == pytest.approx(0.4533, abs=1e-4)

    def test_encryption_adds_one_fortieth(self):
        """加密技术原理每级 +1/40（5 级 → ×1.125）。"""
        assert invention_probability(0.34, 0, 0, 5) == pytest.approx(0.34 * 1.125)

    def test_full_skills_bonus_is_additive_denominator(self):
        """满技能（科学 5/5 + 加密 5）→ 加成 = 10/30 + 5/40 = 0.4583…

        注意：wiki 那句「每级科学技能等效 +3.333%」说的是 (s1+s2)/30 这一项，
        不是「基础率 ×3.333%」，两者不可混。
        """
        got = invention_probability(0.30, 5, 5, 5)
        assert got == pytest.approx(0.30 * (1 + 10 / 30 + 5 / 40))
        assert got == pytest.approx(0.4375)

    def test_decryptor_multiplier_applied(self):
        assert invention_probability(0.34, 0, 0, 0, prob_mult=1.8) == pytest.approx(0.612)
        assert invention_probability(0.34, 0, 0, 0, prob_mult=0.6) == pytest.approx(0.204)

    def test_clamped_to_one(self):
        """极端组合（高基础率 × 满技能 × 最优解码器）不会超过 100%。"""
        assert invention_probability(1.0, 5, 5, 5, prob_mult=1.9) <= 1.0

    def test_zero_base_returns_zero(self):
        assert invention_probability(0.0, 5, 5, 5, prob_mult=1.9) == 0.0
        assert invention_probability(0.0) == 0.0

    def test_negative_inputs_treated_as_zero(self):
        assert invention_probability(0.34, -3, -3, -3) == pytest.approx(0.34)


class TestDecryptorTable:
    """解码器表逐条比对知识库 §解码器（8 种）。"""

    EXPECTED = {
        34201: ("加速装置解码器", 1.20, 1, 2, 10),
        34202: ("获取装置解码器", 1.80, 4, -1, 4),
        34203: ("放大装置解码器", 0.60, 9, -2, 2),
        34204: ("等价装置解码器", 1.50, 3, 1, -2),
        34205: ("处理装置解码器", 1.10, 0, 3, 6),
        34206: ("对称装置解码器", 1.00, 2, 1, 8),
        34207: ("优化的获取装置解码器", 1.90, 2, 1, -2),
        34208: ("优化的放大装置解码器", 1.10, 7, 2, 0),
    }

    def test_table_matches_knowledge_base(self):
        assert set(DECRYPTORS) == set(self.EXPECTED)
        for tid, (name, mult, runs, me, te) in self.EXPECTED.items():
            d = DECRYPTORS[tid]
            assert d.name == name, tid
            assert d.prob_mult == pytest.approx(mult), tid
            assert d.runs_mod == runs, tid
            assert d.me_mod == me, tid
            assert d.te_mod == te, tid

    def test_get_decryptor_none_and_unknown(self):
        assert get_decryptor(None) is None
        assert get_decryptor(0) is None
        assert get_decryptor(99999999) is None

    def test_get_decryptor_known(self):
        d = get_decryptor(34203)
        assert d is not None and d.name == "放大装置解码器"


class TestInventionOutput:
    @pytest.mark.parametrize(
        ("base_runs", "decryptor_id", "expected"),
        [
            (10, None, 10),  # 模块/弹药默认 10 流程
            (1, None, 1),  # 舰船/改装件默认 1 流程
            (10, 34203, 19),  # 放大装置 +9
            (1, 34203, 10),  # 舰船 1 + 9
            (10, 34202, 14),  # 获取装置 +4
            (10, 34205, 10),  # 处理装置 +0
            (10, 34208, 17),  # 优化的放大装置 +7
        ],
    )
    def test_output_runs(self, base_runs, decryptor_id, expected):
        assert invention_output_runs(base_runs, get_decryptor(decryptor_id)) == expected

    def test_output_runs_floor_one(self):
        """负修正也不会把流程数压到 0 以下。"""
        weird = Decryptor(1, "测试", 1.0, -99, 0, 0)
        assert invention_output_runs(3, weird) == 1

    def test_output_me_te_without_decryptor(self):
        assert invention_output_me_te(None) == (2, 4)

    @pytest.mark.parametrize(
        ("decryptor_id", "expected"),
        [
            (34201, (4, 14)),  # +2 ME / +10 TE
            (34203, (0, 6)),  # -2 ME / +2 TE
            (34204, (3, 2)),  # +1 / -2
            (34206, (3, 12)),  # +1 / +8
        ],
    )
    def test_output_me_te_with_decryptor(self, decryptor_id, expected):
        assert invention_output_me_te(get_decryptor(decryptor_id)) == expected

    def test_output_me_te_floor_zero(self):
        """解码器负修正不会产生负的 ME/TE。"""
        weird = Decryptor(1, "测试", 1.0, 0, -99, -99)
        assert invention_output_me_te(weird) == (0, 0)


class TestInventionAttempts:
    def test_no_decryptor_module(self):
        """基础率 0.34、10 流程/次 → 要凑够 10 流程期望 3 次（0.34×10=3.4）。"""
        assert invention_attempts(10, 0.34, 10) == 3

    def test_amplified_decryptor_ship(self):
        """舰船基础率 0.30 × 放大装置 0.60 = 0.18、产出 1+9=10 流程 → 凑 10 流程 6 次。"""
        rate = invention_probability(0.30, 0, 0, 0, prob_mult=0.60)
        assert rate == pytest.approx(0.18)
        assert invention_attempts(10, rate, 10) == 6

    def test_ceiling_rounds_up(self):
        """0.34×10=3.4 → 需要 2 次才能覆盖 4 流程（ceil(4/3.4)=2）。"""
        assert invention_attempts(4, 0.34, 10) == 2

    def test_float_divisor_uses_true_ceiling(self):
        """分母是浮点（3.4）：必须真 ceil，不能被整数取整技巧算成 12。"""
        assert invention_attempts(38, 0.34, 10) == 12  # ceil(38/3.4) = ceil(11.176) = 12
        # 0.204×19 = 3.876；ceil(38/3.876) = ceil(9.804) = 10
        assert invention_attempts(38, 0.204, 19) == 10

    def test_exact_multiple_no_extra_attempt(self):
        """整除时不额外多算一次。"""
        assert invention_attempts(34, 0.34, 10) == 10  # 34/3.4 = 10.0

    def test_zero_inputs(self):
        assert invention_attempts(10, 0.0, 10) == 0
        assert invention_attempts(10, 0.34, 0) == 0
        assert invention_attempts(0, 0.34, 10) == 0


class TestCopyJobRuns:
    def test_copies_times_runs(self):
        assert copy_job_runs(1, 200, 200) == 200
        assert copy_job_runs(5, 30, 200) == 150

    def test_runs_per_copy_clamped_to_limit(self):
        """每份流程超过蓝图上限 → 钳到上限（发明输入 BPC 不能拷超出上限的流程）。"""
        assert copy_job_runs(1, 500, 200) == 200
        assert copy_job_runs(3, 999, 100) == 300

    def test_floor_one(self):
        assert copy_job_runs(0, 0, 0) == 1
        assert copy_job_runs(1, 0, 200) == 1


class TestScienceJobTime:
    def test_no_skills_no_structure(self):
        assert science_job_time(13800, activity=ACTIVITY_INVENTION) == pytest.approx(13800)

    def test_research_skill_two_percent(self):
        """研究概论 5 级 → -10%。"""
        got = science_job_time(13800, activity=ACTIVITY_INVENTION, research_skill=5)
        assert got == pytest.approx(13800 * 0.9)

    def test_metallurgy_only_for_research_activities(self):
        """冶金学只对 ME/TE 研究生效，拷贝/发明忽略。"""
        for act in (ACTIVITY_RESEARCH_ME, ACTIVITY_RESEARCH_TE):
            got = science_job_time(2100, activity=act, metallurgy_skill=5)
            assert got == pytest.approx(2100 * 0.95), act
        for act in (ACTIVITY_COPYING, ACTIVITY_INVENTION):
            got = science_job_time(2100, activity=act, metallurgy_skill=5)
            assert got == pytest.approx(2100), act

    def test_both_skills_multiply(self):
        got = science_job_time(1000, activity=ACTIVITY_RESEARCH_ME, research_skill=5, metallurgy_skill=5)
        assert got == pytest.approx(1000 * 0.9 * 0.95)

    def test_te_level_and_structure(self):
        got = science_job_time(1000, activity=ACTIVITY_INVENTION, research_skill=0, te_level=10, structure_time_mod=0.8)
        assert got == pytest.approx(1000 * 0.9 * 0.8)

    def test_negative_skills_treated_as_zero(self):
        assert science_job_time(1000, activity=ACTIVITY_INVENTION, research_skill=-3) == pytest.approx(1000)


class TestConstantsWiredToFormulas:
    """常量必须与 domain.formulas 的值一致（避免两处漂移）。"""

    def test_research_and_metallurgy_multipliers(self):
        from domain.research import METALLURGY_TIME_SKILL, RESEARCH_TIME_SKILL

        assert RESEARCH_TIME_SKILL == "研究概论"
        assert METALLURGY_TIME_SKILL == "冶金学"
        assert formulas.RESEARCH_SKILL_MULT == pytest.approx(0.02)
        assert formulas.METALLURGY_SKILL_MULT == pytest.approx(0.01)
