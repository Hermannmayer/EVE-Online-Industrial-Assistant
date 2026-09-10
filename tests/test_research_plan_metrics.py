"""科研作业成本金标准测试 — services/plan_metrics 的拷贝/发明/研究成本。

数值来自 SDE 实测 + 游戏内价格快照，作为「公式契约」回归基线：
- 200mm自动加农炮 II（type_id 2889）的发明路径：
  T2 制造蓝图 2890 ← 发明自 T1 蓝图 821「200mm自动加农炮蓝图 I」
  数据核心 = 机械工程 ×1（¥27,890）+ 核芯物理 ×1（¥96,830）
  基础成功率 0.34、基础时长 13,800s、拷贝上限 200 流程
"""

from __future__ import annotations

import pytest

from domain.research import DECRYPTORS
from services.plan_metrics import (
    copying_plan_cost,
    invention_plan_cost,
    job_batch_materials,
    material_cost_of,
    research_plan_cost,
)

# ── 200mm 自动加农炮 II 的实测数据 ──
MECH_DATACORE = 20424  # 机械工程数据核心
NUCLEAR_DATACORE = 20423  # 核芯物理数据核心
INVENTION_MATS = [(MECH_DATACORE, 1), (NUCLEAR_DATACORE, 1)]
PRICES = {MECH_DATACORE: 27890.0, NUCLEAR_DATACORE: 96830.0}
JITA_INVENTION_SCI = 0.0014
BASE_PROB = 0.34
BASE_RUNS = 10  # min(T1 拷贝上限 200, T2 制造上限 10)


class TestJobBatchMaterials:
    def test_single_job_is_base_quantity(self):
        assert job_batch_materials([(20416, 2), (25887, 2)], 1) == [(20416, 2), (25887, 2)]

    def test_scales_linearly_with_job_count(self):
        assert job_batch_materials([(20416, 2)], 5) == [(20416, 10)]

    def test_zero_jobs_floored_to_one(self):
        assert job_batch_materials([(20416, 2)], 0) == [(20416, 2)]


class TestMaterialCostOf:
    def test_prices_times_quantities(self):
        assert material_cost_of([(20424, 1), (20423, 1)], PRICES) == pytest.approx(124720.0)

    def test_missing_price_counts_as_zero(self):
        assert material_cost_of([(20424, 1), (999999, 5)], PRICES) == pytest.approx(27890.0)

    def test_extra_items_added(self):
        got = material_cost_of([(20424, 1)], PRICES, extra=[(20423, 1)])
        assert got == pytest.approx(27890.0 + 96830.0)


