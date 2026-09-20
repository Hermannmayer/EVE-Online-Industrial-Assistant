"""ESI 导入的合并策略 —— 纯函数，无 Qt / 无 DB。

这三条策略决定「从 ESI 拿回来的数据怎么落进 char_config」。算错的表现都是
**静默的**：技能等级被改错、或者配置被 ESI 的几百个技能撑爆，界面看不出异常。
所以逐条钉住。

放在这里而不是 `test_char_config_validator.py`：被测对象是
`core/char_settings_common.py`，跟那个校验器不是一个模块。
"""

from __future__ import annotations

import pytest

from core.char_settings_common import (
    apply_skill_queue_finished,
    merge_esi_skill_levels,
    union_skill_levels,
)

pytestmark = pytest.mark.fast

_NOW = "2026-09-20T00:00:00Z"

#: 一个小号「面板」，用来把期望值写死，不必抄一百个技能名
_PANEL = ["工业理论", "批量生产学", "冶金学"]


@pytest.mark.parametrize(
    ("levels", "queue", "expected"),
    [
        # 还没到时间的条目不算 —— 这是「队列里在练的技能不该提前生效」
        ({3387: 3}, [{"skill_id": 3387, "finished_level": 5, "finish_date": "2999-01-01T00:00:00Z"}], {3387: 3}),
        # 已完成：覆盖 /skills 里的旧等级。这就是补队列的全部意义 ——
        # 角色离线期间练完的技能，/skills 不会体现（CCP 文档明说会过期）
        ({3387: 3}, [{"skill_id": 3387, "finished_level": 5, "finish_date": "2026-09-19T00:00:00Z"}], {3387: 5}),
        # 边界：finish_date 恰好等于 now 也算练完
        ({3387: 3}, [{"skill_id": 3387, "finished_level": 4, "finish_date": _NOW}], {3387: 4}),
        # /skills 里没有的技能，队列也能补进来
        ({}, [{"skill_id": 3443, "finished_level": 2, "finish_date": "2026-09-19T00:00:00Z"}], {3443: 2}),
        # 队列里的等级更低时不降级（取 max，而不是以队列为准）
        ({3387: 5}, [{"skill_id": 3387, "finished_level": 1, "finish_date": "2026-09-19T00:00:00Z"}], {3387: 5}),
        # 脏条目：缺 finish_date、缺 skill_id 都要跳过而不是抛异常（ESI 是外部数据源）
        (
            {3387: 3},
            [
                {"skill_id": 3387, "finished_level": 5},
                {"finished_level": 5, "finish_date": "2020-01-01T00:00:00Z"},
                {},
            ],
            {3387: 3},
        ),
        # 空队列 / 空技能
        ({}, [], {}),
    ],
)
def test_apply_skill_queue_finished(levels, queue, expected):
    original = dict(levels)

    assert apply_skill_queue_finished(levels, queue, _NOW) == expected
    assert levels == original, "不得就地修改入参（调用方会复用同一个 levels）"


@pytest.mark.parametrize(
    ("existing", "esi", "expected"),
    [
        # ⭐ 用户报的缺陷的回归：面板上的技能（造船、冶金、研究那一大片）以前
        # **一个都不写**，因为它们在 char_config 里没有手填过 —— 于是面板上
        # 除手填过的那十几个之外全是 0，看起来像「没导入」。现在面板全集都要写。
        ({}, {"冶金学": 4}, {"工业理论": 0, "批量生产学": 0, "冶金学": 4}),
        # 已有的手工值被 ESI 的真实等级纠正
        ({"批量生产学": 3}, {"批量生产学": 5}, {"工业理论": 0, "批量生产学": 5, "冶金学": 0}),
        # 用户自建的、不在面板里的技能名保留原值
        ({"自建技能": 2}, {}, {"工业理论": 0, "批量生产学": 0, "冶金学": 0, "自建技能": 2}),
        # ESI 独有的、不属于面板的技能仍然**不写**（否则配置被几百个技能撑爆）
        ({}, {"贸易学": 5, "某冷门技能": 3}, {"工业理论": 0, "批量生产学": 0, "冶金学": 0}),
    ],
)
def test_merge_covers_whole_panel_and_keeps_custom_names(existing, esi, expected):
    original = dict(existing)

    assert merge_esi_skill_levels(existing, esi, _PANEL) == expected
    assert existing == original, "不得就地修改入参"


@pytest.mark.parametrize(
    ("characters", "esi", "expected"),
    [
        # 面板全集 ∪ 其它角色的自建技能名；等级取自 ESI，缺的记 0
        (
            {"甲": {"skills": {"自建技能": 5}}},
            {"批量生产学": 3},
            {"工业理论": 0, "批量生产学": 3, "冶金学": 0, "自建技能": 0},
        ),
        # 没有任何现有角色 → 只剩面板全集
        ({}, {"工业理论": 5}, {"工业理论": 5, "批量生产学": 0, "冶金学": 0}),
        # 角色条目缺 skills 键也不该炸
        ({"甲": {}}, {}, {"工业理论": 0, "批量生产学": 0, "冶金学": 0}),
    ],
)
def test_union_skill_levels_fills_panel(characters, esi, expected):
    assert union_skill_levels(characters, esi, _PANEL) == expected
