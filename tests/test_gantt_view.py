"""甘特图排期测试 — 树序行 / 子项先跑母项接后 / 末端完成时刻 / 主题监听。

该文件覆盖此前为零的甘特图逻辑：排期正确性只靠 `load_from_plans` 之后的
`start`/`duration` 断言，绘制细节不在测试范围内。
"""

from datetime import UTC, datetime, timedelta

import pytest

import ui_pyside6.theme as theme
from ui_pyside6.views.industry.gantt_view import GanttView

pytestmark = pytest.mark.ui


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


def _starts(view: GanttView) -> dict[str, float]:
    return {i["name"]: i["start"] for i in view._items}


class TestGanttScheduling:
    def test_children_run_first_mother_after(self, qapp):
        """子项各自从 0 起并行，母项等全部子项结束才开工。"""
        mother = _plan(1, name="母项", tid=2001, group=7, hours=4)
        c1 = _plan(2, name="子项A", tid=3001, group=7, level=1, hours=3, parent_tid=2001)
        c2 = _plan(3, name="子项B", tid=3002, group=7, level=1, hours=5, parent_tid=2001)

        view = GanttView()
        view.load_from_plans([mother, c1, c2])

        starts = _starts(view)
        assert starts["子项A"] == 0
        assert starts["子项B"] == 0
        assert starts["母项"] == 5  # max(3, 5)，不是 0（旧行为：全部并行）

    def test_standalone_plans_start_at_zero(self, qapp):
        view = GanttView()
        view.load_from_plans([_plan(1, name="独立A", tid=2001, hours=3), _plan(2, name="独立B", tid=2002, hours=9)])
        assert [i["start"] for i in view._items] == [0, 0]

    def test_groups_do_not_chain(self, qapp):
        """不同组是不同产品，各自从 0 起 —— 跨组不串行。"""
        m1 = _plan(1, name="母项1", tid=2001, group=7, hours=1)
        c1 = _plan(2, name="子1", tid=3001, group=7, level=1, hours=8, parent_tid=2001)
        m2 = _plan(3, name="母项2", tid=4001, group=8, hours=1)
        c2 = _plan(4, name="子2", tid=5001, group=8, level=1, hours=2, parent_tid=4001)

        view = GanttView()
        view.load_from_plans([m1, c1, m2, c2])

        starts = _starts(view)
        assert starts["母项1"] == 8
        assert starts["母项2"] == 2

    def test_multi_level_bom_pushes_layer_by_layer(self, qapp):
        """多层 BOM：最底层先做，逐层往上推。"""
        mother = _plan(1, name="母项", tid=2001, group=7, hours=1)
        mid = _plan(2, name="中间件", tid=3001, group=7, level=1, hours=2, parent_tid=2001)
        leaf = _plan(3, name="原料件", tid=4001, group=7, level=2, hours=6, parent_tid=3001)

        view = GanttView()
        view.load_from_plans([mother, mid, leaf])

        starts = _starts(view)
        assert starts["原料件"] == 0
        assert starts["中间件"] == 6
        assert starts["母项"] == 8

    def test_row_order_is_tree_order(self, qapp):
        """行序母项在前、子项紧随（即「子项排在母项后面」），与 DB 的时间倒序无关。"""
        mother = _plan(1, name="母项", tid=2001, group=7)
        child = _plan(2, name="子项", tid=3001, group=7, level=1, parent_tid=2001)
        standalone = _plan(9, name="独立", tid=9001)

        view = GanttView()
        view.load_from_plans([standalone, child, mother])

        assert [i["name"] for i in view._items] == ["母项", "子项", "独立"]

    def test_synthetic_root_not_drawn(self, qapp):
        """共享组件的合成根行（id=None）不是真实计划，不画柱子。"""
        shared = _plan(2, name="共享件", tid=3001, group=7, level=1, parent_tid=2001)
        shared["source_mother_ids"] = "1,3"

        view = GanttView()
        view.load_from_plans([shared])

        assert [i["name"] for i in view._items] == ["共享件"]

    def test_max_hours_covers_rightmost_bar(self, qapp):
        mother = _plan(1, name="母项", tid=2001, group=7, hours=4)
        child = _plan(2, name="子项", tid=3001, group=7, level=1, hours=30, parent_tid=2001)

        view = GanttView()
        view.load_from_plans([mother, child])

        assert view._max_hours >= 34  # 子项 30 + 母项 4
        assert view._max_hours % 12 == 0


class TestGanttEndTime:
    def test_pending_plan_end_is_now_plus_offset(self, qapp):
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        plan = _plan(1)

        text = GanttView._end_time_text(plan, 5, now)

        expected = (now.astimezone().replace(tzinfo=None) + timedelta(hours=5)).strftime("%m-%d %H:%M")
        assert text == expected

    def test_running_plan_uses_real_eta_ignoring_offset(self, qapp):
        """在产计划按 started_at 推真实完成时刻（与倒计时列同源），排期偏移不参与。"""
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        started = (now - timedelta(hours=2)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        plan = _plan(1, status="in_progress", started_at=started, hours=5)

        text = GanttView._end_time_text(plan, 999, now)  # end_hours 应被忽略

        assert text == (now + timedelta(hours=3)).astimezone().strftime("%m-%d %H:%M")

    def test_running_without_started_at_falls_back(self, qapp):
        """异常数据（在产但没有 started_at）→ 退回「现在 + 偏移」，不崩。"""
        now = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
        plan = _plan(1, status="in_progress", started_at=None)

        text = GanttView._end_time_text(plan, 2, now)

        assert text == (now.astimezone().replace(tzinfo=None) + timedelta(hours=2)).strftime("%m-%d %H:%M")


class TestGanttTheme:
    def test_registers_theme_listener(self, qapp, monkeypatch):
        """必须注册主题监听 —— 否则换主题后配色不跟随（历史缺陷）。"""
        seen: list = []
        monkeypatch.setattr(theme, "add_theme_listener", lambda cb: seen.append(cb))

        GanttView()

        assert len(seen) == 1
        assert seen[0].__self__.__class__ is GanttView
