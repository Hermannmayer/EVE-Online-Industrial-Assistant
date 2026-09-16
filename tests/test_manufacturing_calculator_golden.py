"""制造计算金标准测试 — 用游戏内实测确认的真实数值锁定公式

⚠️ 这些数值来自游戏内实际验证（用户实测）+ 最新 SDE 实际解析，勿改。
若测试变红 → 先验证 EVE 机制/SDE 格式是否变更，再确认是否修改公式。

背景（2026-07-31 审计澄清）：
- 最新 SDE 的 blueprints.yaml 已移除 wasteFactor 字段，materials.quantity
  直接包含浪费（即 ME0 时的游戏内需求量）
- 当前公式 `(100 - ME) / 100`（每级 -1%）与官方 wiki「每个流程可以减少
  1% 的材料需求量」及游戏实测一致
- 旧公式 `1 + wf/(100*(1+ME))` 是 wasteFactor 时代（Crius 前）的过时实现
"""

import pytest

from domain.formulas import material_total_for_runs
from services.manufacturing_calculator import calc_material_for_runs, calc_material_per_run

pytestmark = pytest.mark.fast

# ════════════════════════════════════════════════════════════
#  金标准数值：BP 683 惩罚者级 Bantam（游戏内实测 + 最新 SDE）
#  ME0 需求量 = SDE quantity（含浪费）
# ════════════════════════════════════════════════════════════

# (material_name, SDE quantity, ME0 需求, ME10 需求)
# ME10 = ME0 × 0.9，向上取整（1875×0.9=1687.5→1688；375×0.9=337.5→338）
BANTAM_MATERIALS = [
    ("三钛合金 Tritanium", 24000, 24000, 21600),
    ("类晶体矿 Pyerite", 4500, 4500, 4050),
    ("类银超金属 Mexallon", 1875, 1875, 1688),
    ("异构核素 Isogen", 375, 375, 338),
]


def test_bantam_me0_per_run_matches_game():
    """ME0 单轮：需求 = SDE quantity（含浪费）——用户游戏实测确认"""
    for name, sde_qty, me0_qty, _me10 in BANTAM_MATERIALS:
        got = calc_material_per_run(sde_qty, wastefactor=10, me_level=0)
        assert got == me0_qty, f"{name}: ME0 期望 {me0_qty}，实际 {got}"


def test_bantam_me10_per_run_matches_game():
    """ME10 单轮：×0.9 向上取整——官方 wiki「每级 -1%」"""
    for name, sde_qty, _me0, me10_qty in BANTAM_MATERIALS:
        got = calc_material_per_run(sde_qty, wastefactor=10, me_level=10)
        assert got == me10_qty, f"{name}: ME10 期望 {me10_qty}，实际 {got}"


def test_bantam_me0_runs_total_matches_game():
    """多轮次总量 = 单轮 × runs（材料效率适用于整个项目）"""
    runs = 10
    for name, sde_qty, me0_qty, _me10 in BANTAM_MATERIALS:
        got = calc_material_for_runs(sde_qty, wastefactor=10, me_level=0, runs=runs)
        assert got == me0_qty * runs, f"{name}: {runs} 轮期望 {me0_qty * runs}，实际 {got}"


def test_wastefactor_is_ignored_but_kept_for_compat():
    """wastefactor 参数保留兼容但不再参与计算（SDE 已移除该字段）"""
    # 相同 ME 下，不同 wastefactor 应得到相同结果
    a = calc_material_per_run(100, wastefactor=10, me_level=5)
    b = calc_material_per_run(100, wastefactor=2, me_level=5)
    assert a == b == 95, "wastefactor 不应影响结果（ME5 = ×0.95 → ceil(95))"


def test_single_unit_items_exempt_from_me():
    """单件物品（qty≤1）不受 ME 影响：ceil(1×x)=1 恒成立"""
    assert calc_material_per_run(1, wastefactor=10, me_level=0) == 1
    assert calc_material_per_run(1, wastefactor=10, me_level=10) == 1


def test_me_clamped_at_10():
    """ME 上限 10（SDE/游戏机制），超过仍按 10 计算"""
    assert calc_material_per_run(1000, wastefactor=10, me_level=99) == 900
    assert calc_material_per_run(1000, wastefactor=10, me_level=-5) == 1000


# ════════════════════════════════════════════════════════════════════
#  整批取整的**判别性锚点**（上面那条 ME0 的用例两口径恒等，挡不住回归）
# ════════════════════════════════════════════════════════════════════


