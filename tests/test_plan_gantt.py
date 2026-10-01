"""甘特图排期测试 — 树序行 / 子项先跑母项接后 / 末端完成时刻。

原先这些断言挂在 `GanttView`（QWidget）上，阶段 2b 把绘制交给 QML、排期计算
上移到 `services/plan_gantt.py`，于是不再需要构造 QWidget，全部归入 fast 档。
绘制细节（画笔/颜色/像素）不在断言范围内。
"""

from datetime import UTC, datetime, timedelta

import pytest

from services.plan_gantt import build_rows, end_time_text, max_hours


def _plan(
    plan_id: int,
    *,
    name: str = "部件",
    tid: int = 2001,
    group: int = 0,
    level: int = 0,
    hours: float = 2,
    parent_tid: int | None = None,
    status: str = "pending",
    started_at: str | None = None,
) -> dict:
    """一条计划夹具（只含甘特图用到的字段）。"""
    return {
        "id": plan_id,
        "product_type_id": tid,
        "product_name": name,
        "group_number": group,
        "sub_level": level,
        "calculated_time": hours * 3600,
        "runs": 1,
        "parallels": 1,
        "status": status,
        "started_at": started_at,
        "component_parent_type_id": parent_tid,
    }


def _starts(plans: list[dict]) -> dict[str, float]:
    return {r["name"]: r["start"] for r in build_rows(plans)}


@pytest.mark.fast
class TestGanttScheduling:
    def test_children_run_first_mother_after(self):
        """子项各自从 0 起并行，母项等全部子项结束才开工。"""
        mother = _plan(1, name="母项", tid=2001, group=7, hours=4)
        c1 = _plan(2, name="子项A", tid=3001, group=7, level=1, hours=3, parent_tid=2001)
        c2 = _plan(3, name="子项B", tid=3002, group=7, level=1, hours=5, parent_tid=2001)

        starts = _starts([mother, c1, c2])
        assert starts["子项A"] == 0
        assert starts["子项B"] == 0
        assert starts["母项"] == 5  # max(3, 5)，不是 0（旧行为：全部并行）

    def test_standalone_plans_start_at_zero(self):
        rows = build_rows([_plan(1, name="独立A", tid=2001, hours=3), _plan(2, name="独立B", tid=2002, hours=9)])
        assert [r["start"] for r in rows] == [0, 0]

    def test_groups_do_not_chain(self):
        """不同组是不同产品，各自从 0 起 —— 跨组不串行。"""
        m1 = _plan(1, name="母项1", tid=2001, group=7, hours=1)
        c1 = _plan(2, name="子1", tid=3001, group=7, level=1, hours=8, parent_tid=2001)
        m2 = _plan(3, name="母项2", tid=4001, group=8, hours=1)
        c2 = _plan(4, name="子2", tid=5001, group=8, level=1, hours=2, parent_tid=4001)

        starts = _starts([m1, c1, m2, c2])
        assert starts["母项1"] == 8
        assert starts["母项2"] == 2

    def test_multi_level_bom_pushes_layer_by_layer(self):
        """多层 BOM：最底层先做，逐层往上推。"""
        mother = _plan(1, name="母项", tid=2001, group=7, hours=1)
        mid = _plan(2, name="中间件", tid=3001, group=7, level=1, hours=2, parent_tid=2001)
        leaf = _plan(3, name="原料件", tid=4001, group=7, level=2, hours=6, parent_tid=3001)

        starts = _starts([mother, mid, leaf])
        assert starts["原料件"] == 0
        assert starts["中间件"] == 6
        assert starts["母项"] == 8

    def test_row_order_is_tree_order(self):
        """行序母项在前、子项紧随（即「子项排在母项后面」），与 DB 的时间倒序无关。"""
        mother = _plan(1, name="母项", tid=2001, group=7)
        child = _plan(2, name="子项", tid=3001, group=7, level=1, parent_tid=2001)
        standalone = _plan(9, name="独立", tid=9001)

        rows = build_rows([standalone, child, mother])
        assert [r["name"] for r in rows] == ["母项", "子项", "独立"]

    def test_synthetic_root_not_drawn(self):
        """共享组件的合成根行（id=None）不是真实计划，不画柱子。"""
        shared = _plan(2, name="共享件", tid=3001, group=7, level=1, parent_tid=2001)
        shared["source_mother_ids"] = "1,3"

        rows = build_rows([shared])
        assert [r["name"] for r in rows] == ["共享件"]

    def test_max_hours_covers_rightmost_bar(self):
        mother = _plan(1, name="母项", tid=2001, group=7, hours=4)
        child = _plan(2, name="子项", tid=3001, group=7, level=1, hours=30, parent_tid=2001)

        rows = build_rows([mother, child])
        assert max_hours(rows) >= 34  # 子项 30 + 母项 4
        assert max_hours(rows) % 12 == 0

    def test_missing_calculated_time_falls_back_to_run_estimate(self):
        """`calculated_time` 为 0 时按「流程数 × 并行数 × 2h」兜底，不画成 0 宽。"""
        plan = _plan(1, name="无时长", tid=2001, hours=0)
        plan["runs"] = 3
        plan["parallels"] = 2
        rows = build_rows([plan])
        assert rows[0]["duration"] == 12.0