class TestInventionPlanCost:
    def test_no_decryptor_module_golden(self):
        """无解码器、无技能：成功率 0.34、产出 10 流程、每次尝试材料 ¥124,720。

        需要 10 流程 → ceil(10 / (0.34×10)) = 3 次尝试。
        """
        r = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=JITA_INVENTION_SCI,
            base_runs=BASE_RUNS,
            output_runs_needed=10,
        )
        assert r["success_rate"] == pytest.approx(0.34)
        assert r["runs_per_bpc"] == 10
        assert r["attempts"] == 3
        assert r["material_cost"] == pytest.approx(124720.0 * 3)
        # 安装费 = EIV(124720×3) × (SCI + 税 + SCC)
        eiv = 124720.0 * 3
        assert r["fee"] == pytest.approx(eiv * (JITA_INVENTION_SCI + 0.0025 + 0.04), rel=1e-6)
        assert r["output_runs"] == 30
        assert not r["is_actual"]

    def test_amplified_decryptor_lowers_chance_but_raises_runs(self):
        """放大装置解码器：×0.60 → 成功率 0.204；+9 流程 → 产出 19 流程/次。

        需要 19 流程 → ceil(19 / (0.204×19)) = ceil(4.90) = 5 次尝试。
        """
        r = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=JITA_INVENTION_SCI,
            decryptor=DECRYPTORS[34203],
            base_runs=BASE_RUNS,
            output_runs_needed=19,
        )
        assert r["success_rate"] == pytest.approx(0.204)
        assert r["runs_per_bpc"] == 19
        assert r["attempts"] == 5
        # 材料含解码器（每次 1 个，¥708,900）
        decryptor_price = 708900.0
        prices = {**PRICES, 34203: decryptor_price}
        r2 = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=prices,
            sci=JITA_INVENTION_SCI,
            decryptor=DECRYPTORS[34203],
            base_runs=BASE_RUNS,
            output_runs_needed=19,
        )
        assert r2["material_cost"] == pytest.approx((124720.0 + decryptor_price) * 5)

    def test_decryptor_cost_is_charged_per_attempt(self):
        """解码器按尝试次数计（每次消耗 1 个），不是按产出。"""
        prices = {**PRICES, 34206: 250000.0}
        r = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=prices,
            sci=0.0,
            decryptor=DECRYPTORS[34206],
            base_runs=BASE_RUNS,
            output_runs_needed=1,
        )
        # 对称解码器 ×1.00、+2 流程 → 产出 12 流程；需 1 流程 → ceil(1/(0.34×12)) = 1 次
        assert r["attempts"] == 1
        assert r["material_cost"] == pytest.approx(124720.0 + 250000.0)

    def test_optimized_attainment_is_best_chance(self):
        """优化的获取装置 ×1.90 成功率最高（对比其余解码器）。"""
        rates = {}
        for tid, d in DECRYPTORS.items():
            r = invention_plan_cost(
                base_probability=BASE_PROB,
                materials=INVENTION_MATS,
                prices=PRICES,
                sci=0.0,
                decryptor=d,
                base_runs=BASE_RUNS,
                output_runs_needed=10,
            )
            rates[tid] = r["success_rate"]
        assert max(rates, key=lambda k: rates[k]) == 34207
        assert rates[34207] == pytest.approx(0.34 * 1.90)

    def test_lower_probability_decryptor_costs_more(self):
        """放大装置（×0.60）的总成本必须高于不使用解码器（同解出 10 流程）。"""
        prices = {**PRICES, 34203: 708900.0}
        plain = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=prices,
            sci=JITA_INVENTION_SCI,
            base_runs=BASE_RUNS,
            output_runs_needed=10,
        )
        amplified = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=prices,
            sci=JITA_INVENTION_SCI,
            decryptor=DECRYPTORS[34203],
            base_runs=BASE_RUNS,
            output_runs_needed=10,
        )
        assert amplified["total_cost"] > plain["total_cost"]

    def test_skills_raise_chance_and_lower_cost(self):
        no_skill = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=0.0,
            base_runs=BASE_RUNS,
            output_runs_needed=100,
        )
        skilled = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=0.0,
            science_skill_1=5,
            science_skill_2=5,
            encryption_skill=5,
            base_runs=BASE_RUNS,
            output_runs_needed=100,
        )
        assert skilled["success_rate"] > no_skill["success_rate"]
        assert skilled["attempts"] < no_skill["attempts"]
        assert skilled["total_cost"] < no_skill["total_cost"]

    def test_success_rate_override_wins(self):
        """用户手填的预期成功率优先于技能计算值。"""
        r = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=0.0,
            base_runs=BASE_RUNS,
            output_runs_needed=10,
            success_rate_override=0.5,
        )
        assert r["success_rate"] == pytest.approx(0.5)
        assert r["attempts"] == 2  # ceil(10 / 5)

    def test_input_bpc_cost_per_run_counted(self):
        """输入 T1 BPC 的每流程成本 × 尝试次数计入总成本。"""
        base = {
            "base_probability": BASE_PROB,
            "materials": INVENTION_MATS,
            "prices": PRICES,
            "sci": 0.0,
            "base_runs": BASE_RUNS,
            "output_runs_needed": 10,
        }
        plain = invention_plan_cost(**base)
        with_bpc = invention_plan_cost(**base, input_bpc_cost_per_run=1000.0)
        assert with_bpc["input_bpc_cost"] == pytest.approx(1000.0 * plain["attempts"])
        assert with_bpc["total_cost"] == pytest.approx(plain["total_cost"] + 1000.0 * plain["attempts"])

    def test_bpc_unit_cost_divides_by_output(self):
        r = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=0.0,
            base_runs=BASE_RUNS,
            output_runs_needed=10,
        )
        assert r["bpc_unit_cost"] == pytest.approx(r["total_cost"] / r["output_runs"])

    def test_actual_output_runs_switches_to_actual_basis(self):
        """回填实际产出后：output_runs 用实际值算 bpc_unit_cost，成本不变。"""
        common = {
            "base_probability": BASE_PROB,
            "materials": INVENTION_MATS,
            "prices": PRICES,
            "sci": 0.0,
            "base_runs": BASE_RUNS,
            "output_runs_needed": 10,
        }
        expected = invention_plan_cost(**common)
        actual = invention_plan_cost(**common, actual_output_runs=7)
        assert actual["is_actual"] is True
        assert actual["output_runs"] == 7
        assert actual["expected_runs"] == expected["expected_runs"]
        assert actual["total_cost"] == pytest.approx(expected["total_cost"])
        assert actual["bpc_unit_cost"] == pytest.approx(expected["total_cost"] / 7)
        assert actual["bpc_unit_cost"] > expected["bpc_unit_cost"]

    def test_actual_failure_zero_runs_no_div_by_zero(self):
        """发明失败（回填 0）：不崩，单位成本为 0（无产出）。"""
        r = invention_plan_cost(
            base_probability=BASE_PROB,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=0.0,
            base_runs=BASE_RUNS,
            output_runs_needed=10,
            actual_output_runs=0,
        )
        assert r["is_actual"] is True
        assert r["output_runs"] == 0
        assert r["bpc_unit_cost"] == 0.0
        assert r["total_cost"] > 0  # 材料照扣（游戏事实）

    def test_zero_probability_yields_zero_attempts(self):
        r = invention_plan_cost(
            base_probability=0.0,
            materials=INVENTION_MATS,
            prices=PRICES,
            sci=0.0,
            base_runs=BASE_RUNS,
            output_runs_needed=10,
        )
        assert r["attempts"] == 0
        assert r["output_runs"] == 0
        assert r["total_cost"] == 0.0