def test_bantam_me10_runs_total_is_rounded_once_for_the_whole_batch():
    """ME10 多轮：对**整批**取一次整 —— 这才是「材料效率适用于整个项目」的判别性证据。

    上面 `test_bantam_me0_runs_total_matches_game` 取 ME0，`ceil(qty×runs×1.0)` 与
    `ceil(qty×1.0)×runs` 恒等，**数值上分不出两种口径**。ME10 才分得出：
    类银超金属 1875 → `ceil(1875×10×0.9) = 16875`，逐轮口径则是 `1688×10 = 16880`（多要 5）。
    异构核素 375 同理：3375（整批） vs 3380（逐轮）。
    """
    runs = 10
    for name, sde_qty, _me0, _me10 in BANTAM_MATERIALS:
        whole = calc_material_for_runs(sde_qty, wastefactor=10, me_level=10, runs=runs)
        per_run_times_runs = calc_material_per_run(sde_qty, wastefactor=10, me_level=10) * runs
        assert whole <= per_run_times_runs, f"{name}: 整批口径不可能比逐轮口径要得更多"
    # 至少有一种材料上两者必须**不等**，否则这条用例没有判别力
    diffs = [
        name
        for name, q, _m0, _m10 in BANTAM_MATERIALS
        if calc_material_per_run(q, wastefactor=10, me_level=10) * runs
        - calc_material_for_runs(q, wastefactor=10, me_level=10, runs=runs)
        > 0
    ]
    assert diffs, "这批数据分不出两种口径，用例失效"
    # 定量锚点：1875→16880 vs 16875、375→3380 vs 3375，各差 5
    assert calc_material_per_run(1875, wastefactor=10, me_level=10) * runs == 16880
    assert calc_material_for_runs(1875, wastefactor=10, me_level=10, runs=runs) == 16875
    assert calc_material_per_run(375, wastefactor=10, me_level=10) * runs == 3380
    assert calc_material_for_runs(375, wastefactor=10, me_level=10, runs=runs) == 3375


def test_material_total_for_runs_matches_the_real_over_request_bug():
    """回归锚点：用户实机那一单 —— 基础量 22、2510 次作业、ME10。

    逐轮口径要 50,200，整批口径只要 49,698；用户仓库里存的**正是 49,698**，
    于是「材料刚好够」被误判成「缺 502」。这个数来自实机 `production_plans.material_short`
    （`{"16672": 502, "16680": 1757, "16681": 502}`）。
    """
    runs = 502 * 5  # runs × parallels
    cases = [(22, 49_698, 50_200), (7, 15_813, 17_570), (2, 4_518, 5_020)]
    for base, whole_expected, per_run_expected in cases:
        mat = {"base_qty": base, "wastefactor": 10}
        got = material_total_for_runs(mat, runs, me_level=10)
        assert got == whole_expected, f"基础量 {base}: 期望 {whole_expected}，实际 {got}"
        assert calc_material_per_run(base, wastefactor=10, me_level=10) * runs == per_run_expected, (
            f"逐轮口径的对照值变了，说明公式被改过：基础量 {base}"
        )


def test_material_total_for_runs_single_run_equals_per_run():
    """只有一次作业时两口径必须逐值相同 —— 这是「本次改动不动小批量」的保证。"""
    for sde_qty in (1, 2, 7, 22, 375, 1875, 24000):
        mat = {"base_qty": sde_qty, "wastefactor": 10}
        assert material_total_for_runs(mat, 1, me_level=10) == calc_material_per_run(
            sde_qty, wastefactor=10, me_level=10
        )


def test_material_total_for_runs_keeps_the_single_unit_exemption():
    """单件材料（基础量 ≤1）保持豁免 ME —— 用户确认保留的既有口径。"""
    mat = {"base_qty": 1, "wastefactor": 10}
    # 豁免 = 不减 ME：2510 次作业就是 2510 个，而不是 ceil(2510×0.9)=2259
    assert material_total_for_runs(mat, 2510, me_level=10) == 2510


def test_material_total_for_runs_applies_structure_saving_on_the_batch():
    """结构减免与 ME 一样作用在整批上（同一个 ceil），不能被位置参数吞掉。"""
    mat = {"base_qty": 100, "wastefactor": 10}
    # ceil(100 × 10 × 1.0 × 0.5) = 500
    assert material_total_for_runs(mat, 10, me_level=0, structure_mat_saving=0.5) == 500
    # ceil(100 × 10 × 0.9 × 0.5) = 450
    assert material_total_for_runs(mat, 10, me_level=10, structure_mat_saving=0.5) == 450