@pytest.mark.fast
class TestGanttEndTime:
    def test_pending_plan_end_is_now_plus_offset(self):
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        plan = _plan(1)

        text = end_time_text(plan, 5, now)

        expected = (now.astimezone().replace(tzinfo=None) + timedelta(hours=5)).strftime("%m-%d %H:%M")
        assert text == expected

    def test_running_plan_uses_real_eta_ignoring_offset(self):
        """在产计划按 started_at 推真实完成时刻（与倒计时列同源），排期偏移不参与。"""
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        started = (now - timedelta(hours=2)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        plan = _plan(1, status="in_progress", started_at=started, hours=5)

        text = end_time_text(plan, 999, now)  # end_hours 应被忽略

        assert text == (now + timedelta(hours=3)).astimezone().strftime("%m-%d %H:%M")

    def test_running_without_started_at_falls_back(self):
        """异常数据（在产但没有 started_at）→ 退回「现在 + 偏移」，不崩。"""
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        plan = _plan(1, status="in_progress", started_at=None)

        text = end_time_text(plan, 2, now)

        assert text == (now.astimezone().replace(tzinfo=None) + timedelta(hours=2)).strftime("%m-%d %H:%M")


@pytest.mark.fast
class TestGanttAxisFollowsTheClock:
    """横轴口径 —— 对应用户提的三条：图随时间缩短 / 刻度按日期 / 完工不占位。

    回归背景（2026-09-28）：原先每行 `start` 恒为 0、`duration` 恒为**完整**时长，
    轴的起点永远与真实时间无关 —— 于是「长度不随时间推进缩短，永远等长」，而且一条
    已开工 8 小时、只剩 2 小时的计划柱子仍画满原始时长，右侧 ETA 文字却是真实的
    `now + 2h`（柱长与标签自相矛盾）。
    """

    def test_finished_plans_do_not_take_horizontal_space(self):
        """完工的行不画 —— 图上只留「还要做的事」，做完了自然变短。"""
        plans = [_plan(1, name="做完的", hours=5, status="completed"), _plan(2, name="待做的", hours=3)]
        assert [r["name"] for r in build_rows(plans)] == ["待做的"]

    def test_running_plan_draws_only_the_remaining_time(self):
        """在产行按**剩余**时长画：开工越久条越短（这就是「随时间推进而缩短」）。"""
        started = (datetime.now(UTC) - timedelta(hours=4)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        rows = build_rows([_plan(1, name="在产", hours=6, status="in_progress", started_at=started)])

        assert len(rows) == 1
        # 总时长 6h、已跑 4h → 剩 ~2h（放容差给用例自身的执行耗时）
        assert 1.5 < rows[0]["duration"] < 2.5, rows[0]["duration"]

    def test_axis_is_rounded_to_whole_days(self):
        """轴上限按**整天**取整 —— 刻度是「几月几号」，不按整天取整会把末刻度顶出轴外。"""
        from services.plan_gantt import AXIS_GRANULARITY

        assert AXIS_GRANULARITY == 24, "日期刻度必须按整天取整"
        rounded = max_hours(build_rows([_plan(1, hours=30)]))
        assert rounded == 48, rounded  # 30h 向上取整到 2 天
        assert rounded % 24 == 0

    def test_axis_start_is_an_absolute_instant(self):
        """轴起点必须是**绝对时刻**（QML 靠它把「第 n 天」换算成日期）；可注入才好断言。"""
        from services.plan_gantt import axis_start_ms

        fixed = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)
        assert axis_start_ms(fixed) == pytest.approx(fixed.timestamp() * 1000.0)