class TestCopyingPlanCost:
    def test_no_materials_only_installation_fee(self):
        """T1 蓝图拷贝材料为空（实测 821 无拷贝材料）→ 只有安装费。"""
        r = copying_plan_cost(materials=[], prices={}, sci=0.0014, total_copy_runs=200, copies=1)
        assert r["material_cost"] == 0.0
        assert r["fee"] == 0.0  # EIV=0 → 安装费 0
        assert r["total_cost"] == 0.0
        assert r["runs_per_copy"] == 200
        assert r["per_copy_cost"] == 0.0

    def test_materials_scale_with_total_runs(self):
        """材料按总授权流程数计（份数 × 每份流程），不是按份数。"""
        r = copying_plan_cost(
            materials=[(3812, 10)],
            prices={3812: 100.0},
            sci=0.0,
            total_copy_runs=200,
            copies=2,
        )
        assert r["material_cost"] == pytest.approx(10 * 200 * 100.0)
        assert r["runs_per_copy"] == 100
        assert r["per_copy_cost"] == pytest.approx(r["total_cost"] / 2)

    def test_installation_fee_uses_sci(self):
        r = copying_plan_cost(materials=[(3812, 1)], prices={3812: 1000.0}, sci=0.0014, total_copy_runs=1, copies=1)
        assert r["fee"] == pytest.approx(1000.0 * (0.0014 + 0.0025 + 0.04), rel=1e-6)


class TestResearchPlanCost:
    def test_target_level_scales_materials(self):
        r1 = research_plan_cost(materials=[(11459, 1)], prices={11459: 1000.0}, sci=0.0, target_level=1)
        r5 = research_plan_cost(materials=[(11459, 1)], prices={11459: 1000.0}, sci=0.0, target_level=5)
        assert r5["material_cost"] == pytest.approx(r1["material_cost"] * 5)
        assert r5["target_level"] == 5

    def test_zero_level_floored_to_one(self):
        r = research_plan_cost(materials=[(11459, 1)], prices={11459: 1000.0}, sci=0.0, target_level=0)
        assert r["target_level"] == 1
