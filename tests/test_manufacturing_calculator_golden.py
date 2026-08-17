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
