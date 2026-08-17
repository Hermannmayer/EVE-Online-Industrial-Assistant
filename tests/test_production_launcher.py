"""产线启动小助手 UI 冒烟测试（slow，--quick 时跳过）。"""

import pytest
from PySide6.QtCore import Qt

import services.plan_execution as plan_execution

pytestmark = pytest.mark.ui

SAMPLE_PLANS = [
    {
        "id": 1,
        "product_type_id": 2001,
        "product_name": "渡鸦级",
        "blueprint_type_id": 3001,
        "status": "pending",
        "char_name": "甲",
        "category": "manufacturing",
        "group_id": 0,
        "child_level": 0,
        "runs": 1,
        "parallels": 1,
        "calculated_time": 3600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "仓库B",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 12345,
    },
    {
        "id": 2,
        "product_type_id": 2002,
        "product_name": "无人机",
        "blueprint_type_id": 3002,
        "status": "pending",
        "char_name": "甲",
        "category": "copying",
        "group_id": 0,
        "child_level": 0,
        "runs": 2,
        "parallels": 3,
        "calculated_time": 600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 999,
    },
    {
        "id": 3,
        "product_type_id": 2001,
        "product_name": "母项成品",
        "blueprint_type_id": 3001,
        "status": "pending",
        "char_name": "乙",
        "category": "manufacturing",
        "group_id": 10,
        "child_level": 0,
        "runs": 1,
        "parallels": 1,
        "calculated_time": 3600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "仓库B",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 100,
    },
    {
        "id": 4,
        "product_type_id": 2002,
        "product_name": "子项材料",
        "blueprint_type_id": 3002,
        "status": "pending",
        "char_name": "乙",
        "category": "manufacturing",
        "group_id": 10,
        "child_level": 1,
        "runs": 1,
        "parallels": 1,
        "calculated_time": 600,
        "mat_hangar_id": 1,
        "facility": "仓库A",
        "output_hangar": "",
        "has_image": True,
        "assigned_blueprint_id": None,
        "material_cost": 50,
    },
]


def _make_launcher(qapp, monkeypatch):
    from ui_pyside6.views.industry import production_launcher as pl

    monkeypatch.setattr(plan_execution, "expire_overdue_plans", lambda: 0)
    monkeypatch.setattr(plan_execution, "check_materials", lambda plan, mat: [])
    monkeypatch.setattr(plan_execution, "output_per_run", lambda tid: 1)
    monkeypatch.setattr(plan_execution, "start_plan", lambda *a, **k: {"ok": True, "message": "ok"})
    monkeypatch.setattr(pl, "load_plans_for_wizard", lambda: SAMPLE_PLANS)
    monkeypatch.setattr(pl, "load_item_icon", lambda tid, size=None: None)
    monkeypatch.setattr(pl, "get_character_list", lambda: ["甲", "乙"])
    monkeypatch.setattr(
        pl,
        "load_all_data",
        lambda: {
            "current": "甲",
            "characters": {
                "甲": {
                    "skills": {
                        "高级量产技术": 5,
                        "批量生产学": 5,
                        "高级实验室运作理论": 5,
                        "科学网络学": 5,
                        "大规模反应理论": 5,
                        "高级大规模反应理论": 5,
                    }
                },
                "乙": {"skills": {"高级量产技术": 5, "批量生产学": 5}},
            },
        },
    )
    monkeypatch.setattr("services.inventory_manager.get_default_mat_hangar_and_system", lambda: (None, None))
    monkeypatch.setattr(
        "services.ui_data_service.get_item_names_batch",
        lambda ids, db=None: {i: f"蓝图{i}" for i in ids},
    )

    w = pl.ProductionLauncher()
    w._tick_timer.stop()
    w._poll_timer.stop()
    return w, pl


class TestProductionLauncher:
    def test_constructs_and_builds_rows(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            assert w._list.count() == 4  # 全部计划
            assert len(w._widgets) == 4
            # 占用区渲染了 甲/乙 两行
            assert w._occ_layout.count() >= 2
        finally:
            w.close()

    def test_group_parent_first(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 组 10：母项 id=3 在前，子项 id=4 在后；独立计划 1/2 殿后
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [3, 4, 1, 2], ids
            # 母项有未完成子项 → 折叠按钮（含子项数）
            parent_row = w._widgets[3]
            assert parent_row._btn_toggle.isHidden() is False
            assert "折叠(1)" in parent_row._btn_toggle.text()
        finally:
            w.close()

    def test_collapse_toggle(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 折叠组 10 → 子项 id=4 隐藏
            w._on_row_toggle(10)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [3, 1, 2], ids
            parent_row = w._widgets[3]
            assert "展开(1)" in parent_row._btn_toggle.text()
            # 再次展开 → 子项恢复
            w._on_row_toggle(10)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [3, 4, 1, 2], ids
        finally:
            w.close()

    def test_startable_row_has_button(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            row = w._widgets[1]  # pending + 有图 + 无机库缺口 → 可启动
            assert row._btn_start.isHidden() is False
            assert row._btn_toggle.isHidden() is True
        finally:
            w.close()

    def test_blocked_row_blank_action(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            monkeypatch.setattr(w, "_block_reason", lambda plan: "生产中" if plan.get("id") == 2 else None)
            w._sync_rows(w._visible_plans)
            row = w._widgets[2]
            assert row._btn_start.isHidden() is True
            assert row._btn_toggle.isHidden() is True
        finally:
            w.close()

    def test_line_filter(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            idx = w._line_filter.findData("research")
            w._line_filter.setCurrentIndex(idx)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [2]  # 只有 copying → research
        finally:
            w.close()

    def test_char_filter(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            idx = w._char_filter.findData("甲")
            w._char_filter.setCurrentIndex(idx)
            ids = [w._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w._list.count())]
            assert ids == [1, 2]
        finally:
            w.close()

    def test_selection_updates_bottom(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        try:
            # 可见顺序 [3(母项), 4, 1, 2]；选索引 2 = 计划 1（可启动）
            w._list.setCurrentRow(2)
            assert w._main_btn.isHidden() is False
            assert w._main_btn.text() == "渡鸦级 x 1"
        finally:
            w.close()

    def test_start_calls_plan_execution(self, qapp, monkeypatch):
        import services.plan_execution as plan_execution

        w, _ = _make_launcher(qapp, monkeypatch)
        calls = []

        def fake_start(plan, *, mat_hangar_id, char_name, **kw):
            calls.append((plan.get("id"), char_name))
            return {"ok": True, "message": "ok"}

        monkeypatch.setattr(plan_execution, "start_plan", fake_start)
        try:
            w._start(1)
            assert calls == [(1, "甲")]  # 默认执行人物 = 计划人物甲
        finally:
            w.close()

    def test_close_stops_timers(self, qapp, monkeypatch):
        w, _ = _make_launcher(qapp, monkeypatch)
        w._tick_timer.start()
        w._poll_timer.start()
        w.close()
        assert w._tick_timer.isActive() is False
        assert w._poll_timer.isActive() is False
